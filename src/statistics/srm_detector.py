"""
ExperimentIQ — Sample Ratio Mismatch (SRM) Detector

Purpose:
    Detects Sample Ratio Mismatch using a chi-square test on observed vs expected variant allocation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import pandas as pd
import scipy.stats as stats

logger = logging.getLogger(__name__)

@dataclass
class SRMResult:
    """Results of a Sample Ratio Mismatch test."""
    control_observed: int
    variant_observed: int
    control_expected: float
    variant_expected: float
    chi_square_statistic: float
    p_value: float
    srm_detected: bool
    alpha: float
    expected_split: float

class SRMDetector:
    """Detects Sample Ratio Mismatch in experiment assignments."""
    
    def __init__(self, expected_split: float = 0.5, alpha: float = 0.01) -> None:
        """
        Initialise SRM Detector.
        Note: SRM alpha is typically lower (e.g., 0.01 or 0.001) than metric alpha (0.05) 
        because false positives can derail an entire experiment.
        """
        self.expected_split = expected_split
        self.alpha = alpha
        logger.debug("SRMDetector initialised | expected_split=%.2f | alpha=%.3f", expected_split, alpha)

    def detect(self, control_n: int, variant_n: int) -> SRMResult:
        """Run chi-square test for SRM based on counts."""
        total_n = control_n + variant_n
        
        if total_n == 0:
            return SRMResult(
                control_observed=0, variant_observed=0,
                control_expected=0.0, variant_expected=0.0,
                chi_square_statistic=0.0, p_value=1.0,
                srm_detected=False, alpha=self.alpha, expected_split=self.expected_split
            )
            
        variant_expected = total_n * self.expected_split
        control_expected = total_n * (1 - self.expected_split)
        
        observed = [control_n, variant_n]
        expected = [control_expected, variant_expected]
        
        chi2_stat, p_val = stats.chisquare(f_obs=observed, f_exp=expected)
        
        srm_detected = p_val < self.alpha
        
        if srm_detected:
            logger.warning(
                "SRM DETECTED! p_value=%.5f < alpha=%.3f | observed=(%d, %d)", 
                p_val, self.alpha, control_n, variant_n
            )
            
        return SRMResult(
            control_observed=control_n,
            variant_observed=variant_n,
            control_expected=control_expected,
            variant_expected=variant_expected,
            chi_square_statistic=chi2_stat,
            p_value=p_val,
            srm_detected=srm_detected,
            alpha=self.alpha,
            expected_split=self.expected_split
        )

    def detect_from_dataframe(self, experiments_df: pd.DataFrame) -> SRMResult:
        """Helper to run SRM detection directly from an experiments DataFrame."""
        if "variant" not in experiments_df.columns or "is_holdout" not in experiments_df.columns:
            raise ValueError("DataFrame must contain 'variant' and 'is_holdout' columns")
            
        active_df = experiments_df[~experiments_df["is_holdout"]]
        counts = active_df["variant"].value_counts()
        
        control_n = counts.get("control", 0)
        variant_n = counts.get("variant", 0)
        
        return self.detect(control_n, variant_n)
