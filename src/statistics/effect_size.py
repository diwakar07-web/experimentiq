"""
ExperimentIQ — Effect Size

Purpose:
    Computes Cohen's h effect size for proportion comparisons.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import asin, sqrt

logger = logging.getLogger(__name__)

@dataclass
class EffectSizeResult:
    """Cohen's h effect size results."""
    cohens_h: float
    phi_control: float
    phi_variant: float
    magnitude: str
    control_rate: float
    variant_rate: float

class EffectSizeEngine:
    """Computes and interprets effect sizes for proportions."""
    
    def compute_cohens_h(self, control_rate: float, variant_rate: float) -> EffectSizeResult:
        """
        Compute Cohen's h for two proportions.
        
        Formula:
        phi = 2 * arcsin(sqrt(p))
        h = phi1 - phi2
        """
        # Constrain probabilities to valid domain [0, 1]
        p_c = max(0.0, min(1.0, control_rate))
        p_v = max(0.0, min(1.0, variant_rate))
        
        phi_control = 2 * asin(sqrt(p_c))
        phi_variant = 2 * asin(sqrt(p_v))
        
        # We calculate it as variant - control so positive means variant is better
        cohens_h = phi_variant - phi_control
        magnitude = self.interpret_magnitude(cohens_h)
        
        return EffectSizeResult(
            cohens_h=cohens_h,
            phi_control=phi_control,
            phi_variant=phi_variant,
            magnitude=magnitude,
            control_rate=control_rate,
            variant_rate=variant_rate
        )

    def interpret_magnitude(self, h: float) -> str:
        """
        Interpret the magnitude of Cohen's h.
        |h| < 0.2: negligible
        |h| >= 0.2: small
        |h| >= 0.5: medium
        |h| >= 0.8: large
        """
        abs_h = abs(h)
        if abs_h < 0.2:
            return "negligible"
        elif abs_h < 0.5:
            return "small"
        elif abs_h < 0.8:
            return "medium"
        else:
            return "large"
