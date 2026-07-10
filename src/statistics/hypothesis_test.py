"""
ExperimentIQ — Hypothesis Testing

Purpose:
    Implements the Two-Proportion Z-Test for the primary metric.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import sqrt
import scipy.stats as stats

logger = logging.getLogger(__name__)

@dataclass
class ZTestResult:
    """Results of a two-proportion Z-test."""
    control_n: int
    variant_n: int
    control_conversions: int
    variant_conversions: int
    control_rate: float
    variant_rate: float
    absolute_lift: float
    relative_lift_pct: float
    z_score: float
    p_value: float
    is_significant: bool
    alpha: float
    pooled_proportion: float
    standard_error: float
    test_direction: str

class HypothesisTestEngine:
    """Runs hypothesis tests for experimental data."""
    
    def __init__(self, alpha: float = 0.05) -> None:
        self.alpha = alpha
        logger.debug("HypothesisTestEngine initialised | alpha=%.3f", alpha)

    def validate_inputs(self, control_n: int, variant_n: int, control_conversions: int, variant_conversions: int) -> None:
        """Validates input constraints."""
        if control_n <= 0 or variant_n <= 0:
            raise ValueError("Sample sizes must be greater than zero.")
        if control_conversions > control_n or variant_conversions > variant_n:
            raise ValueError("Conversions cannot exceed sample size.")
        if control_conversions < 0 or variant_conversions < 0:
            raise ValueError("Conversions cannot be negative.")

    def run_two_proportion_z_test(self, control_n: int, variant_n: int, control_conversions: int, variant_conversions: int) -> ZTestResult:
        """
        Run a two-proportion Z-test.
        
        Formulas:
        p_pooled = (x1 + x2) / (n1 + n2)
        SE = sqrt(p_pooled * (1 - p_pooled) * (1/n1 + 1/n2))
        z = (p2 - p1) / SE
        """
        self.validate_inputs(control_n, variant_n, control_conversions, variant_conversions)
        
        p_control = control_conversions / control_n if control_n > 0 else 0
        p_variant = variant_conversions / variant_n if variant_n > 0 else 0
        
        p_pooled = (control_conversions + variant_conversions) / (control_n + variant_n)
        se = sqrt(p_pooled * (1 - p_pooled) * (1/control_n + 1/variant_n))
        
        if se == 0:
            z_score = 0.0
            p_value = 1.0
        else:
            z_score = (p_variant - p_control) / se
            p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))
            
        absolute_lift = p_variant - p_control
        relative_lift_pct = (absolute_lift / p_control * 100) if p_control > 0 else 0.0
        
        return ZTestResult(
            control_n=control_n,
            variant_n=variant_n,
            control_conversions=control_conversions,
            variant_conversions=variant_conversions,
            control_rate=p_control,
            variant_rate=p_variant,
            absolute_lift=absolute_lift,
            relative_lift_pct=relative_lift_pct,
            z_score=z_score,
            p_value=p_value,
            is_significant=p_value < self.alpha,
            alpha=self.alpha,
            pooled_proportion=p_pooled,
            standard_error=se,
            test_direction="two-tailed"
        )
