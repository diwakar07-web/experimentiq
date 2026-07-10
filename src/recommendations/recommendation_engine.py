"""
ExperimentIQ — Recommendation Engine

Purpose:
    Applies the decision rules to statistical outputs and produces 
    a final, human-readable recommendation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any

from config.settings import RecommendationSettings, StatisticsSettings
from src.statistics.hypothesis_test import ZTestResult
from src.statistics.power_analysis import PowerAnalysisResult
from src.statistics.srm_detector import SRMResult
from src.statistics.effect_size import EffectSizeResult
from src.analytics.metrics_engine import ExperimentMetrics
from src.recommendations.decision_rules import RuleEvaluationResult, RuleEvaluator, DecisionRuleSet

logger = logging.getLogger(__name__)

class Recommendation(Enum):
    LAUNCH = "LAUNCH"
    CONTINUE_EXPERIMENT = "CONTINUE_EXPERIMENT"
    STOP_FOR_FUTILITY = "STOP_FOR_FUTILITY"
    INVESTIGATE_DATA_QUALITY = "INVESTIGATE_DATA_QUALITY"

@dataclass
class RecommendationReport:
    """A comprehensive recommendation based on all experiment inputs."""
    recommendation: Recommendation
    decision: str
    confidence: str
    summary: str
    rule_results: List[RuleEvaluationResult]
    key_metrics: Dict[str, Any]
    generated_at: datetime
    experiment_name: str

class RecommendationEngine:
    """Generates business recommendations from statistical tests."""
    
    def __init__(self, settings: RecommendationSettings, statistics_settings: StatisticsSettings) -> None:
        self.settings = settings
        self.statistics_settings = statistics_settings
        
        # Build rule set from settings
        rule_set = DecisionRuleSet(
            significance_alpha=statistics_settings.alpha,
            power_target=statistics_settings.power_target,
            practical_uplift_min=settings.practical_uplift_min,
            guardrail_bounce_rate_max=settings.guardrail_bounce_rate_max,
            srm_alpha=statistics_settings.srm_alpha
        )
        self.evaluator = RuleEvaluator(rule_set)
        
        logger.debug("RecommendationEngine initialised")

    def generate(
        self,
        z_test_result: ZTestResult,
        power_result: PowerAnalysisResult,
        srm_result: SRMResult,
        effect_size_result: EffectSizeResult,
        metrics: ExperimentMetrics,
        required_sample_size: int
    ) -> RecommendationReport:
        """
        Generate a final recommendation report.
        
        Decision logic:
        1. If SRM detected: INVESTIGATE_DATA_QUALITY
        2. If p >= alpha AND current_n < required_n: CONTINUE_EXPERIMENT
        3. If p >= alpha AND current_n >= required_n: STOP_FOR_FUTILITY
        4. If p < alpha AND power >= target AND practical_uplift >= min AND guardrails OK: LAUNCH
        5. If p < alpha AND (power < target OR practical_uplift < min): CONTINUE_EXPERIMENT
        6. Otherwise: INVESTIGATE_DATA_QUALITY
        """
        # Evaluate all rules
        evaluation_inputs = {
            "p_value": z_test_result.p_value,
            "achieved_power": power_result.achieved_power,
            "relative_lift": z_test_result.relative_lift_pct,
            "control_bounce_rate": metrics.control_bounce_rate,
            "variant_bounce_rate": metrics.variant_bounce_rate,
            "srm_detected": srm_result.srm_detected,
            "current_n": z_test_result.control_n,  # Simplifying to control N
            "required_n": required_sample_size
        }
        
        rule_results = self.evaluator.evaluate_all(evaluation_inputs)
        
        # Apply decision logic tree
        is_significant = z_test_result.is_significant
        srm_detected = srm_result.srm_detected
        is_powered = power_result.is_adequately_powered
        has_practical_uplift = z_test_result.relative_lift_pct >= self.settings.practical_uplift_min
        sufficient_n = z_test_result.control_n >= required_sample_size
        
        # Check guardrails from rule results
        guardrail_passed = next(
            (r.passed for r in rule_results if r.rule_name == "Guardrail Bounce Rate"), 
            True
        )
        
        recommendation = Recommendation.INVESTIGATE_DATA_QUALITY
        
        if srm_detected:
            recommendation = Recommendation.INVESTIGATE_DATA_QUALITY
        elif not is_significant and not sufficient_n:
            recommendation = Recommendation.CONTINUE_EXPERIMENT
        elif not is_significant and sufficient_n:
            recommendation = Recommendation.STOP_FOR_FUTILITY
        elif is_significant and is_powered and has_practical_uplift and guardrail_passed:
            recommendation = Recommendation.LAUNCH
        elif is_significant and (not is_powered or not has_practical_uplift):
            recommendation = Recommendation.CONTINUE_EXPERIMENT
            
        decision = recommendation.value.replace("_", " ").title()
        
        key_metrics = {
            "p_value": z_test_result.p_value,
            "relative_lift_pct": z_test_result.relative_lift_pct,
            "achieved_power": power_result.achieved_power,
            "cohens_h": effect_size_result.cohens_h,
            "control_n": z_test_result.control_n,
            "required_n": required_sample_size
        }
        
        confidence = self._determine_confidence(rule_results)
        summary = self._generate_summary(recommendation, key_metrics)
        
        logger.info("Recommendation generated: %s | confidence: %s", recommendation.name, confidence)
        
        return RecommendationReport(
            recommendation=recommendation,
            decision=decision,
            confidence=confidence,
            summary=summary,
            rule_results=rule_results,
            key_metrics=key_metrics,
            generated_at=datetime.utcnow(),
            experiment_name=metrics.experiment_name
        )

    def _generate_summary(self, recommendation: Recommendation, metrics: Dict[str, Any]) -> str:
        """Generate a natural language explanation."""
        lift = metrics["relative_lift_pct"]
        p_val = metrics["p_value"]
        power = metrics["achieved_power"]
        
        if recommendation == Recommendation.LAUNCH:
            return (
                f"Variant improved purchase conversion by {lift:.2f}% (relative lift). "
                f"The observed difference is statistically significant (p = {p_val:.4f}). "
                f"The test has adequate statistical power ({power:.2%} > 80%) and meets all "
                f"business guardrails. We recommend launching the variant to 100% of traffic."
            )
        elif recommendation == Recommendation.CONTINUE_EXPERIMENT:
            return (
                f"The experiment is currently inconclusive. While we observe a lift of {lift:.2f}%, "
                f"either statistical significance is not met (p = {p_val:.4f}) or the test lacks "
                f"sufficient power ({power:.2%}). We recommend continuing the experiment until "
                f"the required sample size of {metrics['required_n']} is reached."
            )
        elif recommendation == Recommendation.STOP_FOR_FUTILITY:
            return (
                f"The variant failed to produce a statistically significant improvement "
                f"(p = {p_val:.4f}). We have reached the required sample size of "
                f"{metrics['required_n']} users, meaning the test is fully powered. "
                f"Continuing the experiment is unlikely to yield a different result. "
                f"We recommend stopping the experiment and retaining the control experience."
            )
        else:
            return (
                f"Data quality issues detected. The experiment exhibits a Sample Ratio Mismatch (SRM) "
                f"or violates critical guardrails. The statistical results (p = {p_val:.4f}) cannot "
                f"be trusted until the underlying tracking or assignment issue is resolved."
            )

    def _determine_confidence(self, rule_results: List[RuleEvaluationResult]) -> str:
        """Determine confidence level based on rule evaluations."""
        passed_rules = sum(1 for r in rule_results if r.passed)
        total_rules = len(rule_results)
        
        if passed_rules == total_rules:
            return "HIGH"
        elif passed_rules >= total_rules - 2:
            return "MEDIUM"
        else:
            return "LOW"
