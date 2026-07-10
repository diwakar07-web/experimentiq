"""
ExperimentIQ — Schema Validator

Purpose:
    Validates that generated DataFrames conform to the expected schema before
    attempting database ingestion. Acts as the final gate between data
    generation and database loading.

Design:
    - Checks column presence, data types, non-null constraints, and value ranges.
    - Returns structured validation results rather than raising immediately,
      allowing all issues to be collected and reported at once.
    - Raises SchemaValidationError only if critical issues are found.

Dependencies:
    - pandas >= 2.2
    - numpy >= 1.26

Inputs:
    Dictionary mapping table names to DataFrames.

Outputs:
    ValidationReport with all issues listed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    """Represents a single schema validation issue."""

    table: str
    column: Optional[str]
    severity: str  # "ERROR" | "WARNING"
    message: str

    def __str__(self) -> str:
        col_str = f".{self.column}" if self.column else ""
        return f"[{self.severity}] {self.table}{col_str}: {self.message}"


@dataclass
class ValidationReport:
    """
    Aggregates all validation issues across all tables.

    Attributes:
        issues: List of all ValidationIssue instances found.
        tables_checked: Number of tables validated.
    """

    issues: List[ValidationIssue] = field(default_factory=list)
    tables_checked: int = 0

    @property
    def errors(self) -> List[ValidationIssue]:
        """Return only ERROR-level issues."""
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Return only WARNING-level issues."""
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def is_valid(self) -> bool:
        """Return True if there are no ERROR-level issues."""
        return len(self.errors) == 0

    def log_report(self) -> None:
        """Log all issues at appropriate severity levels."""
        if self.is_valid:
            logger.info(
                "Schema validation PASSED | tables=%d | warnings=%d",
                self.tables_checked,
                len(self.warnings),
            )
        else:
            logger.error(
                "Schema validation FAILED | tables=%d | errors=%d | warnings=%d",
                self.tables_checked,
                len(self.errors),
                len(self.warnings),
            )

        for issue in self.errors:
            logger.error("  %s", issue)
        for issue in self.warnings:
            logger.warning("  %s", issue)


class SchemaValidationError(Exception):
    """Raised when schema validation produces critical errors."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        error_count = len(report.errors)
        super().__init__(
            f"Schema validation failed with {error_count} error(s). "
            f"Check ValidationReport for details."
        )


# ---------------------------------------------------------------------------
# Schema Definitions
# ---------------------------------------------------------------------------

# Required columns per table with (dtype_category, nullable)
# dtype_category: "str" | "int" | "float" | "bool" | "datetime" | "uuid" | "date"
TableSchema = Dict[str, Tuple[str, bool]]

REQUIRED_SCHEMAS: Dict[str, TableSchema] = {
    "users": {
        "user_id":          ("str",      False),
        "signup_date":      ("datetime", False),
        "country_id":       ("int",      False),
        "device_id":        ("int",      False),
        "browser_id":       ("int",      False),
        "channel_id":       ("int",      False),
        "customer_type":    ("str",      False),
        "is_returning":     ("bool",     False),
    },
    "experiments": {
        "experiment_id":        ("str",      False),
        "experiment_name":      ("str",      False),
        "variant":              ("str",      False),
        "user_id":              ("str",      False),
        "assignment_timestamp": ("datetime", False),
        "is_holdout":           ("bool",     False),
    },
    "sessions": {
        "session_id":       ("str",      False),
        "user_id":          ("str",      False),
        "session_start":    ("datetime", False),
        "session_end":      ("datetime", False),
        "duration_seconds": ("int",      False),
        "device_id":        ("int",      False),
        "browser_id":       ("int",      False),
        "page_count":       ("int",      False),
        "is_bounce":        ("bool",     False),
    },
    "events": {
        "event_id":         ("str",      False),
        "session_id":       ("str",      False),
        "user_id":          ("str",      False),
        "experiment_id":    ("str",      True),   # nullable
        "event_type_id":    ("int",      False),
        "event_timestamp":  ("datetime", False),
        "is_mobile":        ("bool",     False),
        "revenue":          ("float",    True),   # nullable
    },
    "orders": {
        "order_id":        ("str",      False),
        "user_id":         ("str",      False),
        "session_id":      ("str",      False),
        "order_timestamp": ("datetime", False),
        "order_value":     ("float",    False),
        "payment_method":  ("str",      False),
        "is_refund":       ("bool",     False),
        "payment_status":  ("str",      False),
    },
}

# Valid categorical values
VALID_VALUES: Dict[str, Dict[str, Set[str]]] = {
    "experiments": {
        "variant": {"control", "variant"},
    },
    "users": {
        "customer_type": {"new", "returning", "high_value"},
    },
    "orders": {
        "payment_status": {"completed", "failed", "pending", "refunded"},
        "payment_method": {
            "credit_card", "debit_card", "paypal",
            "apple_pay", "google_pay", "bank_transfer",
        },
    },
}


# ---------------------------------------------------------------------------
# SchemaValidator
# ---------------------------------------------------------------------------


class SchemaValidator:
    """
    Validates DataFrames against the expected database schema.

    Usage:
        validator = SchemaValidator()
        report = validator.validate_all(dataframes)
        if not report.is_valid:
            raise SchemaValidationError(report)
    """

    def validate_all(
        self,
        dataframes: Dict[str, pd.DataFrame],
    ) -> ValidationReport:
        """
        Validate all provided DataFrames against their expected schemas.

        Args:
            dataframes: Dict mapping table names to DataFrames.

        Returns:
            ValidationReport with all discovered issues.
        """
        report = ValidationReport(tables_checked=len(dataframes))

        for table_name, df in dataframes.items():
            logger.debug("Validating table: %s | rows=%d", table_name, len(df))
            issues = self._validate_table(table_name, df)
            report.issues.extend(issues)

        report.log_report()
        return report

    def validate_all_strict(self, dataframes: Dict[str, pd.DataFrame]) -> ValidationReport:
        """
        Validate and raise SchemaValidationError if any errors are found.

        Args:
            dataframes: Dict mapping table names to DataFrames.

        Returns:
            ValidationReport (only if valid).

        Raises:
            SchemaValidationError: If any ERROR-level issues are found.
        """
        report = self.validate_all(dataframes)
        if not report.is_valid:
            raise SchemaValidationError(report)
        return report

    def _validate_table(
        self,
        table_name: str,
        df: pd.DataFrame,
    ) -> List[ValidationIssue]:
        """
        Validate a single DataFrame against its schema.

        Args:
            table_name: Name of the target database table.
            df: DataFrame to validate.

        Returns:
            List of ValidationIssue instances found.
        """
        issues: List[ValidationIssue] = []

        # Skip tables without a defined schema (lookup tables)
        if table_name not in REQUIRED_SCHEMAS:
            logger.debug("No schema defined for '%s' — skipping validation", table_name)
            return issues

        schema = REQUIRED_SCHEMAS[table_name]

        # Check: table is not empty
        if df.empty:
            issues.append(ValidationIssue(
                table=table_name,
                column=None,
                severity="ERROR",
                message="DataFrame is empty",
            ))
            return issues  # No point continuing with empty DataFrame

        # Check: required columns exist
        missing_cols = set(schema.keys()) - set(df.columns)
        for col in missing_cols:
            issues.append(ValidationIssue(
                table=table_name,
                column=col,
                severity="ERROR",
                message=f"Required column is missing",
            ))

        # Only proceed with column-level checks for present columns
        present_cols = {col for col in schema.keys() if col in df.columns}

        for col in present_cols:
            dtype_cat, nullable = schema[col]
            col_issues = self._validate_column(table_name, df, col, dtype_cat, nullable)
            issues.extend(col_issues)

        # Check: valid categorical values
        if table_name in VALID_VALUES:
            for col, valid_set in VALID_VALUES[table_name].items():
                if col in df.columns:
                    invalid_mask = ~df[col].isin(valid_set) & df[col].notna()
                    invalid_count = invalid_mask.sum()
                    if invalid_count > 0:
                        invalid_sample = df[col][invalid_mask].unique()[:5].tolist()
                        issues.append(ValidationIssue(
                            table=table_name,
                            column=col,
                            severity="ERROR",
                            message=(
                                f"{invalid_count} rows have invalid values. "
                                f"Valid: {sorted(valid_set)}. "
                                f"Found (sample): {invalid_sample}"
                            ),
                        ))

        # Check: duplicate primary keys (UUID string columns named *_id)
        id_col = f"{table_name[:-1]}_id" if table_name.endswith("s") else f"{table_name}_id"
        if id_col in df.columns:
            dupe_count = df[id_col].duplicated().sum()
            if dupe_count > 0:
                issues.append(ValidationIssue(
                    table=table_name,
                    column=id_col,
                    severity="ERROR",
                    message=f"{dupe_count} duplicate primary key values found",
                ))

        return issues

    def _validate_column(
        self,
        table_name: str,
        df: pd.DataFrame,
        col: str,
        dtype_cat: str,
        nullable: bool,
    ) -> List[ValidationIssue]:
        """
        Validate a single column's nullability and basic type compatibility.

        Args:
            table_name: Table name for error context.
            df: DataFrame containing the column.
            col: Column name to validate.
            dtype_cat: Expected dtype category.
            nullable: Whether the column allows nulls.

        Returns:
            List of ValidationIssue instances.
        """
        issues: List[ValidationIssue] = []
        series = df[col]

        # Null check
        null_count = series.isnull().sum()
        if null_count > 0 and not nullable:
            issues.append(ValidationIssue(
                table=table_name,
                column=col,
                severity="ERROR",
                message=f"{null_count} NULL values found in non-nullable column",
            ))
        elif null_count > 0 and nullable:
            logger.debug("Column '%s.%s' has %d NULLs (allowed)", table_name, col, null_count)

        # Numeric range checks
        if dtype_cat == "float" and not series.dropna().empty:
            if (series.dropna() < 0).any():
                issues.append(ValidationIssue(
                    table=table_name,
                    column=col,
                    severity="WARNING",
                    message="Negative values detected — check if intentional",
                ))

        if dtype_cat == "int":
            non_null = series.dropna()
            if not non_null.empty:
                try:
                    numeric_vals = pd.to_numeric(non_null, errors="coerce")
                    if numeric_vals.isnull().any():
                        issues.append(ValidationIssue(
                            table=table_name,
                            column=col,
                            severity="ERROR",
                            message="Non-numeric values found in integer column",
                        ))
                except Exception:
                    pass

        return issues
