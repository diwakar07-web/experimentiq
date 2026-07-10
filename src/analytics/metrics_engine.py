"""
metrics_engine.py
=================
Computes all business metrics from the analytical DataFrames built by
DatasetBuilder.  This is where all metric calculation logic lives.

Design constraints:
- NO SQL queries here.  Consume DataFrames only.
- NO statistical inference (p-values, CIs, power) here; that belongs in
  src/statistics/.
- All calculations are deterministic arithmetic operations on DataFrames.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Label constants – must match values in the database
CONTROL_LABEL = "control"
VARIANT_LABEL = "variant"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExperimentMetrics:
    """
    Immutable snapshot of all computed business metrics for one experiment.

    Attributes:
        experiment_name:            Human-readable name of the experiment.
        control_users:              Number of users assigned to control.
        variant_users:              Number of users assigned to variant.
        control_conversion_rate:    Conversion rate for control (0–1 range).
        variant_conversion_rate:    Conversion rate for variant (0–1 range).
        absolute_lift:              variant_rate − control_rate.
        relative_lift:              absolute_lift / control_rate (×100 = %).
        control_revenue_per_visitor: Total revenue / control users.
        variant_revenue_per_visitor: Total revenue / variant users.
        control_aov:                Average order value for control.
        variant_aov:                Average order value for variant.
        control_bounce_rate:        Bounce rate for control (0–1).
        variant_bounce_rate:        Bounce rate for variant (0–1).
        computed_at:                UTC timestamp of when this object was built.
    """

    experiment_name: str
    control_users: int
    variant_users: int
    control_conversion_rate: float
    variant_conversion_rate: float
    absolute_lift: float
    relative_lift: float
    control_revenue_per_visitor: float
    variant_revenue_per_visitor: float
    control_aov: float
    variant_aov: float
    control_bounce_rate: float
    variant_bounce_rate: float
    computed_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class MetricsEngine:
    """
    Computes business metrics from analytical DataFrames.

    The engine expects DataFrames produced by :class:`src.analytics.DatasetBuilder`.
    It does NOT issue SQL queries or perform statistical inference.

    Attributes:
        experiment_summary: DataFrame from ``build_experiment_summary()``.
        revenue_summary:    DataFrame from ``build_revenue_summary()``.

    Example::

        engine = MetricsEngine(experiment_summary=df_exp, revenue_summary=df_rev)
        primary   = engine.compute_primary_metric()
        secondary = engine.compute_secondary_metrics()
        metrics   = engine.compute_all_metrics(session_df=df_sess, funnel_df=df_funnel)
    """

    def __init__(
        self,
        experiment_summary: pd.DataFrame,
        revenue_summary: pd.DataFrame,
    ) -> None:
        """
        Initialise MetricsEngine with the two core DataFrames.

        Args:
            experiment_summary: Aggregated experiment-level data from
                                ``v_experiment_summary``.
            revenue_summary:    Revenue aggregates from ``v_revenue_summary``.

        Raises:
            ValueError: If either DataFrame is None or completely empty.
        """
        if experiment_summary is None or experiment_summary.empty:
            raise ValueError("experiment_summary DataFrame must not be None or empty.")
        if revenue_summary is None or revenue_summary.empty:
            raise ValueError("revenue_summary DataFrame must not be None or empty.")

        self.experiment_summary = experiment_summary.copy()
        self.revenue_summary = revenue_summary.copy()

        self._experiment_name: str = self._resolve_experiment_name()
        logger.info(
            "MetricsEngine initialised for experiment: '%s'", self._experiment_name
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_experiment_name(self) -> str:
        """Return the experiment name from the summary DataFrame, or 'Unknown'."""
        if "experiment_name" in self.experiment_summary.columns:
            names = self.experiment_summary["experiment_name"].dropna().unique()
            if len(names) == 1:
                return str(names[0])
            if len(names) > 1:
                logger.warning(
                    "Multiple experiment names found in summary: %s. Using first.",
                    names.tolist(),
                )
                return str(names[0])
        return "Unknown"

    def _get_variant_row(
        self, df: pd.DataFrame, label: str
    ) -> Optional[pd.Series]:
        """
        Return the single row matching *label* in the ``variant_label`` column.

        Args:
            df:    DataFrame to search.
            label: Label to look for (e.g. ``"control"`` or ``"variant"``).

        Returns:
            The matching row as a Series, or *None* if not found / ambiguous.
        """
        if "variant_label" not in df.columns:
            logger.error("DataFrame missing 'variant_label' column.")
            return None
        mask = df["variant_label"].str.lower() == label.lower()
        matches = df[mask]
        if matches.empty:
            logger.warning("No rows found for variant_label='%s'.", label)
            return None
        if len(matches) > 1:
            logger.warning(
                "%d rows found for variant_label='%s'; using first.",
                len(matches), label,
            )
        return matches.iloc[0]

    @staticmethod
    def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
        """Return numerator / denominator, or *default* when denominator is zero."""
        if denominator == 0:
            return default
        return numerator / denominator

    # ------------------------------------------------------------------
    # Public metric methods
    # ------------------------------------------------------------------

    def compute_primary_metric(self) -> dict:
        """
        Compute conversion rate metrics for control and variant.

        Reads ``users`` and ``conversions`` from the experiment_summary
        DataFrame and derives:

        * ``control_rate``    = control_conversions / control_users
        * ``variant_rate``    = variant_conversions / variant_users
        * ``absolute_lift``   = variant_rate − control_rate
        * ``relative_lift``   = absolute_lift / control_rate (×100 gives %)

        Returns:
            Dictionary with keys:
            control_users, variant_users, control_conversions,
            variant_conversions, control_rate, variant_rate,
            absolute_lift, relative_lift_pct.

        Raises:
            ValueError: If required rows/columns are missing.
        """
        logger.info("Computing primary conversion metric.")

        ctrl = self._get_variant_row(self.experiment_summary, CONTROL_LABEL)
        vari = self._get_variant_row(self.experiment_summary, VARIANT_LABEL)

        if ctrl is None or vari is None:
            raise ValueError(
                "Cannot compute primary metric: missing control or variant row in "
                "experiment_summary DataFrame."
            )

        for col in ("users", "conversions"):
            if col not in self.experiment_summary.columns:
                raise ValueError(
                    f"Column '{col}' missing from experiment_summary DataFrame."
                )

        ctrl_users = int(ctrl["users"])
        ctrl_conv = int(ctrl["conversions"])
        vari_users = int(vari["users"])
        vari_conv = int(vari["conversions"])

        ctrl_rate = self._safe_divide(ctrl_conv, ctrl_users)
        vari_rate = self._safe_divide(vari_conv, vari_users)
        abs_lift = vari_rate - ctrl_rate
        rel_lift_pct = self._safe_divide(abs_lift, ctrl_rate) * 100

        result = {
            "control_users": ctrl_users,
            "variant_users": vari_users,
            "control_conversions": ctrl_conv,
            "variant_conversions": vari_conv,
            "control_rate": ctrl_rate,
            "variant_rate": vari_rate,
            "absolute_lift": abs_lift,
            "relative_lift_pct": rel_lift_pct,
        }
        logger.info(
            "Primary metric: control_rate=%.4f variant_rate=%.4f "
            "abs_lift=%.4f rel_lift=%.2f%%",
            ctrl_rate, vari_rate, abs_lift, rel_lift_pct,
        )
        return result

    def compute_secondary_metrics(
        self, session_df: Optional[pd.DataFrame] = None
    ) -> dict:
        """
        Compute secondary business metrics: RPV, AOV, and session duration.

        Revenue per visitor (RPV) and average order value (AOV) are derived
        from the revenue_summary DataFrame.  Session duration is taken from
        *session_df* when supplied.

        Args:
            session_df: Optional DataFrame from ``build_session_metrics()``.
                        When provided, ``avg_session_duration_seconds`` is
                        included in the output.

        Returns:
            Dictionary with keys:
            control_rpv, variant_rpv, control_aov, variant_aov,
            and (optionally) control_avg_session_seconds,
            variant_avg_session_seconds.
        """
        logger.info("Computing secondary metrics (RPV, AOV, session duration).")

        ctrl_rev = self._get_variant_row(self.revenue_summary, CONTROL_LABEL)
        vari_rev = self._get_variant_row(self.revenue_summary, VARIANT_LABEL)

        def _safe_get(row: Optional[pd.Series], col: str, default: float = 0.0) -> float:
            if row is None or col not in row.index:
                return default
            val = row[col]
            return float(val) if pd.notna(val) else default

        result: dict = {
            "control_rpv": _safe_get(ctrl_rev, "revenue_per_visitor"),
            "variant_rpv": _safe_get(vari_rev, "revenue_per_visitor"),
            "control_aov": _safe_get(ctrl_rev, "average_order_value"),
            "variant_aov": _safe_get(vari_rev, "average_order_value"),
        }

        if session_df is not None and not session_df.empty:
            ctrl_sess = self._get_variant_row(session_df, CONTROL_LABEL)
            vari_sess = self._get_variant_row(session_df, VARIANT_LABEL)
            result["control_avg_session_seconds"] = _safe_get(
                ctrl_sess, "avg_session_duration_seconds"
            )
            result["variant_avg_session_seconds"] = _safe_get(
                vari_sess, "avg_session_duration_seconds"
            )
            logger.debug(
                "Session duration — control: %.1fs  variant: %.1fs",
                result["control_avg_session_seconds"],
                result["variant_avg_session_seconds"],
            )

        logger.info(
            "Secondary metrics: ctrl_rpv=%.4f var_rpv=%.4f ctrl_aov=%.4f var_aov=%.4f",
            result["control_rpv"], result["variant_rpv"],
            result["control_aov"], result["variant_aov"],
        )
        return result

    def compute_guardrail_metrics(self, session_df: pd.DataFrame) -> dict:
        """
        Compute guardrail metrics: bounce rate and checkout abandonment.

        Guardrail metrics detect regressions in user experience caused by
        the variant.  A significant increase in bounce rate or checkout
        abandonment would invalidate a positive conversion lift.

        Args:
            session_df: DataFrame from ``build_session_metrics()`` containing
                        ``bounce_rate`` and ``checkout_abandonment_rate``.

        Returns:
            Dictionary with keys:
            control_bounce_rate, variant_bounce_rate,
            bounce_rate_lift (variant − control),
            control_checkout_abandonment, variant_checkout_abandonment,
            checkout_abandonment_lift.

        Raises:
            ValueError: If session_df is None or empty.
        """
        if session_df is None or session_df.empty:
            raise ValueError(
                "session_df must be a non-empty DataFrame to compute guardrail metrics."
            )

        logger.info("Computing guardrail metrics (bounce rate, checkout abandonment).")

        ctrl_s = self._get_variant_row(session_df, CONTROL_LABEL)
        vari_s = self._get_variant_row(session_df, VARIANT_LABEL)

        def _safe_get(row: Optional[pd.Series], col: str) -> float:
            if row is None or col not in row.index:
                logger.warning("Column '%s' not found in session_df row.", col)
                return 0.0
            val = row[col]
            return float(val) if pd.notna(val) else 0.0

        ctrl_bounce = _safe_get(ctrl_s, "bounce_rate")
        vari_bounce = _safe_get(vari_s, "bounce_rate")
        ctrl_abandon = _safe_get(ctrl_s, "checkout_abandonment_rate")
        vari_abandon = _safe_get(vari_s, "checkout_abandonment_rate")

        result = {
            "control_bounce_rate": ctrl_bounce,
            "variant_bounce_rate": vari_bounce,
            "bounce_rate_lift": vari_bounce - ctrl_bounce,
            "control_checkout_abandonment": ctrl_abandon,
            "variant_checkout_abandonment": vari_abandon,
            "checkout_abandonment_lift": vari_abandon - ctrl_abandon,
        }

        logger.info(
            "Guardrail metrics: bounce ctrl=%.4f var=%.4f | "
            "abandonment ctrl=%.4f var=%.4f",
            ctrl_bounce, vari_bounce, ctrl_abandon, vari_abandon,
        )
        return result

    def compute_all_metrics(
        self,
        session_df: pd.DataFrame,
        funnel_df: Optional[pd.DataFrame] = None,
    ) -> ExperimentMetrics:
        """
        Compute the full suite of business metrics and return as an immutable
        :class:`ExperimentMetrics` dataclass.

        Args:
            session_df: DataFrame from ``build_session_metrics()``.  Required
                        for guardrail metrics.
            funnel_df:  DataFrame from ``build_funnel_data()``.  Currently
                        reserved for future expansion; not used in metric
                        computation directly.

        Returns:
            An :class:`ExperimentMetrics` instance populated with all
            computed values.

        Raises:
            ValueError: If required DataFrames are missing or malformed.
        """
        logger.info(
            "MetricsEngine.compute_all_metrics() started for '%s'.",
            self._experiment_name,
        )

        primary = self.compute_primary_metric()
        secondary = self.compute_secondary_metrics(session_df=session_df)
        guardrail = self.compute_guardrail_metrics(session_df=session_df)

        metrics = ExperimentMetrics(
            experiment_name=self._experiment_name,
            control_users=primary["control_users"],
            variant_users=primary["variant_users"],
            control_conversion_rate=primary["control_rate"],
            variant_conversion_rate=primary["variant_rate"],
            absolute_lift=primary["absolute_lift"],
            relative_lift=primary["relative_lift_pct"],
            control_revenue_per_visitor=secondary["control_rpv"],
            variant_revenue_per_visitor=secondary["variant_rpv"],
            control_aov=secondary["control_aov"],
            variant_aov=secondary["variant_aov"],
            control_bounce_rate=guardrail["control_bounce_rate"],
            variant_bounce_rate=guardrail["variant_bounce_rate"],
            computed_at=datetime.utcnow(),
        )

        logger.info(
            "ExperimentMetrics computed: abs_lift=%.4f rel_lift=%.2f%% "
            "ctrl_users=%d var_users=%d",
            metrics.absolute_lift,
            metrics.relative_lift,
            metrics.control_users,
            metrics.variant_users,
        )
        return metrics
