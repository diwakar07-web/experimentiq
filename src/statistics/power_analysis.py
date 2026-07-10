"""
ExperimentIQ — Power Analysis

Purpose:
    Computes statistical power for the observed experiment and 
    required sample sizes for a target MDE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from statsmodels.stats.proportion import proportion_effectsize
from statsmodels.stats.power import NormalIndPower

logger = logging.getLogger(__name__)

@dataclass
class PowerAnalysisResult:
    """Results of a power analysis computation."""
    baseline_rate: float
    variant_rate: float
    effect_size: float
    alpha: float
    achieved_power: float
    required_sample_size_per_group: int
    current_n_control: int
    current_n_variant: int
    is_adequately_powered: bool
    mde: float

class PowerAnalysisEngine:
    """Computes statistical power and required sample size."""
    
    def __init__(self, alpha: float = 0.05, power_target: float = 0.80) -> None:
        self.alpha = alpha
        self.power_target = power_target
        self.analyzer = NormalIndPower()
        logger.debug("PowerAnalysisEngine initialised | alpha=%.3f | power_target=%.3f", alpha, power_target)

    def compute_achieved_power(self, control_rate: float, variant_rate: float, n_control: int, n_variant: int) -> PowerAnalysisResult:
        """Compute achieved power and other power metrics based on observed data."""
        if n_control <= 0 or n_variant <= 0:
            return PowerAnalysisResult(control_rate, variant_rate, 0, self.alpha, 0, 0, n_control, n_variant, False, 0)
            
        effect_size = proportion_effectsize(variant_rate, control_rate)
        ratio = n_variant / n_control
        
        # Determine actual achieved power
        if effect_size == 0:
            achieved_power = self.alpha
        else:
            achieved_power = self.analyzer.power(
                effect_size=effect_size,
                nobs1=n_control,
                alpha=self.alpha,
                ratio=ratio,
                alternative='two-sided'
            )
            
        # Determine required sample size for the observed effect size to hit target power
        if effect_size != 0:
            required_n = self.estimate_required_sample_size(control_rate, abs(variant_rate - control_rate))
        else:
            required_n = 0
            
        mde = self.compute_mde_for_sample_size(control_rate, min(n_control, n_variant))
        
        return PowerAnalysisResult(
            baseline_rate=control_rate,
            variant_rate=variant_rate,
            effect_size=effect_size,
            alpha=self.alpha,
            achieved_power=achieved_power,
            required_sample_size_per_group=required_n,
            current_n_control=n_control,
            current_n_variant=n_variant,
            is_adequately_powered=achieved_power >= self.power_target,
            mde=mde
        )

    def estimate_required_sample_size(self, baseline_rate: float, mde: float, alternative: str = 'two-sided') -> int:
        """Estimate the required sample size per group for a given Minimum Detectable Effect."""
        if mde == 0:
            return 0
            
        target_rate = baseline_rate + mde
        effect_size = proportion_effectsize(target_rate, baseline_rate)
        
        nobs1 = self.analyzer.solve_power(
            effect_size=effect_size,
            power=self.power_target,
            alpha=self.alpha,
            ratio=1.0,
            alternative=alternative
        )
        return int(nobs1)

    def compute_mde_for_sample_size(self, baseline_rate: float, n_per_group: int) -> float:
        """Determine what Minimum Detectable Effect can be found given a sample size."""
        if n_per_group <= 0:
            return 0.0
            
        effect_size = self.analyzer.solve_power(
            nobs1=n_per_group,
            power=self.power_target,
            alpha=self.alpha,
            ratio=1.0,
            alternative='two-sided'
        )
        
        # Reverse engineer the target rate from effect size
        # Cohen's h = 2 * (arcsin(sqrt(p1)) - arcsin(sqrt(p2)))
        import math
        phi1 = effect_size + 2 * math.asin(math.sqrt(baseline_rate))
        target_rate = math.sin(phi1 / 2)**2
        
        return target_rate - baseline_rate
