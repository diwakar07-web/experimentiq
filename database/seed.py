"""
ExperimentIQ — Database Schema Initialization Runner

Purpose:
    Initialises the PostgreSQL database by executing all SQL files in the
    correct dependency order. This script is idempotent — it can be run
    multiple times without causing errors (uses IF NOT EXISTS, ON CONFLICT).

    Execution order:
        1. schema.sql     — table definitions and seed data
        2. constraints.sql — foreign keys and check constraints
        3. indexes.sql    — performance indexes
        4. views.sql      — views and materialized views

    This script also validates that all expected tables exist after migration.

Dependencies:
    - psycopg2-binary
    - config.settings (DatabaseSettings)
    - config.logging_config (configure_logging_from_settings)

Usage:
    python database/seed.py
    python database/seed.py --force-drop   # WARNING: drops and recreates everything

Inputs:
    Database connection from settings. SQL files in this directory.

Outputs:
    Fully initialised PostgreSQL schema ready for data ingestion.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Tuple

import psycopg2
import psycopg2.extras
from psycopg2 import sql

# ---------------------------------------------------------------------------
# Bootstrap: add project root to sys.path so config is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.logging_config import configure_logging_from_settings
from config.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATABASE_DIR = Path(__file__).parent.resolve()

# SQL files in strict execution order
SQL_FILES: List[Tuple[str, str]] = [
    ("schema.sql",      "Table definitions and seed data"),
    ("constraints.sql", "Foreign key and check constraints"),
    ("indexes.sql",     "Performance indexes"),
    ("views.sql",       "Analytical views and materialized views"),
]

# Tables that must exist after successful schema initialisation
EXPECTED_TABLES: List[str] = [
    "regions",
    "countries",
    "devices",
    "browsers",
    "acquisition_channels",
    "event_types",
    "users",
    "experiments",
    "sessions",
    "events",
    "orders",
]

# Views that must exist after successful schema initialisation
EXPECTED_VIEWS: List[str] = [
    "v_experiment_summary",
    "v_daily_metrics",
    "v_funnel_steps",
    "v_session_metrics",
    "v_segment_conversion",
    "v_revenue_summary",
]

EXPECTED_MATERIALIZED_VIEWS: List[str] = [
    "mv_user_experiment_summary",
    "mv_daily_conversion",
]


# ---------------------------------------------------------------------------
# Database Utilities
# ---------------------------------------------------------------------------


def get_connection(settings: "DatabaseSettings") -> psycopg2.extensions.connection:
    """
    Create and return a psycopg2 database connection.

    Args:
        settings: DatabaseSettings instance with connection parameters.

    Returns:
        psycopg2 connection object.

    Raises:
        psycopg2.OperationalError: If the database is unreachable.
    """
    logger.debug(
        "Connecting to PostgreSQL | host=%s port=%s db=%s user=%s",
        settings.host,
        settings.port,
        settings.name,
        settings.user,
    )
    conn = psycopg2.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.name,
        user=settings.user,
        password=settings.password,
        connect_timeout=30,
    )
    conn.autocommit = False
    return conn


def execute_sql_file(
    conn: psycopg2.extensions.connection,
    file_path: Path,
    description: str,
) -> None:
    """
    Execute a SQL file against an open database connection.

    The entire file is executed within a single transaction. If any
    statement fails, the transaction is rolled back and the error is re-raised.

    Args:
        conn: Open psycopg2 connection (autocommit must be False).
        file_path: Absolute path to the SQL file.
        description: Human-readable description for logging.

    Raises:
        FileNotFoundError: If the SQL file does not exist.
        psycopg2.Error: If any SQL statement fails.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    sql_content = file_path.read_text(encoding="utf-8")
    logger.info("Executing %s | file=%s", description, file_path.name)

    start = time.perf_counter()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_content)
        conn.commit()
        elapsed = time.perf_counter() - start
        logger.info("Completed %s | duration=%.2fs", description, elapsed)
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Failed executing %s | error=%s | file=%s",
            description,
            exc.pgcode,
            file_path.name,
        )
        raise


def drop_all_objects(conn: psycopg2.extensions.connection) -> None:
    """
    Drop all ExperimentIQ objects from the database.

    WARNING: Destructive operation. Drops tables, views, and extensions
    in reverse dependency order. Used only with --force-drop flag.

    Args:
        conn: Open psycopg2 connection.
    """
    logger.warning("Dropping all ExperimentIQ database objects (force-drop mode)")
    drop_sql = """
        DROP MATERIALIZED VIEW IF EXISTS mv_daily_conversion CASCADE;
        DROP MATERIALIZED VIEW IF EXISTS mv_user_experiment_summary CASCADE;
        DROP VIEW IF EXISTS v_revenue_summary CASCADE;
        DROP VIEW IF EXISTS v_segment_conversion CASCADE;
        DROP VIEW IF EXISTS v_session_metrics CASCADE;
        DROP VIEW IF EXISTS v_funnel_steps CASCADE;
        DROP VIEW IF EXISTS v_daily_metrics CASCADE;
        DROP VIEW IF EXISTS v_experiment_summary CASCADE;
        DROP TABLE IF EXISTS orders CASCADE;
        DROP TABLE IF EXISTS events CASCADE;
        DROP TABLE IF EXISTS sessions CASCADE;
        DROP TABLE IF EXISTS experiments CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        DROP TABLE IF EXISTS event_types CASCADE;
        DROP TABLE IF EXISTS acquisition_channels CASCADE;
        DROP TABLE IF EXISTS browsers CASCADE;
        DROP TABLE IF EXISTS devices CASCADE;
        DROP TABLE IF EXISTS countries CASCADE;
        DROP TABLE IF EXISTS regions CASCADE;
        DROP FUNCTION IF EXISTS refresh_all_materialized_views() CASCADE;
    """
    with conn.cursor() as cursor:
        cursor.execute(drop_sql)
    conn.commit()
    logger.info("All database objects dropped successfully")


def validate_schema(conn: psycopg2.extensions.connection) -> bool:
    """
    Validate that all expected database objects exist after initialisation.

    Checks for:
    - All expected tables in pg_tables
    - All expected views in pg_views
    - All expected materialized views in pg_matviews

    Args:
        conn: Open psycopg2 connection.

    Returns:
        True if all expected objects exist; False otherwise.
    """
    logger.info("Validating database schema completeness")
    all_valid = True

    with conn.cursor() as cursor:
        # Check tables
        cursor.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            """
        )
        existing_tables = {row[0] for row in cursor.fetchall()}
        for table in EXPECTED_TABLES:
            if table not in existing_tables:
                logger.error("Missing table: %s", table)
                all_valid = False
            else:
                logger.debug("Table OK: %s", table)

        # Check views
        cursor.execute(
            """
            SELECT viewname FROM pg_views
            WHERE schemaname = 'public'
            """
        )
        existing_views = {row[0] for row in cursor.fetchall()}
        for view in EXPECTED_VIEWS:
            if view not in existing_views:
                logger.error("Missing view: %s", view)
                all_valid = False
            else:
                logger.debug("View OK: %s", view)

        # Check materialized views
        cursor.execute(
            """
            SELECT matviewname FROM pg_matviews
            WHERE schemaname = 'public'
            """
        )
        existing_matviews = {row[0] for row in cursor.fetchall()}
        for mv in EXPECTED_MATERIALIZED_VIEWS:
            if mv not in existing_matviews:
                logger.error("Missing materialized view: %s", mv)
                all_valid = False
            else:
                logger.debug("Materialized view OK: %s", mv)

    return all_valid


def log_table_counts(conn: psycopg2.extensions.connection) -> None:
    """
    Log row counts for all core tables and lookup tables.

    Args:
        conn: Open psycopg2 connection.
    """
    tables_to_count = EXPECTED_TABLES
    with conn.cursor() as cursor:
        for table in tables_to_count:
            cursor.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
            )
            count = cursor.fetchone()[0]
            logger.info("Table %s | rows=%s", table, f"{count:,}")


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main(force_drop: bool = False) -> int:
    """
    Execute the complete database initialisation workflow.

    Args:
        force_drop: If True, drop all existing objects before recreating.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    configure_logging_from_settings()
    settings = get_settings()

    logger.info("=" * 60)
    logger.info("ExperimentIQ Database Initialisation")
    logger.info("Target: %s@%s:%s/%s", settings.database.user, settings.database.host,
                settings.database.port, settings.database.name)
    logger.info("=" * 60)

    pipeline_start = time.perf_counter()

    try:
        conn = get_connection(settings.database)
    except psycopg2.OperationalError as exc:
        logger.critical(
            "Cannot connect to PostgreSQL. Is the database running? Error: %s", exc
        )
        logger.info("TIP: Start the database with: docker compose up -d")
        return 1

    try:
        if force_drop:
            drop_all_objects(conn)

        # Execute SQL files in dependency order
        for filename, description in SQL_FILES:
            file_path = DATABASE_DIR / filename
            execute_sql_file(conn, file_path, description)

        # Validate schema completeness
        if not validate_schema(conn):
            logger.error("Schema validation FAILED — some objects are missing")
            return 1

        logger.info("Schema validation PASSED — all objects exist")

        # Log seed data counts
        log_table_counts(conn)

        total_elapsed = time.perf_counter() - pipeline_start
        logger.info("=" * 60)
        logger.info(
            "Database initialisation COMPLETE | total_duration=%.2fs", total_elapsed
        )
        logger.info("=" * 60)
        return 0

    except (psycopg2.Error, FileNotFoundError) as exc:
        logger.critical("Database initialisation FAILED: %s", exc)
        return 1

    finally:
        if conn and not conn.closed:
            conn.close()
            logger.debug("Database connection closed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialise the ExperimentIQ PostgreSQL database schema."
    )
    parser.add_argument(
        "--force-drop",
        action="store_true",
        default=False,
        help="Drop all existing objects before recreating. WARNING: Destructive.",
    )
    args = parser.parse_args()
    sys.exit(main(force_drop=args.force_drop))
