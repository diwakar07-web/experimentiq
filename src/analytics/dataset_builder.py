"""
dataset_builder.py
==================
Reads analytical data from PostgreSQL views and assembles typed pandas DataFrames
for use by the statistics and reporting engines.

This is the ONLY module allowed to query the database for analytics purposes.
All other modules must consume DataFrames produced here.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _get_engine() -> Engine:
    """Lazy import to avoid circular dependencies at module load time."""
    from src.utils.db import get_engine  # type: ignore[import]
    return get_engine()


# ---------------------------------------------------------------------------
# Column dtype specifications for each view
# ---------------------------------------------------------------------------

_EXPERIMENT_SUMMARY_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "experiment_name": "object",
    "variant_label": "object",
    "users": "int64",
    "conversions": "int64",
    "conversion_rate": "float64",
    "total_revenue": "float64",
    "revenue_per_visitor": "float64",
    "average_order_value": "float64",
    "orders": "int64",
}

_DAILY_METRICS_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "variant_label": "object",
    "event_date": "object",
    "daily_users": "int64",
    "daily_conversions": "int64",
    "daily_revenue": "float64",
    "daily_conversion_rate": "float64",
}

_FUNNEL_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "variant_label": "object",
    "step_name": "object",
    "step_order": "int64",
    "users_reached": "int64",
    "step_rate": "float64",
    "cumulative_rate": "float64",
}

_SESSION_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "variant_label": "object",
    "avg_session_duration_seconds": "float64",
    "bounce_rate": "float64",
    "checkout_abandonment_rate": "float64",
    "pages_per_session": "float64",
}

_SEGMENT_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "variant_label": "object",
    "device_type": "object",
    "country": "object",
    "acquisition_channel": "object",
    "customer_type": "object",
    "users": "int64",
    "conversions": "int64",
    "conversion_rate": "float64",
}

_REVENUE_SUMMARY_DTYPES: dict[str, str] = {
    "experiment_id": "int64",
    "variant_label": "object",
    "total_revenue": "float64",
    "orders": "int64",
    "revenue_per_visitor": "float64",
    "average_order_value": "float64",
    "users": "int64",
}

_USER_LEVEL_DTYPES: dict[str, str] = {
    "user_id": "object",
    "experiment_id": "int64",
    "variant_label": "object",
    "converted": "int64",
    "total_revenue": "float64",
    "session_count": "int64",
    "total_session_duration_seconds": "float64",
}


def _apply_dtypes(df: pd.DataFrame, dtype_map: dict[str, str]) -> pd.DataFrame:
    """
    Apply a dtype mapping to a DataFrame, coercing columns that exist.

    Columns present in dtype_map but absent from df are silently skipped.
    Columns in df but not in dtype_map are left as-is.

    Args:
        df: Source DataFrame.
        dtype_map: Mapping of column name → dtype string.

    Returns:
        DataFrame with corrected dtypes.
    """
    for col, dtype in dtype_map.items():
        if col in df.columns:
            try:
                df[col] = df[col].astype(dtype)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Could not cast column '%s' to %s: %s. Leaving as-is.",
                    col, dtype, exc,
                )
    return df


class DatasetBuilder:
    """
    Assembles typed pandas DataFrames from PostgreSQL analytical views.

    This class is the single authorised entry-point for all database reads
    performed by the analytics pipeline.  Downstream modules (metrics engine,
    funnel analyser, report generator, etc.) must NOT issue SQL queries
    directly; they must consume DataFrames produced by this class.

    Attributes:
        engine: SQLAlchemy engine used to connect to PostgreSQL.

    Example::

        builder = DatasetBuilder()
        summary = builder.build_experiment_summary()
        daily   = builder.build_daily_metrics()
        all_df  = builder.build_all()
    """

    def __init__(self, engine: Optional[Engine] = None) -> None:
        """
        Initialise the DatasetBuilder.

        Args:
            engine: Optional SQLAlchemy engine.  When *None* the engine
                    returned by :func:`src.utils.db.get_engine` is used.
        """
        self.engine: Engine = engine if engine is not None else _get_engine()
        logger.debug("DatasetBuilder initialised with engine: %s", self.engine)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_view(
        self,
        view_name: str,
        dtype_map: dict[str, str],
        *,
        extra_sql: str = "",
    ) -> pd.DataFrame:
        """
        Execute a SELECT * against a view and return a typed DataFrame.

        Args:
            view_name: PostgreSQL view or materialised view name.
            dtype_map: Column→dtype mapping applied after loading.
            extra_sql: Optional SQL clause appended after the FROM clause
                       (e.g. ``TABLESAMPLE SYSTEM (10)``).

        Returns:
            Typed DataFrame; empty DataFrame if the view returns no rows.

        Raises:
            RuntimeError: If the query fails for any reason other than an
                          empty result set.
        """
        sql = f"SELECT * FROM {view_name}{(' ' + extra_sql) if extra_sql else ''}"
        logger.info("DatasetBuilder executing query: %s", sql)
        try:
            df = pd.read_sql(sql=sql, con=self.engine)
        except Exception as exc:
            logger.error(
                "Failed to read view '%s': %s", view_name, exc, exc_info=True
            )
            raise RuntimeError(
                f"DatasetBuilder could not read view '{view_name}'"
            ) from exc

        if df.empty:
            logger.warning("View '%s' returned 0 rows.", view_name)
            return df

        df = _apply_dtypes(df, dtype_map)
        logger.info("View '%s' returned %d rows.", view_name, len(df))
        return df

    # ------------------------------------------------------------------
    # Public build methods
    # ------------------------------------------------------------------

    def build_experiment_summary(self) -> pd.DataFrame:
        """
        Load the experiment summary view.

        View: ``v_experiment_summary``

        The view returns one row per (experiment, variant) with aggregate
        conversion and revenue metrics.

        Returns:
            DataFrame with columns:
            experiment_id, experiment_name, variant_label, users, conversions,
            conversion_rate, total_revenue, revenue_per_visitor,
            average_order_value, orders.

        Raises:
            RuntimeError: On query failure.
        """
        return self._read_view("v_experiment_summary", _EXPERIMENT_SUMMARY_DTYPES)

    def build_daily_metrics(self) -> pd.DataFrame:
        """
        Load the daily conversion materialised view.

        View: ``mv_daily_conversion``

        Returns one row per (experiment, variant, date) capturing the
        day-level traffic, conversions, and revenue aggregates.

        Returns:
            DataFrame with columns:
            experiment_id, variant_label, event_date (str→parse later),
            daily_users, daily_conversions, daily_revenue,
            daily_conversion_rate.

        Raises:
            RuntimeError: On query failure.
        """
        df = self._read_view("mv_daily_conversion", _DAILY_METRICS_DTYPES)
        if not df.empty and "event_date" in df.columns:
            df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
            logger.debug("Parsed 'event_date' to datetime.")
        return df

    def build_funnel_data(self) -> pd.DataFrame:
        """
        Load the funnel steps view.

        View: ``v_funnel_steps``

        Returns one row per (experiment, variant, funnel step) capturing
        users who reached each step, the step-to-step rate, and the
        cumulative rate from the top of the funnel.

        Returns:
            DataFrame with columns:
            experiment_id, variant_label, step_name, step_order,
            users_reached, step_rate, cumulative_rate.

        Raises:
            RuntimeError: On query failure.
        """
        df = self._read_view("v_funnel_steps", _FUNNEL_DTYPES)
        if not df.empty and "step_order" in df.columns:
            df = df.sort_values(["experiment_id", "variant_label", "step_order"])
            logger.debug("Sorted funnel data by step_order.")
        return df

    def build_session_metrics(self) -> pd.DataFrame:
        """
        Load the session metrics view.

        View: ``v_session_metrics``

        Returns aggregate session-level behavioural metrics per
        (experiment, variant): average session duration, bounce rate,
        checkout abandonment rate, and pages per session.

        Returns:
            DataFrame with columns:
            experiment_id, variant_label, avg_session_duration_seconds,
            bounce_rate, checkout_abandonment_rate, pages_per_session.

        Raises:
            RuntimeError: On query failure.
        """
        return self._read_view("v_session_metrics", _SESSION_DTYPES)

    def build_segment_data(self) -> pd.DataFrame:
        """
        Load the segment conversion view.

        View: ``v_segment_conversion``

        Returns one row per (experiment, variant, device, country, channel,
        customer_type) with user and conversion counts.

        Returns:
            DataFrame with columns:
            experiment_id, variant_label, device_type, country,
            acquisition_channel, customer_type, users, conversions,
            conversion_rate.

        Raises:
            RuntimeError: On query failure.
        """
        return self._read_view("v_segment_conversion", _SEGMENT_DTYPES)

    def build_revenue_summary(self) -> pd.DataFrame:
        """
        Load the revenue summary view.

        View: ``v_revenue_summary``

        Returns aggregate revenue metrics per (experiment, variant):
        total revenue, order count, revenue per visitor, and AOV.

        Returns:
            DataFrame with columns:
            experiment_id, variant_label, total_revenue, orders,
            revenue_per_visitor, average_order_value, users.

        Raises:
            RuntimeError: On query failure.
        """
        return self._read_view("v_revenue_summary", _REVENUE_SUMMARY_DTYPES)

    def build_user_level_data(self, sample_frac: float = 1.0) -> pd.DataFrame:
        """
        Load user-level experiment summary data with optional sampling.

        View: ``mv_user_experiment_summary``

        Returns one row per user with their variant assignment, conversion
        flag, revenue, session count, and total session duration.

        Args:
            sample_frac: Fraction of rows to return (0 < sample_frac ≤ 1.0).
                         Sampling is performed via PostgreSQL's
                         ``TABLESAMPLE SYSTEM`` clause which operates at the
                         block level and is approximate.  Defaults to 1.0
                         (no sampling).

        Returns:
            DataFrame with columns:
            user_id, experiment_id, variant_label, converted, total_revenue,
            session_count, total_session_duration_seconds.

        Raises:
            ValueError: If sample_frac is not in (0, 1].
            RuntimeError: On query failure.
        """
        if not (0 < sample_frac <= 1.0):
            raise ValueError(
                f"sample_frac must be in (0, 1], got {sample_frac!r}"
            )

        extra_sql = ""
        if sample_frac < 1.0:
            pct = round(sample_frac * 100, 6)
            extra_sql = f"TABLESAMPLE SYSTEM ({pct})"
            logger.info(
                "build_user_level_data: sampling %s%% of mv_user_experiment_summary",
                pct,
            )

        return self._read_view(
            "mv_user_experiment_summary",
            _USER_LEVEL_DTYPES,
            extra_sql=extra_sql,
        )

    def build_all(self) -> dict[str, pd.DataFrame]:
        """
        Build all available analytical DataFrames in a single call.

        Calls every ``build_*`` method and aggregates the results into a
        dictionary keyed by a canonical name.  Each individual method is
        called with its default arguments; use individual build methods
        directly when non-default arguments are required.

        Returns:
            Dictionary mapping dataset name → DataFrame:

            * ``"experiment_summary"``
            * ``"daily_metrics"``
            * ``"funnel_data"``
            * ``"session_metrics"``
            * ``"segment_data"``
            * ``"revenue_summary"``
            * ``"user_level_data"``

        Raises:
            RuntimeError: If any individual build method fails.
        """
        logger.info("DatasetBuilder.build_all() started.")
        datasets: dict[str, pd.DataFrame] = {}

        build_steps = [
            ("experiment_summary", self.build_experiment_summary),
            ("daily_metrics", self.build_daily_metrics),
            ("funnel_data", self.build_funnel_data),
            ("session_metrics", self.build_session_metrics),
            ("segment_data", self.build_segment_data),
            ("revenue_summary", self.build_revenue_summary),
            ("user_level_data", self.build_user_level_data),
        ]

        for name, builder_fn in build_steps:
            logger.info("Building dataset: %s", name)
            datasets[name] = builder_fn()
            logger.info(
                "Dataset '%s' ready: %d rows, %d columns.",
                name,
                len(datasets[name]),
                datasets[name].shape[1] if not datasets[name].empty else 0,
            )

        logger.info(
            "DatasetBuilder.build_all() complete. Built %d datasets.", len(datasets)
        )
        return datasets
