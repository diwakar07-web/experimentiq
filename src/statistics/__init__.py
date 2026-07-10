"""
ExperimentIQ Statistics Package
=================================
Provides all statistical engines: hypothesis testing, confidence intervals,
power analysis, effect size, multiple testing correction, SRM detection,
and outlier analysis.
"""

from src.statistics.hypothesis_test import HypothesisTestEngine, ZTestResult
from src.statistics.confidence_interval import ConfidenceIntervalEngine, ConfidenceIntervalResult
from src.statistics.power_analysis import PowerAnalysisEngine, PowerAnalysisResult
from src.statistics.effect_size import EffectSizeEngine, EffectSizeResult
from src.statistics.multiple_testing import MultipleTestingCorrector, CorrectedResult
from src.statistics.srm_detector import SRMDetector, SRMResult
from src.statistics.outlier_analysis import OutlierAnalyzer, OutlierAnalysisResult

__all__ = [
    "HypothesisTestEngine",
    "ZTestResult",
    "ConfidenceIntervalEngine",
    "ConfidenceIntervalResult",
    "PowerAnalysisEngine",
    "PowerAnalysisResult",
    "EffectSizeEngine",
    "EffectSizeResult",
    "MultipleTestingCorrector",
    "CorrectedResult",
    "SRMDetector",
    "SRMResult",
    "OutlierAnalyzer",
    "OutlierAnalysisResult",
]
