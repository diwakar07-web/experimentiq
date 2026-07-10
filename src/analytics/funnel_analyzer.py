"""
funnel_analyzer.py
==================
Analyzes funnel performance from the funnel DataFrame produced by
DatasetBuilder.  Produces per-step metrics and drop-off analysis.

No SQL queries and no statistical inference occur here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Label constants
CONTROL_LABEL = "control"
VARIANT_LABEL = "variant"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class FunnelStep:
    """
    Represents a single step in the conversion funnel for one variant.

    Attributes:
        step_name:       Human-readable name of the funnel step.
        step_order:      Integer ordering index (1 = first step).
        users_reached:   Number of users who reached this step.
        step_rate:       Step-to-step conversion rate (users_reached[n] /
                         users_reached[n-1]).  For the first step this is
                         the entry rate relative to total experiment users.
        cumulative_rate: Fraction of the top-of-funnel users who reached
                         this step.
        drop_off_count:  Number of users who did NOT proceed past this step
                         (users_reached[n] − users_reached[n+1]).  Zero for
                         the last step.
    """

    step_name: str
    step_order: int
    users_reached: int
    step_rate: float
    cumulative_rate: float
    drop_off_count: int


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class FunnelAnalyzer:
    """
    Analyzes funnel performance across control and variant groups.

    The class consumes the funnel DataFrame produced by
    :meth:`src.analytics.DatasetBuilder.build_funnel_data`.

    Attributes:
        funnel_df: Raw funnel DataFrame, filtered to a single experiment.

    Example::

        analyzer = FunnelAnalyzer(funnel_df=df_funnel)
        steps = analyzer.get_funnel_steps("variant")
        lift_df = analyzer.compute_funnel_lift()
        report = analyzer.to_report_dict()
    """

    def __init__(self, funnel_df: pd.DataFrame) -> None:
        """
        Initialise FunnelAnalyzer.

        Args:
            funnel_df: DataFrame from ``build_funnel_data()``.  Must contain
                       columns: ``variant_label``, ``step_name``,
                       ``step_order``, ``users_reached``, ``step_rate``,
                       ``cumulative_rate``.

        Raises:
            ValueError: If funnel_df is None or empty.
        """
        if funnel_df is None or funnel_df.empty:
            raise ValueError("funnel_df must be a non-empty DataFrame.")

        self.funnel_df = funnel_df.copy()
        self._validate_columns()
        logger.info(
            "FunnelAnalyzer initialised with %d rows.", len(self.funnel_df)
        )

    def _validate_columns(self) -> None:
        """Raise ValueError if any required column is missing."""
        required = {
            "variant_label", "step_name", "step_order",
            "users_reached", "step_rate", "cumulative_rate",
        }
        missing = required - set(self.funnel_df.columns)
        if missing:
            raise ValueError(
                f"funnel_df is missing required columns: {missing}"
            )

    def _filter_variant(self, variant: str) -> pd.DataFrame:
        """
        Return rows for the given variant label, sorted by step_order.

        Args:
            variant: Variant label string (e.g. ``"control"``).

        Returns:
            Filtered and sorted DataFrame.

        Raises:
            ValueError: If no rows match the label.
        """
        mask = self.funnel_df["variant_label"].str.lower() == variant.lower()
        df = self.funnel_df[mask].sort_values("step_order").reset_index(drop=True)
        if df.empty:
            raise ValueError(
                f"No funnel data found for variant_label='{variant}'."
            )
        return df

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_funnel_steps(self, variant: str) -> list[FunnelStep]:
        """
        Return ordered list of :class:`FunnelStep` objects for a variant.

        Drop-off count for each step is computed as the difference between
        that step's user count and the next step's user count.  The last
        step always has ``drop_off_count = 0``.

        Args:
            variant: Variant label, typically ``"control"`` or ``"variant"``.

        Returns:
            List of :class:`FunnelStep`, ordered from top to bottom of funnel.

        Raises:
            ValueError: If the variant label is not present in the data.
        """
        logger.info("Building funnel steps for variant='%s'.", variant)
        df = self._filter_variant(variant)
        steps: list[FunnelStep] = []

        for idx, row in df.iterrows():
            # Drop-off: difference to next step, or 0 for the last step
            next_users: int
            if idx < len(df) - 1:
                next_users = int(df.loc[idx + 1, "users_reached"])
            else:
                next_users = int(row["users_reached"])
            drop_off = max(int(row["users_reached"]) - next_users, 0)

            step = FunnelStep(
                step_name=str(row["step_name"]),
                step_order=int(row["step_order"]),
                users_reached=int(row["users_reached"]),
                step_rate=float(row["step_rate"]),
                cumulative_rate=float(row["cumulative_rate"]),
                drop_off_count=drop_off,
            )
            steps.append(step)

        logger.debug(
            "get_funnel_steps('%s') returned %d steps.", variant, len(steps)
        )
        return steps

    def compute_funnel_lift(self) -> pd.DataFrame:
        """
        Compute step-by-step lift (variant vs control) for each funnel step.

        Lift is defined as:
        ``cumulative_rate_variant − cumulative_rate_control``

        The result includes absolute lift and relative lift (%) for both
        ``step_rate`` and ``cumulative_rate``.

        Returns:
            DataFrame with columns:
            step_name, step_order,
            control_step_rate, variant_step_rate, step_rate_lift,
            control_cumulative_rate, variant_cumulative_rate,
            cumulative_rate_lift, cumulative_rate_relative_lift_pct.

        Raises:
            ValueError: If control or variant data is not available.
        """
        logger.info("Computing funnel lift (variant vs control).")

        ctrl_df = self._filter_variant(CONTROL_LABEL)[
            ["step_name", "step_order", "step_rate", "cumulative_rate"]
        ].rename(columns={
            "step_rate": "control_step_rate",
            "cumulative_rate": "control_cumulative_rate",
        })

        vari_df = self._filter_variant(VARIANT_LABEL)[
            ["step_name", "step_order", "step_rate", "cumulative_rate"]
        ].rename(columns={
            "step_rate": "variant_step_rate",
            "cumulative_rate": "variant_cumulative_rate",
        })

        merged = pd.merge(ctrl_df, vari_df, on=["step_name", "step_order"], how="outer")
        merged = merged.sort_values("step_order").reset_index(drop=True)

        merged["step_rate_lift"] = (
            merged["variant_step_rate"] - merged["control_step_rate"]
        )
        merged["cumulative_rate_lift"] = (
            merged["variant_cumulative_rate"] - merged["control_cumulative_rate"]
        )
        merged["cumulative_rate_relative_lift_pct"] = (
            merged["cumulative_rate_lift"]
            / merged["control_cumulative_rate"].replace(0, float("nan"))
            * 100
        )

        logger.info(
            "compute_funnel_lift() produced lift DataFrame with %d rows.", len(merged)
        )
        return merged

    def get_biggest_drop_off(self, variant: str) -> FunnelStep:
        """
        Return the funnel step with the highest drop-off count for a variant.

        Among all steps except the last, the step with the greatest absolute
        number of users lost is identified.

        Args:
            variant: Variant label (e.g. ``"control"`` or ``"variant"``).

        Returns:
            :class:`FunnelStep` representing the step with the most drop-off.

        Raises:
            ValueError: If variant data is missing or funnel has only one step.
        """
        logger.info("Finding biggest drop-off for variant='%s'.", variant)
        steps = self.get_funnel_steps(variant)

        if len(steps) < 2:
            raise ValueError(
                f"Funnel for variant='{variant}' has fewer than 2 steps; "
                "drop-off analysis requires at least 2 steps."
            )

        # Exclude the last step (always has drop_off_count = 0)
        candidate_steps = steps[:-1]
        worst = max(candidate_steps, key=lambda s: s.drop_off_count)

        logger.info(
            "Biggest drop-off for '%s': step='%s' (order=%d, drop_off=%d)",
            variant, worst.step_name, worst.step_order, worst.drop_off_count,
        )
        return worst

    def to_report_dict(self) -> dict:
        """
        Produce a structured dictionary suitable for report generation.

        The output is designed to be serialisable (JSON/YAML) and consumed
        directly by the reporting engine without further transformation.

        Returns:
            Dictionary with keys:

            * ``"control_steps"`` – list of dicts from control FunnelSteps
            * ``"variant_steps"`` – list of dicts from variant FunnelSteps
            * ``"funnel_lift"``   – list of dicts from :meth:`compute_funnel_lift`
            * ``"biggest_drop_off_control"`` – dict from worst control step
            * ``"biggest_drop_off_variant"`` – dict from worst variant step
        """
        logger.info("FunnelAnalyzer.to_report_dict() called.")

        def _steps_to_dicts(steps: list[FunnelStep]) -> list[dict]:
            return [
                {
                    "step_name": s.step_name,
                    "step_order": s.step_order,
                    "users_reached": s.users_reached,
                    "step_rate": s.step_rate,
                    "cumulative_rate": s.cumulative_rate,
                    "drop_off_count": s.drop_off_count,
                }
                for s in steps
            ]

        try:
            ctrl_steps = self.get_funnel_steps(CONTROL_LABEL)
        except ValueError as exc:
            logger.warning("Could not build control steps: %s", exc)
            ctrl_steps = []

        try:
            vari_steps = self.get_funnel_steps(VARIANT_LABEL)
        except ValueError as exc:
            logger.warning("Could not build variant steps: %s", exc)
            vari_steps = []

        try:
            lift_df = self.compute_funnel_lift()
            lift_records = lift_df.to_dict(orient="records")
        except ValueError as exc:
            logger.warning("Could not compute funnel lift: %s", exc)
            lift_records = []

        def _step_to_dict(step: Optional[FunnelStep]) -> Optional[dict]:
            if step is None:
                return None
            return {
                "step_name": step.step_name,
                "step_order": step.step_order,
                "users_reached": step.users_reached,
                "step_rate": step.step_rate,
                "cumulative_rate": step.cumulative_rate,
                "drop_off_count": step.drop_off_count,
            }

        try:
            worst_ctrl = _step_to_dict(self.get_biggest_drop_off(CONTROL_LABEL))
        except ValueError:
            worst_ctrl = None

        try:
            worst_vari = _step_to_dict(self.get_biggest_drop_off(VARIANT_LABEL))
        except ValueError:
            worst_vari = None

        return {
            "control_steps": _steps_to_dicts(ctrl_steps),
            "variant_steps": _steps_to_dicts(vari_steps),
            "funnel_lift": lift_records,
            "biggest_drop_off_control": worst_ctrl,
            "biggest_drop_off_variant": worst_vari,
        }
