"""
ExperimentIQ — Confidence Intervals

Purpose:
    Computes confidence intervals for proportions and differences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import sqrt
import scipy.stats as stats
import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class ConfidenceIntervalResult:
    """Confidence interval bounds."""
    lower: float
    upper: float
    center: float
    confidence_level: float
    margin_of_error: float

class ConfidenceIntervalEngine:
    """Computes confidence intervals for experiment metrics."""
    
    def __init__(self, confidence_level: float = 0.95) -> None:
        self.confidence_level = confidence_level
        self.alpha = 1 - confidence_level
        # z-score for the given alpha level (e.g. 1.96 for 95% CI)
        self.z_alpha_2 = stats.norm.ppf(1 - self.alpha / 2)

    def compute_proportion_ci(self, successes: int, n: int) -> ConfidenceIntervalResult:
        """Compute Wilson score interval for a single proportion."""
        if n == 0:
            return ConfidenceIntervalResult(0, 0, 0, self.confidence_level, 0)
        
        p = successes / n
        z = self.z_alpha_2
        
        denominator = 1 + z**2 / n
        center_adjusted = p + z**2 / (2 * n)
        margin = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
        
        lower = (center_adjusted - margin) / denominator
        upper = (center_adjusted + margin) / denominator
        
        return ConfidenceIntervalResult(
            lower=lower,
            upper=upper,
            center=p,
            confidence_level=self.confidence_level,
            margin_of_error=(upper - lower) / 2
        )

    def compute_difference_ci(self, control_n: int, variant_n: int, control_conversions: int, variant_conversions: int) -> ConfidenceIntervalResult:
        """Compute confidence interval for the difference between two proportions."""
        if control_n == 0 or variant_n == 0:
            return ConfidenceIntervalResult(0, 0, 0, self.confidence_level, 0)
            
        p1 = control_conversions / control_n
        p2 = variant_conversions / variant_n
        
        diff = p2 - p1
        se = sqrt(p1 * (1 - p1) / control_n + p2 * (1 - p2) / variant_n)
        margin = self.z_alpha_2 * se
        
        return ConfidenceIntervalResult(
            lower=diff - margin,
            upper=diff + margin,
            center=diff,
            confidence_level=self.confidence_level,
            margin_of_error=margin
        )

    def compute_revenue_ci(self, values: np.ndarray) -> ConfidenceIntervalResult:
        """Compute t-based confidence interval for continuous metrics like revenue."""
        n = len(values)
        if n < 2:
            center = float(values[0]) if n == 1 else 0.0
            return ConfidenceIntervalResult(center, center, center, self.confidence_level, 0)
            
        mean = np.mean(values)
        se = stats.sem(values)
        margin = se * stats.t.ppf((1 + self.confidence_level) / 2., n-1)
        
        return ConfidenceIntervalResult(
            lower=mean - margin,
            upper=mean + margin,
            center=mean,
            confidence_level=self.confidence_level,
            margin_of_error=margin
        )
