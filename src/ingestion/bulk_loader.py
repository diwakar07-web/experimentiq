"""
ExperimentIQ — Bulk Data Loader

Purpose:
    Loads validated DataFrames into PostgreSQL using the most efficient
    available strategy. Uses PostgreSQL's COPY command (via psycopg2's
    copy_expert) for maximum throughput — significantly faster than
    row-by-row INSERT or even SQLAlchemy's bulk_insert_mappings.

Design:
    - Tables are loaded in FK dependency order to satisfy constraints.
    - Each table load is an atomic transaction: commit on success, rollback on failure.
    - Chunk-based COPY for memory efficiency on large tables.
    - Idempotent: TRUNCATE with RESTART IDENTITY CASCADE before loading
      (configurable; default is to append without truncation for reruns).
    - Row counts are validated after load.

Dependencies:
    - psycopg2-binary
    - pandas >= 2.2
    - src/ingestion/db_connection.py

Inputs:
    Dictionary mapping table names to validated pandas DataFrames.

Outputs:
    Loaded PostgreSQL tables; logged row counts.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
import psycopg2.extensions
import psycopg2.extras

from src.ingestion.db_connection import get_raw_psycopg2_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default COPY batch size (number of rows per COPY invocation)
DEFAULT_CHUNK_SIZE = 10_000

# FK-aware loading order for core tables
# Lookup tables (already seeded in schema.sql) are excluded from bulk load
LOAD_ORDER: List[str] = [
    "users",
    "experiments",
    "sessions",
    "events",
    "orders",
]


# ---------------------------------------------------------------------------
# BulkLoader
# ---------------------------------------------------------------------------


class BulkLoader:
    """
    Loads DataFrames into PostgreSQL tables using high-performance COPY.

    Usage:
        loader = BulkLoader()
        loader.load_all(dataframes_dict, truncate_first=True)

    Attributes:
        chunk_size: Number of rows per COPY batch.
        load_results: Dict mapping table names to (rows_loaded, duration_s) after load.
    """

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        """
        Initialise the BulkLoader.

        Args:
            chunk_size: Number of rows per COPY batch for memory control.
        """
        self.chunk_size = chunk_size
        self.load_results: Dict[str, Tuple[int, float]] = {}

    def load_all(
        self,
        dataframes: Dict[str, pd.DataFrame],
        truncate_first: bool = False,
    ) -> None:
        """
        Load all DataFrames in FK-aware order.

        Args:
            dataframes: Dict mapping table names to DataFrames.
            truncate_first: If True, truncate each table before loading.
                            Use with caution — this deletes all existing data.

        Raises:
            KeyError: If a table in LOAD_ORDER is not present in dataframes.
            psycopg2.Error: If any table load fails (pipeline stops).
        """
        logger.info(
            "Starting bulk load | tables=%d | chunk_size=%d | truncate=%s",
            len(dataframes),
            self.chunk_size,
            truncate_first,
        )

        conn = get_raw_psycopg2_connection()
        try:
            for table_name in LOAD_ORDER:
                if table_name not in dataframes:
                    logger.warning("Table '%s' not found in dataframes — skipping", table_name)
                    continue

                df = dataframes[table_name]
                if df.empty:
                    logger.warning("DataFrame for '%s' is empty — skipping", table_name)
                    continue

                self._load_table(conn, table_name, df, truncate_first)
        finally:
            conn.close()
            logger.debug("psycopg2 connection closed")

        self._log_load_summary()

    def _load_table(
        self,
        conn: psycopg2.extensions.connection,
        table_name: str,
        df: pd.DataFrame,
        truncate_first: bool,
    ) -> None:
        """
        Load a single DataFrame into a PostgreSQL table using COPY FROM.

        Args:
            conn: Open psycopg2 connection.
            table_name: Target table name.
            df: DataFrame to load.
            truncate_first: If True, truncate the table before loading.

        Raises:
            psycopg2.Error: On database failure (triggers rollback).
        """
        start_time = time.perf_counter()
        logger.info("Loading table '%s' | rows=%s", table_name, f"{len(df):,}")

        try:
            if truncate_first:
                self._truncate_table(conn, table_name)

            total_rows = self._copy_dataframe(conn, table_name, df)
            conn.commit()

            elapsed = time.perf_counter() - start_time
            self.load_results[table_name] = (total_rows, elapsed)
            logger.info(
                "Loaded '%s' | rows=%s | duration=%.2fs | throughput=%.0f rows/s",
                table_name,
                f"{total_rows:,}",
                elapsed,
                total_rows / elapsed if elapsed > 0 else 0,
            )

        except psycopg2.Error as exc:
            conn.rollback()
            logger.error(
                "FAILED loading '%s' | error_code=%s | detail=%s",
                table_name,
                exc.pgcode,
                exc.pgerror,
            )
            raise

    def _truncate_table(
        self,
        conn: psycopg2.extensions.connection,
        table_name: str,
    ) -> None:
        """
        Truncate a table with RESTART IDENTITY CASCADE.

        Args:
            conn: Open psycopg2 connection.
            table_name: Table to truncate.
        """
        with conn.cursor() as cursor:
            cursor.execute(
                f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"
            )
        logger.debug("Truncated table: %s", table_name)

    def _copy_dataframe(
        self,
        conn: psycopg2.extensions.connection,
        table_name: str,
        df: pd.DataFrame,
    ) -> int:
        """
        Copy a DataFrame into a table using PostgreSQL COPY FROM STDIN.

        Processes the DataFrame in chunks to limit memory usage.

        Args:
            conn: Open psycopg2 connection.
            table_name: Target table name.
            df: DataFrame to copy.

        Returns:
            Total number of rows copied.
        """
        columns = list(df.columns)
        columns_str = ", ".join(f'"{c}"' for c in columns)
        copy_sql = (
            f"COPY {table_name} ({columns_str}) "
            f"FROM STDIN WITH (FORMAT CSV, NULL '', HEADER FALSE)"
        )

        total_rows = 0
        n_chunks = (len(df) + self.chunk_size - 1) // self.chunk_size

        for chunk_idx in range(n_chunks):
            chunk_start = chunk_idx * self.chunk_size
            chunk_end = min(chunk_start + self.chunk_size, len(df))
            chunk = df.iloc[chunk_start:chunk_end]

            csv_buffer = self._dataframe_to_csv_buffer(chunk)
            with conn.cursor() as cursor:
                cursor.copy_expert(copy_sql, csv_buffer)

            total_rows += len(chunk)
            logger.debug(
                "COPY chunk %d/%d | rows=%d | table=%s",
                chunk_idx + 1,
                n_chunks,
                len(chunk),
                table_name,
            )

        return total_rows

    @staticmethod
    def _dataframe_to_csv_buffer(df: pd.DataFrame) -> io.StringIO:
        """
        Convert a DataFrame to an in-memory CSV buffer for COPY.

        Handles None/NaN values by replacing with empty string (PostgreSQL NULL).
        Datetime values are formatted as ISO 8601 strings.

        Args:
            df: DataFrame chunk to convert.

        Returns:
            io.StringIO buffer with CSV content.
        """
        buffer = io.StringIO()
        # Convert to CSV without header; use empty string for NULL representation
        df.to_csv(
            buffer,
            index=False,
            header=False,
            na_rep="",
            date_format="%Y-%m-%d %H:%M:%S%z",
        )
        buffer.seek(0)
        return buffer

    def _log_load_summary(self) -> None:
        """Log a summary of all table loads with row counts and throughput."""
        total_rows = sum(rows for rows, _ in self.load_results.values())
        total_time = sum(elapsed for _, elapsed in self.load_results.values())

        logger.info("=" * 50)
        logger.info("Bulk Load Summary | total_rows=%s | total_time=%.2fs", f"{total_rows:,}", total_time)
        logger.info("=" * 50)
        for table, (rows, elapsed) in self.load_results.items():
            logger.info(
                "  %-15s | %9s rows | %.2fs",
                table,
                f"{rows:,}",
                elapsed,
            )
        logger.info("=" * 50)

    def validate_row_counts(
        self,
        expected_counts: Dict[str, int],
        conn: Optional[psycopg2.extensions.connection] = None,
    ) -> bool:
        """
        Validate that loaded row counts match expected counts.

        Args:
            expected_counts: Dict mapping table names to expected row counts.
            conn: Optional psycopg2 connection. Creates new if None.

        Returns:
            True if all counts match; False otherwise.
        """
        close_conn = conn is None
        if conn is None:
            conn = get_raw_psycopg2_connection()

        all_valid = True
        try:
            with conn.cursor() as cursor:
                for table, expected in expected_counts.items():
                    cursor.execute(f"SELECT COUNT(*) FROM {table};")
                    actual = cursor.fetchone()[0]
                    if actual != expected:
                        logger.error(
                            "Row count mismatch | table=%s | expected=%s | actual=%s",
                            table,
                            f"{expected:,}",
                            f"{actual:,}",
                        )
                        all_valid = False
                    else:
                        logger.debug("Row count OK | table=%s | count=%s", table, f"{actual:,}")
        finally:
            if close_conn:
                conn.close()

        return all_valid
