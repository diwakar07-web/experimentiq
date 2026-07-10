"""
ExperimentIQ — Data Validator
==============================

Purpose:
    Validates generated Pandas DataFrames BEFORE they are loaded into the
    PostgreSQL database. Performs business-logic validation that goes beyond
    simple schema checks: referential integrity between tables, date range
    checks, experiment balance checks, and revenue sanity checks.

Design:
    - Each validate_<table>() method returns a ValidationResult dataclass.
    - validate_all() aggregates results into an OverallValidationResult.
    - Validation failures are collected (not raised) so the caller can see
      all problems in a single pass rather than stopping on the first error.
    - Warnings are issued for non-fatal anomalies (e.g., slightly skewed splits).

Dependencies:
    - pandas >= 2.0
    - numpy >= 1.25

Usage:
    from src.validation.data_validator import DataValidator

    validator = DataValidator()
    result = validator.validate_all({
        "users": users_df,
        "experiments": experiments_df,
        "sessions": sessions_df,
        "events": events_df,
        "orders": orders_df,
    })
    if not result.is_valid:
        raise RuntimeError(result.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid reference values (mirrors database seed data in schema.sql)
# ---------------------------------------------------------------------------

VALID_CUSTOMER_TYPES: frozenset[str] = frozenset({"new", "returning", "high_value"})
VALID_VARIANTS: frozenset[str] = frozenset({"control", "variant"})
VALID_PAYMENT_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "pending", "refunded"}
)
VALID_PAYMENT_METHODS: frozenset[str] = frozenset(
    {
        "credit_card",
        "debit_card",
        "paypal",
        "apple_pay",
        "google_pay",
        "bank_transfer",
    }
)
VALID_EVENT_CATEGORIES: frozenset[str] = frozenset(
    {"navigation", "engagement", "commerce", "error", "system"}
)

# Thresholds
VARIANT_SPLIT_LOWER: float = 0.40   # Warn if variant fraction < 40 %
VARIANT_SPLIT_UPPER: float = 0.60   # Warn if variant fraction > 60 %
VARIANT_SPLIT_ERROR_LOWER: float = 0.30  # Error if variant fraction < 30 %
VARIANT_SPLIT_ERROR_UPPER: float = 0.70  # Error if variant fraction > 70 %
MAX_REASONABLE_SESSION_DURATION_SECONDS: int = 7_200   # 2 hours
MAX_ORDER_VALUE_SANITY: float = 10_000.0  # Flag orders above $10 000
MAX_REALISTIC_REFUND_RATE: float = 0.30   # Warn if > 30 % refunded
CUSTOMER_TYPE_MAX_FRACTION: float = 0.70  # Warn if any type > 70 % of users


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """
    Result of validating a single DataFrame.

    Attributes:
        table_name:     The name of the table / DataFrame that was validated.
        is_valid:       False if any check raised an error; True otherwise.
        checks_passed:  Number of individual checks that passed.
        checks_failed:  Number of individual checks that failed.
        warnings:       Non-fatal anomalies (won't set is_valid = False).
        errors:         Fatal validation failures (set is_valid = False).
    """

    table_name: str
    is_valid: bool = True
    checks_passed: int = 0
    checks_failed: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Internal helpers — not part of the public API
    # ------------------------------------------------------------------

    def _pass(self, check_name: str) -> None:
        """Record a passed check (debug-level logging)."""
        self.checks_passed += 1
        logger.debug("[%s] [PASS] %s", self.table_name, check_name)

    def _warn(self, check_name: str, detail: str) -> None:
        """Record a non-fatal warning."""
        msg = f"{check_name}: {detail}"
        self.warnings.append(msg)
        self.checks_passed += 1  # Still counts as a pass (non-fatal)
        logger.warning("[%s] [WARN] %s", self.table_name, msg)

    def _fail(self, check_name: str, detail: str) -> None:
        """Record a fatal error and mark result as invalid."""
        msg = f"{check_name}: {detail}"
        self.errors.append(msg)
        self.checks_failed += 1
        self.is_valid = False
        logger.error("[%s] [FAIL] %s", self.table_name, msg)

    def summary(self) -> str:
        """Return a human-readable summary string."""
        status = "VALID" if self.is_valid else "INVALID"
        lines = [
            f"[{self.table_name}] {status} — "
            f"{self.checks_passed} passed, {self.checks_failed} failed, "
            f"{len(self.warnings)} warnings"
        ]
        for err in self.errors:
            lines.append(f"  ERROR   : {err}")
        for warn in self.warnings:
            lines.append(f"  WARNING : {warn}")
        return "\n".join(lines)


@dataclass
class OverallValidationResult:
    """
    Aggregated result of validating all tables in the pipeline.

    Attributes:
        is_valid:           True only if ALL individual results are valid.
        table_results:      Mapping of table_name → ValidationResult.
        total_checks_passed: Sum of all passed checks.
        total_checks_failed: Sum of all failed checks.
        total_warnings:     Total warning count across all tables.
        total_errors:       Total error count across all tables.
    """

    is_valid: bool = True
    table_results: dict[str, ValidationResult] = field(default_factory=dict)
    total_checks_passed: int = 0
    total_checks_failed: int = 0
    total_warnings: int = 0
    total_errors: int = 0

    def add_result(self, result: ValidationResult) -> None:
        """Merge a single-table ValidationResult into this aggregate."""
        self.table_results[result.table_name] = result
        self.total_checks_passed += result.checks_passed
        self.total_checks_failed += result.checks_failed
        self.total_warnings += len(result.warnings)
        self.total_errors += len(result.errors)
        if not result.is_valid:
            self.is_valid = False

    def summary(self) -> str:
        """Return a full human-readable summary of all validation results."""
        status = "PASSED" if self.is_valid else "FAILED"
        lines = [
            "=" * 70,
            f"ExperimentIQ Data Validation — {status}",
            f"  Total checks passed : {self.total_checks_passed}",
            f"  Total checks failed : {self.total_checks_failed}",
            f"  Total warnings      : {self.total_warnings}",
            f"  Total errors        : {self.total_errors}",
            "=" * 70,
        ]
        for table_name, result in self.table_results.items():
            lines.append(result.summary())
        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DataValidator
# ---------------------------------------------------------------------------


class DataValidator:
    """
    Validates generated DataFrames against ExperimentIQ business rules
    before they are loaded into PostgreSQL.

    All validate_* methods are self-contained and can be called
    independently. validate_all() runs all checks in sequence and
    returns a consolidated OverallValidationResult.

    Cross-table checks (referential integrity) are performed only inside
    validate_all(), where all DataFrames are available simultaneously.

    Example::

        validator = DataValidator()
        result = validator.validate_all({
            "users": users_df,
            "experiments": experiments_df,
            "sessions": sessions_df,
            "events": events_df,
            "orders": orders_df,
        })
        print(result.summary())
    """

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        experiment_start_date: date | None = None,
        experiment_end_date: date | None = None,
    ) -> None:
        """
        Initialise the DataValidator.

        Args:
            experiment_start_date: Earliest acceptable assignment date.
                                   If None, date-range checks are skipped.
            experiment_end_date:   Latest acceptable assignment date.
                                   If None, date-range checks are skipped.
        """
        self.experiment_start_date = experiment_start_date
        self.experiment_end_date = experiment_end_date
        logger.debug(
            "DataValidator initialised | experiment window: %s → %s",
            experiment_start_date,
            experiment_end_date,
        )

    # ------------------------------------------------------------------
    # FILE 1 — validate_users
    # ------------------------------------------------------------------

    def validate_users(self, df: pd.DataFrame) -> ValidationResult:
        """
        Validate the users DataFrame against ExperimentIQ business rules.

        Checks performed:
            1. No NULL values in required columns (user_id, signup_date,
               customer_type, country_id, device_id, browser_id, channel_id).
            2. All customer_type values are in the valid set.
            3. signup_date values fall within the experiment window (if set).
            4. customer_type distribution is reasonably balanced
               (warn if any single type exceeds CUSTOMER_TYPE_MAX_FRACTION).
            5. No duplicate user_id values.
            6. is_returning column is boolean-compatible.

        Args:
            df: The users DataFrame produced by UserGenerator.

        Returns:
            ValidationResult with details of all checks.
        """
        result = ValidationResult(table_name="users")
        logger.info("Validating users DataFrame (%d rows) …", len(df))

        if df.empty:
            result._fail("non_empty", "users DataFrame is empty")
            return result

        # 1. Required columns present
        required_cols = [
            "user_id", "signup_date", "customer_type",
            "country_id", "device_id", "browser_id", "channel_id",
        ]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            result._fail(
                "required_columns",
                f"Missing columns: {missing_cols}",
            )
            return result  # Can't proceed without required columns
        result._pass("required_columns_present")

        # 2. No NULLs in required columns
        for col in required_cols:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                result._fail(
                    f"no_nulls_{col}",
                    f"Column '{col}' has {null_count} NULL values",
                )
            else:
                result._pass(f"no_nulls_{col}")

        # 3. No duplicate user_id
        dup_count = int(df["user_id"].duplicated().sum())
        if dup_count > 0:
            result._fail(
                "unique_user_id",
                f"{dup_count} duplicate user_id values found",
            )
        else:
            result._pass("unique_user_id")

        # 4. Valid customer_type values
        invalid_types = df["customer_type"].dropna()
        invalid_types = invalid_types[~invalid_types.isin(VALID_CUSTOMER_TYPES)]
        if len(invalid_types) > 0:
            result._fail(
                "valid_customer_type",
                f"{len(invalid_types)} rows have invalid customer_type: "
                f"{invalid_types.unique().tolist()}",
            )
        else:
            result._pass("valid_customer_type")

        # 5. customer_type distribution balance
        type_fractions = df["customer_type"].value_counts(normalize=True)
        for ctype, fraction in type_fractions.items():
            if fraction > CUSTOMER_TYPE_MAX_FRACTION:
                result._warn(
                    "customer_type_balance",
                    f"customer_type='{ctype}' represents {fraction:.1%} of users "
                    f"(threshold: {CUSTOMER_TYPE_MAX_FRACTION:.0%})",
                )
        if not result.warnings:
            result._pass("customer_type_balance")

        # 6. signup_date within experiment window
        if self.experiment_start_date and self.experiment_end_date:
            signup_dates = pd.to_datetime(df["signup_date"]).dt.date
            too_early = int((signup_dates < self.experiment_start_date).sum())
            too_late = int((signup_dates > self.experiment_end_date).sum())
            if too_early > 0:
                result._fail(
                    "signup_date_range_min",
                    f"{too_early} users have signup_date before experiment start "
                    f"({self.experiment_start_date})",
                )
            elif too_late > 0:
                result._fail(
                    "signup_date_range_max",
                    f"{too_late} users have signup_date after experiment end "
                    f"({self.experiment_end_date})",
                )
            else:
                result._pass("signup_date_range")
        else:
            logger.debug("signup_date range check skipped (no experiment window set)")

        # 7. is_returning is boolean-compatible
        if "is_returning" in df.columns:
            invalid_bool = df["is_returning"].dropna()
            invalid_bool = invalid_bool[~invalid_bool.isin([True, False, 0, 1])]
            if len(invalid_bool) > 0:
                result._fail(
                    "is_returning_boolean",
                    f"{len(invalid_bool)} non-boolean values in is_returning",
                )
            else:
                result._pass("is_returning_boolean")

        logger.info(
            "users validation complete: %d passed, %d failed, %d warnings",
            result.checks_passed,
            result.checks_failed,
            len(result.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # validate_experiments
    # ------------------------------------------------------------------

    def validate_experiments(self, df: pd.DataFrame) -> ValidationResult:
        """
        Validate the experiments DataFrame against business rules.

        Checks performed:
            1. No NULLs in required columns.
            2. Variant split is approximately 50/50
               (warn outside 40/60; error outside 30/70).
            3. No user assigned to the same experiment_name more than once
               (mirrors the UNIQUE(user_id, experiment_name) constraint).
            4. All variant values are 'control' or 'variant'.
            5. assignment_timestamp within experiment window (if set).

        Args:
            df: The experiments DataFrame produced by ExperimentGenerator.

        Returns:
            ValidationResult with details of all checks.
        """
        result = ValidationResult(table_name="experiments")
        logger.info("Validating experiments DataFrame (%d rows) …", len(df))

        if df.empty:
            result._fail("non_empty", "experiments DataFrame is empty")
            return result

        required_cols = [
            "experiment_id", "experiment_name", "variant",
            "user_id", "assignment_timestamp",
        ]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            result._fail("required_columns", f"Missing columns: {missing_cols}")
            return result
        result._pass("required_columns_present")

        # 1. No NULLs in required columns
        for col in required_cols:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                result._fail(
                    f"no_nulls_{col}",
                    f"Column '{col}' has {null_count} NULL values",
                )
            else:
                result._pass(f"no_nulls_{col}")

        # 2. Valid variant values
        invalid_variants = df["variant"].dropna()
        invalid_variants = invalid_variants[~invalid_variants.isin(VALID_VARIANTS)]
        if len(invalid_variants) > 0:
            result._fail(
                "valid_variant_values",
                f"{len(invalid_variants)} rows have invalid variant values: "
                f"{invalid_variants.unique().tolist()}",
            )
        else:
            result._pass("valid_variant_values")

        # 3. Variant split check per experiment
        for exp_name, group in df.groupby("experiment_name"):
            variant_counts = group["variant"].value_counts(normalize=True)
            variant_fraction = float(
                variant_counts.get("variant", 0.0)
            )
            if (
                variant_fraction < VARIANT_SPLIT_ERROR_LOWER
                or variant_fraction > VARIANT_SPLIT_ERROR_UPPER
            ):
                result._fail(
                    "variant_split",
                    f"Experiment '{exp_name}': variant fraction={variant_fraction:.3f} "
                    f"is outside error bounds [{VARIANT_SPLIT_ERROR_LOWER}, "
                    f"{VARIANT_SPLIT_ERROR_UPPER}]",
                )
            elif (
                variant_fraction < VARIANT_SPLIT_LOWER
                or variant_fraction > VARIANT_SPLIT_UPPER
            ):
                result._warn(
                    "variant_split",
                    f"Experiment '{exp_name}': variant fraction={variant_fraction:.3f} "
                    f"is outside warning bounds [{VARIANT_SPLIT_LOWER}, "
                    f"{VARIANT_SPLIT_UPPER}]",
                )
            else:
                result._pass(f"variant_split_{exp_name}")

        # 4. No user in multiple variants of the same experiment
        dup_assignments = df.duplicated(subset=["user_id", "experiment_name"])
        dup_count = int(dup_assignments.sum())
        if dup_count > 0:
            result._fail(
                "unique_user_experiment",
                f"{dup_count} users assigned to the same experiment more than once",
            )
        else:
            result._pass("unique_user_experiment")

        # 5. assignment_timestamp within experiment window
        if self.experiment_start_date and self.experiment_end_date:
            ts = pd.to_datetime(df["assignment_timestamp"], utc=True).dt.date
            too_early = int((ts < self.experiment_start_date).sum())
            too_late = int((ts > self.experiment_end_date).sum())
            if too_early > 0:
                result._fail(
                    "assignment_timestamp_range",
                    f"{too_early} assignments before experiment start "
                    f"({self.experiment_start_date})",
                )
            if too_late > 0:
                result._fail(
                    "assignment_timestamp_range",
                    f"{too_late} assignments after experiment end "
                    f"({self.experiment_end_date})",
                )
            if too_early == 0 and too_late == 0:
                result._pass("assignment_timestamp_range")

        logger.info(
            "experiments validation complete: %d passed, %d failed, %d warnings",
            result.checks_passed,
            result.checks_failed,
            len(result.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # validate_sessions
    # ------------------------------------------------------------------

    def validate_sessions(self, df: pd.DataFrame) -> ValidationResult:
        """
        Validate the sessions DataFrame against business rules.

        Checks performed:
            1. No NULLs in required columns.
            2. session_end >= session_start for every row.
            3. duration_seconds > 0 for all sessions.
            4. duration_seconds distribution is reasonable
               (warn if median > MAX_REASONABLE_SESSION_DURATION_SECONDS / 4).
            5. page_count >= 1 for all sessions.
            6. is_bounce sessions have page_count == 1
               (warn if violated; some generators may differ).
            7. No duplicate session_id values.

        Args:
            df: The sessions DataFrame produced by SessionGenerator.

        Returns:
            ValidationResult with details of all checks.
        """
        result = ValidationResult(table_name="sessions")
        logger.info("Validating sessions DataFrame (%d rows) …", len(df))

        if df.empty:
            result._fail("non_empty", "sessions DataFrame is empty")
            return result

        required_cols = [
            "session_id", "user_id", "session_start", "session_end",
            "duration_seconds", "device_id", "browser_id", "page_count",
        ]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            result._fail("required_columns", f"Missing columns: {missing_cols}")
            return result
        result._pass("required_columns_present")

        # 1. No NULLs
        for col in required_cols:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                result._fail(
                    f"no_nulls_{col}",
                    f"Column '{col}' has {null_count} NULL values",
                )
            else:
                result._pass(f"no_nulls_{col}")

        # 2. No duplicate session_id
        dup_count = int(df["session_id"].duplicated().sum())
        if dup_count > 0:
            result._fail(
                "unique_session_id",
                f"{dup_count} duplicate session_id values",
            )
        else:
            result._pass("unique_session_id")

        # 3. session_end >= session_start
        start_ts = pd.to_datetime(df["session_start"], utc=True)
        end_ts = pd.to_datetime(df["session_end"], utc=True)
        invalid_order = int((end_ts < start_ts).sum())
        if invalid_order > 0:
            result._fail(
                "session_end_after_start",
                f"{invalid_order} sessions have session_end < session_start",
            )
        else:
            result._pass("session_end_after_start")

        # 4. duration_seconds > 0
        non_positive_duration = int((df["duration_seconds"] <= 0).sum())
        if non_positive_duration > 0:
            result._fail(
                "positive_duration",
                f"{non_positive_duration} sessions have duration_seconds <= 0",
            )
        else:
            result._pass("positive_duration")

        # 5. Reasonable duration distribution
        median_duration = float(df["duration_seconds"].median())
        p99_duration = float(df["duration_seconds"].quantile(0.99))
        if p99_duration > MAX_REASONABLE_SESSION_DURATION_SECONDS:
            result._warn(
                "duration_distribution",
                f"p99 session duration = {p99_duration:.0f}s exceeds "
                f"{MAX_REASONABLE_SESSION_DURATION_SECONDS}s sanity threshold",
            )
        else:
            result._pass("duration_distribution")
        logger.debug("Session duration — median: %.0fs, p99: %.0fs", median_duration, p99_duration)

        # 6. page_count >= 1
        invalid_page_count = int((df["page_count"] < 1).sum())
        if invalid_page_count > 0:
            result._fail(
                "page_count_minimum",
                f"{invalid_page_count} sessions have page_count < 1",
            )
        else:
            result._pass("page_count_minimum")

        # 7. is_bounce consistency: bounced sessions should have page_count == 1
        if "is_bounce" in df.columns:
            bounce_multi_page = df[df["is_bounce"] == True]["page_count"]
            bounce_multi_page_count = int((bounce_multi_page > 1).sum())
            if bounce_multi_page_count > 0:
                result._warn(
                    "bounce_page_count_consistency",
                    f"{bounce_multi_page_count} sessions marked is_bounce=True "
                    f"but have page_count > 1",
                )
            else:
                result._pass("bounce_page_count_consistency")

        logger.info(
            "sessions validation complete: %d passed, %d failed, %d warnings",
            result.checks_passed,
            result.checks_failed,
            len(result.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # validate_events
    # ------------------------------------------------------------------

    def validate_events(
        self,
        df: pd.DataFrame,
        sessions_df: pd.DataFrame | None = None,
        event_type_ids: set[int] | None = None,
    ) -> ValidationResult:
        """
        Validate the events DataFrame against business rules.

        Checks performed:
            1. No NULLs in required columns.
            2. Revenue is NULL for non-purchase events
               (revenue only on event_type 'purchase').
            3. Revenue >= 0 where present.
            4. No unknown event_type_ids (if reference set is provided).
            5. All events' timestamps fall within their parent session window
               (requires sessions_df).
            6. No duplicate event_id values.
            7. No orphan events (events referencing session_ids not in sessions_df).

        Args:
            df:             The events DataFrame produced by EventGenerator.
            sessions_df:    Optional sessions DataFrame for temporal integrity checks.
            event_type_ids: Optional set of valid event_type_id integers
                            (from the event_types lookup table).

        Returns:
            ValidationResult with details of all checks.
        """
        result = ValidationResult(table_name="events")
        logger.info("Validating events DataFrame (%d rows) …", len(df))

        if df.empty:
            result._fail("non_empty", "events DataFrame is empty")
            return result

        required_cols = [
            "event_id", "session_id", "user_id",
            "event_type_id", "event_timestamp",
        ]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            result._fail("required_columns", f"Missing columns: {missing_cols}")
            return result
        result._pass("required_columns_present")

        # 1. No NULLs in required columns
        for col in required_cols:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                result._fail(
                    f"no_nulls_{col}",
                    f"Column '{col}' has {null_count} NULL values",
                )
            else:
                result._pass(f"no_nulls_{col}")

        # 2. No duplicate event_id
        dup_count = int(df["event_id"].duplicated().sum())
        if dup_count > 0:
            result._fail(
                "unique_event_id",
                f"{dup_count} duplicate event_id values",
            )
        else:
            result._pass("unique_event_id")

        # 3. Revenue: only on purchase events, and must be >= 0
        if "revenue" in df.columns:
            # Revenue must be non-negative where present
            negative_revenue = int((df["revenue"].dropna() < 0).sum())
            if negative_revenue > 0:
                result._fail(
                    "revenue_non_negative",
                    f"{negative_revenue} events have negative revenue",
                )
            else:
                result._pass("revenue_non_negative")

            # Revenue should be NULL on non-purchase events
            # event_type_id for 'purchase' is typically known; check via name if possible
            if "event_name" in df.columns:
                non_purchase_with_revenue = int(
                    df[(df["event_name"] != "purchase") & df["revenue"].notna()].shape[0]
                )
                if non_purchase_with_revenue > 0:
                    result._warn(
                        "revenue_only_on_purchase",
                        f"{non_purchase_with_revenue} non-purchase events have a "
                        f"non-NULL revenue value",
                    )
                else:
                    result._pass("revenue_only_on_purchase")

        # 4. Valid event_type_ids
        if event_type_ids is not None:
            unknown_ids = df[
                ~df["event_type_id"].isin(event_type_ids)
            ]["event_type_id"].unique()
            if len(unknown_ids) > 0:
                result._fail(
                    "valid_event_type_ids",
                    f"Unknown event_type_id values: {unknown_ids.tolist()[:10]}",
                )
            else:
                result._pass("valid_event_type_ids")

        # 5. Orphan events (session_id not in sessions_df)
        if sessions_df is not None and not sessions_df.empty:
            known_session_ids = set(sessions_df["session_id"].tolist())
            orphan_events = df[~df["session_id"].isin(known_session_ids)]
            if len(orphan_events) > 0:
                result._fail(
                    "no_orphan_events",
                    f"{len(orphan_events)} events reference unknown session_id values",
                )
            else:
                result._pass("no_orphan_events")

            # 6. event_timestamp within parent session window
            merged = df[["event_id", "session_id", "event_timestamp"]].merge(
                sessions_df[["session_id", "session_start", "session_end"]],
                on="session_id",
                how="inner",
            )
            if not merged.empty:
                event_ts = pd.to_datetime(merged["event_timestamp"], utc=True)
                sess_start = pd.to_datetime(merged["session_start"], utc=True)
                sess_end = pd.to_datetime(merged["session_end"], utc=True)
                outside_window = int(
                    ((event_ts < sess_start) | (event_ts > sess_end)).sum()
                )
                if outside_window > 0:
                    result._fail(
                        "event_within_session_window",
                        f"{outside_window} events have timestamps outside their "
                        f"parent session window",
                    )
                else:
                    result._pass("event_within_session_window")

        logger.info(
            "events validation complete: %d passed, %d failed, %d warnings",
            result.checks_passed,
            result.checks_failed,
            len(result.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # validate_orders
    # ------------------------------------------------------------------

    def validate_orders(
        self,
        df: pd.DataFrame,
        users_df: pd.DataFrame | None = None,
        sessions_df: pd.DataFrame | None = None,
    ) -> ValidationResult:
        """
        Validate the orders DataFrame against business rules.

        Checks performed:
            1. No NULLs in required columns.
            2. order_value > 0 for all rows.
            3. No orphan orders (user_id not in users_df).
            4. No orphan session references (session_id not in sessions_df).
            5. payment_method in VALID_PAYMENT_METHODS.
            6. payment_status in VALID_PAYMENT_STATUSES.
            7. Refund rate is realistic (warn if > MAX_REALISTIC_REFUND_RATE).
            8. No extreme order values (warn if > MAX_ORDER_VALUE_SANITY).
            9. No duplicate order_id values.

        Args:
            df:          The orders DataFrame produced by OrderGenerator.
            users_df:    Optional users DataFrame for referential integrity.
            sessions_df: Optional sessions DataFrame for referential integrity.

        Returns:
            ValidationResult with details of all checks.
        """
        result = ValidationResult(table_name="orders")
        logger.info("Validating orders DataFrame (%d rows) …", len(df))

        if df.empty:
            result._fail("non_empty", "orders DataFrame is empty")
            return result

        required_cols = [
            "order_id", "user_id", "session_id",
            "order_timestamp", "order_value",
            "payment_method", "payment_status",
        ]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            result._fail("required_columns", f"Missing columns: {missing_cols}")
            return result
        result._pass("required_columns_present")

        # 1. No NULLs in required columns
        for col in required_cols:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                result._fail(
                    f"no_nulls_{col}",
                    f"Column '{col}' has {null_count} NULL values",
                )
            else:
                result._pass(f"no_nulls_{col}")

        # 2. No duplicate order_id
        dup_count = int(df["order_id"].duplicated().sum())
        if dup_count > 0:
            result._fail(
                "unique_order_id",
                f"{dup_count} duplicate order_id values",
            )
        else:
            result._pass("unique_order_id")

        # 3. order_value > 0
        non_positive = int((df["order_value"] <= 0).sum())
        if non_positive > 0:
            result._fail(
                "order_value_positive",
                f"{non_positive} orders have order_value <= 0",
            )
        else:
            result._pass("order_value_positive")

        # 4. Extreme order values sanity check
        extreme_orders = int((df["order_value"] > MAX_ORDER_VALUE_SANITY).sum())
        if extreme_orders > 0:
            result._warn(
                "order_value_sanity",
                f"{extreme_orders} orders exceed ${MAX_ORDER_VALUE_SANITY:.0f} "
                f"(possible data generation error)",
            )
        else:
            result._pass("order_value_sanity")

        # 5. Valid payment_method values
        invalid_methods = df["payment_method"].dropna()
        invalid_methods = invalid_methods[~invalid_methods.isin(VALID_PAYMENT_METHODS)]
        if len(invalid_methods) > 0:
            result._fail(
                "valid_payment_method",
                f"{len(invalid_methods)} rows have invalid payment_method: "
                f"{invalid_methods.unique().tolist()}",
            )
        else:
            result._pass("valid_payment_method")

        # 6. Valid payment_status values
        invalid_statuses = df["payment_status"].dropna()
        invalid_statuses = invalid_statuses[~invalid_statuses.isin(VALID_PAYMENT_STATUSES)]
        if len(invalid_statuses) > 0:
            result._fail(
                "valid_payment_status",
                f"{len(invalid_statuses)} rows have invalid payment_status: "
                f"{invalid_statuses.unique().tolist()}",
            )
        else:
            result._pass("valid_payment_status")

        # 7. Refund rate sanity
        if "is_refund" in df.columns:
            total_completed = int(
                (df["payment_status"] == "completed").sum()
            )
            total_refunded = int(df["is_refund"].sum())
            if total_completed > 0:
                refund_rate = total_refunded / total_completed
                if refund_rate > MAX_REALISTIC_REFUND_RATE:
                    result._warn(
                        "refund_rate_sanity",
                        f"Refund rate = {refund_rate:.1%} exceeds realistic "
                        f"threshold of {MAX_REALISTIC_REFUND_RATE:.0%}",
                    )
                else:
                    result._pass("refund_rate_sanity")
                logger.debug("Refund rate: %.2f%%", refund_rate * 100)

        # 8. Orphan orders — user_id not in users
        if users_df is not None and not users_df.empty:
            known_user_ids = set(users_df["user_id"].tolist())
            orphan_orders = df[~df["user_id"].isin(known_user_ids)]
            if len(orphan_orders) > 0:
                result._fail(
                    "no_orphan_orders_user",
                    f"{len(orphan_orders)} orders reference unknown user_id values",
                )
            else:
                result._pass("no_orphan_orders_user")

        # 9. Orphan orders — session_id not in sessions
        if sessions_df is not None and not sessions_df.empty:
            known_session_ids = set(sessions_df["session_id"].tolist())
            orphan_orders = df[~df["session_id"].isin(known_session_ids)]
            if len(orphan_orders) > 0:
                result._fail(
                    "no_orphan_orders_session",
                    f"{len(orphan_orders)} orders reference unknown session_id values",
                )
            else:
                result._pass("no_orphan_orders_session")

        logger.info(
            "orders validation complete: %d passed, %d failed, %d warnings",
            result.checks_passed,
            result.checks_failed,
            len(result.warnings),
        )
        return result

    # ------------------------------------------------------------------
    # validate_all
    # ------------------------------------------------------------------

    def validate_all(
        self,
        dataframes_dict: dict[str, pd.DataFrame],
        event_type_ids: set[int] | None = None,
    ) -> OverallValidationResult:
        """
        Run all table-level and cross-table validations in sequence.

        This is the primary entry point for the full validation pipeline.
        It calls each individual validate_* method and then runs additional
        cross-table referential integrity checks.

        Args:
            dataframes_dict: A dictionary mapping table names to DataFrames.
                             Expected keys: "users", "experiments", "sessions",
                             "events", "orders".
            event_type_ids:  Optional set of valid event_type_id integers
                             for event validation.

        Returns:
            OverallValidationResult aggregating all individual results.

        Raises:
            KeyError: If a required DataFrame is missing from the dict.
        """
        overall = OverallValidationResult()
        logger.info(
            "Starting full data validation for tables: %s",
            list(dataframes_dict.keys()),
        )

        users_df = dataframes_dict.get("users", pd.DataFrame())
        experiments_df = dataframes_dict.get("experiments", pd.DataFrame())
        sessions_df = dataframes_dict.get("sessions", pd.DataFrame())
        events_df = dataframes_dict.get("events", pd.DataFrame())
        orders_df = dataframes_dict.get("orders", pd.DataFrame())

        # --- Individual table validations ---
        overall.add_result(self.validate_users(users_df))
        overall.add_result(self.validate_experiments(experiments_df))
        overall.add_result(self.validate_sessions(sessions_df))
        overall.add_result(
            self.validate_events(
                events_df,
                sessions_df=sessions_df if not sessions_df.empty else None,
                event_type_ids=event_type_ids,
            )
        )
        overall.add_result(
            self.validate_orders(
                orders_df,
                users_df=users_df if not users_df.empty else None,
                sessions_df=sessions_df if not sessions_df.empty else None,
            )
        )

        # --- Cross-table referential integrity ---
        cross_result = ValidationResult(table_name="cross_table_integrity")

        # experiments.user_id → users.user_id
        if not experiments_df.empty and not users_df.empty:
            known_user_ids = set(users_df["user_id"].tolist())
            exp_orphans = experiments_df[
                ~experiments_df["user_id"].isin(known_user_ids)
            ]
            if len(exp_orphans) > 0:
                cross_result._fail(
                    "experiments_user_fk",
                    f"{len(exp_orphans)} experiment rows reference unknown user_id values",
                )
            else:
                cross_result._pass("experiments_user_fk")

        # sessions.user_id → users.user_id
        if not sessions_df.empty and not users_df.empty:
            known_user_ids = set(users_df["user_id"].tolist())
            sess_orphans = sessions_df[
                ~sessions_df["user_id"].isin(known_user_ids)
            ]
            if len(sess_orphans) > 0:
                cross_result._fail(
                    "sessions_user_fk",
                    f"{len(sess_orphans)} session rows reference unknown user_id values",
                )
            else:
                cross_result._pass("sessions_user_fk")

        # events.user_id → users.user_id
        if not events_df.empty and not users_df.empty:
            known_user_ids = set(users_df["user_id"].tolist())
            evt_orphans = events_df[
                ~events_df["user_id"].isin(known_user_ids)
            ]
            if len(evt_orphans) > 0:
                cross_result._fail(
                    "events_user_fk",
                    f"{len(evt_orphans)} event rows reference unknown user_id values",
                )
            else:
                cross_result._pass("events_user_fk")

        # Verify every purchaser in orders has a corresponding user
        if not orders_df.empty and not users_df.empty:
            known_user_ids = set(users_df["user_id"].tolist())
            order_orphans = orders_df[
                ~orders_df["user_id"].isin(known_user_ids)
            ]
            if len(order_orphans) > 0:
                cross_result._fail(
                    "orders_user_fk",
                    f"{len(order_orphans)} order rows reference unknown user_id values",
                )
            else:
                cross_result._pass("orders_user_fk")

        overall.add_result(cross_result)

        logger.info(
            "Overall validation complete — %s | "
            "%d checks passed, %d failed, %d warnings, %d errors",
            "VALID" if overall.is_valid else "INVALID",
            overall.total_checks_passed,
            overall.total_checks_failed,
            overall.total_warnings,
            overall.total_errors,
        )
        return overall
