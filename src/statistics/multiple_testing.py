"""
ExperimentIQ — Multiple Testing Correction

Purpose:
    Applies multiple testing corrections when testing multiple metrics simultaneously.
    Implements Bonferroni and Benjamini-Hochberg (FDR).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List
from statsmodels.stats.multitest import multipletests

logger = logging.getLogger(__name__)

@dataclass
class CorrectedResult:
    """Result of a multiple testing correction for a single metric."""
    metric_name: str
    original_p_value: float
    corrected_p_value: float
    is_significant: bool
    correction_method: str
    alpha: float

class MultipleTestingCorrector:
    """Applies statistical corrections for multiple hypothesis testing."""
    
    def __init__(self, alpha: float = 0.05, method: str = 'benjamini_hochberg') -> None:
        self.alpha = alpha
        self.method = method
        logger.debug("MultipleTestingCorrector initialised | alpha=%.3f | method=%s", alpha, method)

    def correct(self, p_values: Dict[str, float]) -> List[CorrectedResult]:
        """Apply the configured correction method to a dictionary of p-values."""
        if self.method == 'bonferroni':
            return self.apply_bonferroni(p_values)
        elif self.method == 'benjamini_hochberg':
            return self.apply_benjamini_hochberg(p_values)
        else:
            raise ValueError(f"Unknown correction method: {self.method}")

    def apply_bonferroni(self, p_values: Dict[str, float]) -> List[CorrectedResult]:
        """
        Apply Bonferroni correction.
        Controls the Family-Wise Error Rate (FWER). Very conservative.
        """
        if not p_values:
            return []
            
        metrics = list(p_values.keys())
        p_vals = [p_values[m] for m in metrics]
        
        reject, pvals_corrected, _, _ = multipletests(
            pvals=p_vals, 
            alpha=self.alpha, 
            method='bonferroni'
        )
        
        results = []
        for i, metric in enumerate(metrics):
            results.append(CorrectedResult(
                metric_name=metric,
                original_p_value=p_vals[i],
                corrected_p_value=pvals_corrected[i],
                is_significant=bool(reject[i]),
                correction_method='bonferroni',
                alpha=self.alpha
            ))
            
        return results

    def apply_benjamini_hochberg(self, p_values: Dict[str, float]) -> List[CorrectedResult]:
        """
        Apply Benjamini-Hochberg (BH) correction.
        Controls the False Discovery Rate (FDR). Less conservative than Bonferroni.
        """
        if not p_values:
            return []
            
        metrics = list(p_values.keys())
        p_vals = [p_values[m] for m in metrics]
        
        reject, pvals_corrected, _, _ = multipletests(
            pvals=p_vals, 
            alpha=self.alpha, 
            method='fdr_bh'
        )
        
        results = []
        for i, metric in enumerate(metrics):
            results.append(CorrectedResult(
                metric_name=metric,
                original_p_value=p_vals[i],
                corrected_p_value=pvals_corrected[i],
                is_significant=bool(reject[i]),
                correction_method='benjamini_hochberg',
                alpha=self.alpha
            ))
            
        return results
