"""
ExperimentIQ — Outlier Analysis

Purpose:
    Analyzes the impact of revenue outliers on the average order value and RPV metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict
import numpy as np
import scipy.stats as stats
import scipy.stats.mstats as mstats

logger = logging.getLogger(__name__)

@dataclass
class OutlierAnalysisResult:
    """Results of outlier analysis on a continuous metric."""
    total_records: int
    outlier_count: int
    outlier_fraction: float
    mean_with_outliers: float
    mean_without_outliers: float
    mean_difference_pct: float
    outlier_threshold: float
    outliers_material: bool

class OutlierAnalyzer:
    """Analyzes outliers using the Interquartile Range (IQR) method."""
    
    def __init__(self, threshold_multiplier: float = 3.0) -> None:
        """
        Initialise OutlierAnalyzer.
        Typically, 1.5 is a standard outlier, 3.0 is an extreme outlier.
        """
        self.threshold_multiplier = threshold_multiplier
        logger.debug("OutlierAnalyzer initialised | multiplier=%.1f", threshold_multiplier)

    def detect_iqr_outliers(self, values: np.ndarray) -> np.ndarray:
        """
        Detect outliers using IQR.
        Returns a boolean mask where True indicates an outlier.
        """
        if len(values) < 4:
            return np.zeros(len(values), dtype=bool)
            
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        
        upper_bound = q3 + (self.threshold_multiplier * iqr)
        lower_bound = q1 - (self.threshold_multiplier * iqr)
        
        return (values > upper_bound) | (values < lower_bound)

    def analyze_revenue_outliers(self, control_values: np.ndarray, variant_values: np.ndarray) -> Dict[str, OutlierAnalysisResult]:
        """Analyze the impact of outliers on control and variant revenue distributions."""
        return {
            "control": self._analyze_distribution(control_values),
            "variant": self._analyze_distribution(variant_values)
        }

    def compute_winsorized_mean(self, values: np.ndarray, limits: tuple[float, float] = (0.05, 0.05)) -> float:
        """
        Compute mean after winsorizing the data (capping extreme values).
        Limits specify the fraction of data to clip at bottom and top.
        """
        if len(values) == 0:
            return 0.0
        winsorized = mstats.winsorize(values, limits=limits)
        return float(np.mean(winsorized))

    def _analyze_distribution(self, values: np.ndarray) -> OutlierAnalysisResult:
        """Helper to analyze a single distribution."""
        n = len(values)
        if n == 0:
            return OutlierAnalysisResult(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, False)
            
        outlier_mask = self.detect_iqr_outliers(values)
        outlier_count = int(np.sum(outlier_mask))
        
        mean_with = float(np.mean(values))
        
        if outlier_count == 0 or outlier_count == n:
            mean_without = mean_with
            threshold = float(np.max(values)) if n > 0 else 0.0
        else:
            clean_values = values[~outlier_mask]
            mean_without = float(np.mean(clean_values))
            
            q1, q3 = np.percentile(values, [25, 75])
            threshold = q3 + (self.threshold_multiplier * (q3 - q1))
            
        diff_pct = (abs(mean_with - mean_without) / mean_without * 100) if mean_without > 0 else 0.0
        
        return OutlierAnalysisResult(
            total_records=n,
            outlier_count=outlier_count,
            outlier_fraction=outlier_count / n if n > 0 else 0.0,
            mean_with_outliers=mean_with,
            mean_without_outliers=mean_without,
            mean_difference_pct=diff_pct,
            outlier_threshold=threshold,
            outliers_material=diff_pct > 5.0
        )
