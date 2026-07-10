"""
ExperimentIQ — Segment Analyzer

Purpose:
    Analyzes conversion across user segments (device, country, channel, customer_type).
    Identifies which segments benefit most from the variant.

Dependencies:
    - pandas >= 2.2
"""

from __future__ import annotations

import logging
from typing import Dict, Any

import pandas as pd
from src.utils.dataframe_utils import assert_columns_exist, compute_conversion_rate

logger = logging.getLogger(__name__)

class SegmentAnalyzer:
    """Analyzes conversion across user segments."""

    def __init__(self, segment_df: pd.DataFrame) -> None:
        """
        Initialise the SegmentAnalyzer.
        
        Args:
            segment_df: DataFrame from v_segment_conversion
        """
        assert_columns_exist(segment_df, [
            "experiment_name", "variant", "device_type", "country_name", 
            "channel_name", "customer_type", "total_users", "purchasers"
        ], "SegmentAnalyzer.__init__")
        self.segment_df = segment_df
        logger.debug("SegmentAnalyzer initialised with %d rows", len(segment_df))

    def get_conversion_by_device(self) -> pd.DataFrame:
        """Get conversion metrics by device type."""
        return self._aggregate_by_dimension("device_type")

    def get_conversion_by_country(self, top_n: int = 10) -> pd.DataFrame:
        """Get conversion metrics by country (top N by volume)."""
        df = self._aggregate_by_dimension("country_name")
        # Filter top N countries by total users across both variants
        top_countries = self.segment_df.groupby("country_name")["total_users"].sum().nlargest(top_n).index
        return df[df["country_name"].isin(top_countries)].copy()

    def get_conversion_by_channel(self) -> pd.DataFrame:
        """Get conversion metrics by acquisition channel."""
        return self._aggregate_by_dimension("channel_name")

    def get_conversion_by_customer_type(self) -> pd.DataFrame:
        """Get conversion metrics by customer type."""
        return self._aggregate_by_dimension("customer_type")

    def get_top_performing_segments(self, dimension: str, top_n: int = 5) -> pd.DataFrame:
        """
        Find segments where variant has highest lift.
        
        Args:
            dimension: The segment dimension to group by.
            top_n: Number of top segments to return.
        """
        lift_df = self.compute_segment_lift(dimension)
        return lift_df.nlargest(top_n, "absolute_lift").copy()

    def compute_segment_lift(self, dimension_col: str) -> pd.DataFrame:
        """
        Compute absolute and relative lift for each value of the dimension.
        
        Args:
            dimension_col: Column name of the dimension to group by.
        """
        df = self._aggregate_by_dimension(dimension_col)
        
        control = df[df["variant"] == "control"].set_index(dimension_col)
        variant = df[df["variant"] == "variant"].set_index(dimension_col)
        
        merged = variant.join(control, lsuffix="_variant", rsuffix="_control", how="inner")
        
        merged["absolute_lift"] = merged["conversion_rate_variant"] - merged["conversion_rate_control"]
        merged["relative_lift"] = merged.apply(
            lambda x: (x["absolute_lift"] / x["conversion_rate_control"]) if x["conversion_rate_control"] > 0 else 0,
            axis=1
        )
        
        return merged.reset_index()

    def to_report_dict(self) -> Dict[str, Any]:
        """Convert segment metrics to structured dictionary for reporting."""
        return {
            "device": self.compute_segment_lift("device_type").to_dict(orient="records"),
            "channel": self.compute_segment_lift("channel_name").to_dict(orient="records"),
            "customer_type": self.compute_segment_lift("customer_type").to_dict(orient="records"),
            "top_countries": self.compute_segment_lift("country_name").nlargest(10, "total_users_control").to_dict(orient="records")
        }

    def _aggregate_by_dimension(self, dimension: str) -> pd.DataFrame:
        """Aggregate segment data by a specific dimension and compute conversion rate."""
        grouped = self.segment_df.groupby([dimension, "variant"], as_index=False)[["total_users", "purchasers"]].sum()
        return compute_conversion_rate(grouped, "purchasers", "total_users", "conversion_rate")
