"""
ExperimentIQ Recommendations Package
======================================
Provides the decision rule framework and recommendation engine that translates
statistical outputs into actionable, human-readable experiment decisions.
"""

from src.recommendations.decision_rules import (
    DecisionRule,
    DecisionRuleSet,
    RuleEvaluationResult,
    RuleEvaluator,
)
from src.recommendations.recommendation_engine import (
    Recommendation,
    RecommendationEngine,
    RecommendationReport,
)

__all__ = [
    "DecisionRule",
    "DecisionRuleSet",
    "RuleEvaluationResult",
    "RuleEvaluator",
    "Recommendation",
    "RecommendationEngine",
    "RecommendationReport",
]
