"""
ExperimentIQ — DataFrame Utility Functions

Purpose:
    Provides reusable pandas DataFrame operations used across the analytics,
    statistics, and reporting layers. Centralises common transformations to
    avoid duplication and ensure consistency.

Design:
    - All functions are pure (no side effects beyond logging).
    - All functions accept and return typed DataFrames.
    - Validation is built into every function — fails fast on unexpected input.

Dependencies:
    - pandas >= 2.2
    - numpy >= 1.26

Inputs:
    pandas DataFrames with documented column requirements.

Outputs:
    Transformed or validated DataFrames.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------


def assert_columns_exist(df: pd.DataFrame, required_columns: Sequence[str], context: str = "") -> None:
    """
    Assert that a DataFrame contains all required columns.

    Args:
        df: DataFrame to validate.
        required_columns: Sequence of required column names.
        context: Optional context string for error messages (e.g., function name).

    Raises:
        ValueError: If any required column is missing.
    """
    missing = set(required_columns) - set(df.columns)
    if missing:
        ctx = f" (in {context})" if context else ""
        raise ValueError(
            f"DataFrame missing required columns{ctx}: {sorted(missing)}. "
            f"Available columns: {sorted(df.columns.tolist())}"
        )


def assert_not_empty(df: pd.DataFrame, context: str = "") -> None:
    """
    Assert that a DataFrame is not empty.

    Args:
        df: DataFrame to validate.
        context: Optional context string.

    Raises:
        ValueError: If the DataFrame is empty.
    """
    if df.empty:
        ctx = f" ({context})" if context else ""
        raise ValueError(f"DataFrame is empty{ctx}. Cannot proceed with empty data.")


# ---------------------------------------------------------------------------
# Categorical Value Helpers
# ---------------------------------------------------------------------------


def safe_category_cast(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """
    Cast specified string columns to pandas Categorical dtype for memory efficiency.

    Silently skips columns that don't exist in the DataFrame.

    Args:
        df: Source DataFrame.
        columns: Column names to convert to Categorical.

    Returns:
        DataFrame with specified columns cast to Categorical.
    """
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype("category")
            logger.debug("Cast column '%s' to Categorical", col)
    return df


# ---------------------------------------------------------------------------
# Aggregation Helpers
# ---------------------------------------------------------------------------


def compute_conversion_rate(
    df: pd.DataFrame,
    numerator_col: str,
    denominator_col: str,
    output_col: str = "conversion_rate",
) -> pd.DataFrame:
    """
    Add a conversion rate column to a DataFrame (numerator / denominator).

    Handles division by zero by returning 0.0.

    Args:
        df: DataFrame containing numerator and denominator columns.
        numerator_col: Column name for the numerator (e.g., "purchasers").
        denominator_col: Column name for the denominator (e.g., "total_users").
        output_col: Name for the new conversion rate column.

    Returns:
        DataFrame with the new conversion rate column appended.

    Raises:
        ValueError: If required columns are missing.
    """
    assert_columns_exist(df, [numerator_col, denominator_col], "compute_conversion_rate")
    df = df.copy()
    df[output_col] = np.where(
        df[denominator_col] == 0,
        0.0,
        df[numerator_col] / df[denominator_col],
    )
    return df


def compute_lift(
    control_rate: float,
    variant_rate: float,
) -> dict[str, float]:
    """
    Compute absolute and relative lift between control and variant rates.

    Args:
        control_rate: Conversion rate for the control group (e.g., 0.035).
        variant_rate: Conversion rate for the variant group (e.g., 0.040).

    Returns:
        Dictionary with:
            - absolute_lift: variant_rate - control_rate
            - relative_lift: (variant_rate - control_rate) / control_rate
            - absolute_lift_pct: absolute_lift * 100
            - relative_lift_pct: relative_lift * 100

    Raises:
        ValueError: If control_rate is zero (lift is undefined).
    """
    if control_rate == 0:
        raise ValueError(
            "Control rate is 0 — relative lift is undefined. "
            "Check data completeness."
        )
    absolute_lift = variant_rate - control_rate
    relative_lift = absolute_lift / control_rate
    return {
        "absolute_lift": absolute_lift,
        "relative_lift": relative_lift,
        "absolute_lift_pct": absolute_lift * 100,
        "relative_lift_pct": relative_lift * 100,
    }


# ---------------------------------------------------------------------------
# Splitting & Filtering Helpers
# ---------------------------------------------------------------------------


def split_by_variant(
    df: pd.DataFrame,
    variant_col: str = "variant",
    control_label: str = "control",
    variant_label: str = "variant",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split a DataFrame into control and variant subsets.

    Args:
        df: DataFrame with a variant column.
        variant_col: Column containing variant labels.
        control_label: Label for the control group.
        variant_label: Label for the variant group.

    Returns:
        Tuple of (control_df, variant_df).

    Raises:
        ValueError: If the variant column is missing or labels are not found.
    """
    assert_columns_exist(df, [variant_col], "split_by_variant")

    control_df = df[df[variant_col] == control_label].copy()
    variant_df = df[df[variant_col] == variant_label].copy()

    if control_df.empty:
        raise ValueError(
            f"No rows found for control label '{control_label}' in column '{variant_col}'. "
            f"Found labels: {df[variant_col].unique().tolist()}"
        )
    if variant_df.empty:
        raise ValueError(
            f"No rows found for variant label '{variant_label}' in column '{variant_col}'. "
            f"Found labels: {df[variant_col].unique().tolist()}"
        )

    logger.debug(
        "Split DataFrame | control=%d rows | variant=%d rows",
        len(control_df),
        len(variant_df),
    )
    return control_df, variant_df


def filter_date_range(
    df: pd.DataFrame,
    date_col: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Filter a DataFrame to a date range (inclusive on both ends).

    Args:
        df: DataFrame with a date/timestamp column.
        date_col: Name of the date column.
        start_date: Start date string (ISO 8601 or None for no lower bound).
        end_date: End date string (ISO 8601 or None for no upper bound).

    Returns:
        Filtered DataFrame.

    Raises:
        ValueError: If the date column is missing.
    """
    assert_columns_exist(df, [date_col], "filter_date_range")
    result = df.copy()

    if start_date:
        result = result[result[date_col] >= pd.Timestamp(start_date)]
    if end_date:
        result = result[result[date_col] <= pd.Timestamp(end_date)]

    logger.debug(
        "Date filter | col=%s | start=%s | end=%s | rows_in=%d | rows_out=%d",
        date_col, start_date, end_date, len(df), len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Summary / Profiling Helpers
# ---------------------------------------------------------------------------


def log_dataframe_summary(df: pd.DataFrame, name: str = "DataFrame") -> None:
    """
    Log a brief summary of a DataFrame's shape, columns, and null counts.

    Args:
        df: DataFrame to summarise.
        name: Human-readable label for the log message.
    """
    null_counts = df.isnull().sum()
    cols_with_nulls = null_counts[null_counts > 0]
    logger.info(
        "%s | shape=%s | dtypes=%d | nulls_in=%d columns",
        name,
        df.shape,
        df.dtypes.nunique(),
        len(cols_with_nulls),
    )
    for col, count in cols_with_nulls.items():
        logger.debug("  Null in '%s': %d (%.1f%%)", col, count, 100 * count / len(df))


def safe_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: str | List[str],
    how: str = "inner",
    context: str = "",
) -> pd.DataFrame:
    """
    Merge two DataFrames with validation and logging.

    Logs the number of rows before and after the merge to catch unexpected
    data loss from bad joins.

    Args:
        left: Left DataFrame.
        right: Right DataFrame.
        on: Column(s) to join on.
        how: Merge type ('inner', 'left', 'right', 'outer').
        context: Optional context for log messages.

    Returns:
        Merged DataFrame.
    """
    result = pd.merge(left, right, on=on, how=how)
    logger.debug(
        "Merge%s | on=%s | how=%s | left=%d | right=%d | result=%d",
        f" ({context})" if context else "",
        on,
        how,
        len(left),
        len(right),
        len(result),
    )
    return result


def to_percent_str(value: float, decimals: int = 2) -> str:
    """
    Format a float (0.0 – 1.0) as a percentage string.

    Args:
        value: Float between 0 and 1.
        decimals: Number of decimal places.

    Returns:
        Formatted string (e.g., "3.50%").
    """
    return f"{value * 100:.{decimals}f}%"
