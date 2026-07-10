"""
ExperimentIQ — Decision Rules
================================

Purpose:
    Defines configurable business decision rules for the recommendation engine.
    Each rule encapsulates a named threshold, a direction of comparison, and a
    human-readable description. The RuleEvaluator applies all rules against live
    statistical outputs and returns typed RuleEvaluationResult objects that are
    later consumed by the RecommendationEngine.

Design:
    - DecisionRule: immutable configuration dataclass for a single criterion.
    - DecisionRuleSet: container that groups all rules required by the engine.
    - RuleEvaluationResult: carries the outcome of a single evaluation pass.
    - RuleEvaluator: stateless evaluator that applies the rule set.

Usage:
    rule_set = DecisionRuleSet()
    evaluator = RuleEvaluator(rule_set)
    results = evaluator.evaluate_all({
        "p_value": 0.03,
        "achieved_power": 0.85,
        "relative_lift": 0.12,
        "control_bounce_rate": 0.42,
        "variant_bounce_rate": 0.43,
        "srm_detected": False,
        "current_n": 25000,
        "required_n": 20000,
    })
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core Rule Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionRule:
    """
    An immutable configuration object for a single business decision criterion.

    Attributes:
        name: Unique identifier for the rule (e.g. 'significance_rule').
        description: Human-readable explanation of what the rule checks.
        threshold: The numeric threshold value used in the comparison.
        direction: How the actual value must compare to the threshold.
            'greater'  → pass if actual_value > threshold
            'less'     → pass if actual_value < threshold
            'between'  → reserved for future range checks (not used currently)
    """

    name: str
    description: str
    threshold: float
    direction: str  # 'greater', 'less', 'between'

    def __post_init__(self) -> None:
        """Validate that direction is one of the allowed values."""
        allowed = {"greater", "less", "between"}
        if self.direction not in allowed:
            raise ValueError(
                f"DecisionRule '{self.name}': direction must be one of {allowed}, "
                f"got '{self.direction}'."
            )


@dataclass
class RuleEvaluationResult:
    """
    The outcome of evaluating a single DecisionRule against a real measurement.

    Attributes:
        rule_name: The name of the rule that was evaluated.
        passed: True if the rule's criterion was satisfied.
        actual_value: The measured value that was tested against the threshold.
        threshold: The threshold value from the rule definition.
        message: A human-readable sentence describing the outcome.
    """

    rule_name: str
    passed: bool
    actual_value: float
    threshold: float
    message: str


# ---------------------------------------------------------------------------
# Rule Set
# ---------------------------------------------------------------------------


@dataclass
class DecisionRuleSet:
    """
    Container that groups all decision rules used by the recommendation engine.

    Each attribute is a DecisionRule instance with a default that mirrors the
    recommended statistical thresholds. Individual rules can be overridden at
    construction time if the experiment uses custom thresholds.

    Attributes:
        significance_rule: Requires p-value to be below the alpha threshold.
        power_rule: Requires achieved power to meet the minimum power target.
        practical_uplift_rule: Requires relative lift to exceed a practical minimum.
        guardrail_bounce_rate_rule: Ensures bounce rate does not degrade beyond tolerance.
        srm_rule: Flags if a Sample Ratio Mismatch was detected.
        sample_size_rule: Checks that the minimum required sample size was reached.
    """

    significance_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="significance_rule",
            description=(
                "The p-value must be strictly below the significance level (alpha) "
                "to declare a statistically significant result."
            ),
            threshold=0.05,
            direction="less",
        )
    )

    power_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="power_rule",
            description=(
                "Achieved statistical power must meet or exceed the target (1 - beta) "
                "to ensure adequate sensitivity to detect the true effect."
            ),
            threshold=0.80,
            direction="greater",
        )
    )

    practical_uplift_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="practical_uplift_rule",
            description=(
                "The relative conversion lift must exceed the minimum practical uplift "
                "threshold to justify the engineering and operational cost of shipping."
            ),
            threshold=0.05,
            direction="greater",
        )
    )

    guardrail_bounce_rate_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="guardrail_bounce_rate_rule",
            description=(
                "The variant bounce rate must not exceed the control bounce rate by more "
                "than the guardrail tolerance (relative degradation)."
            ),
            threshold=0.02,
            direction="less",
        )
    )

    srm_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="srm_rule",
            description=(
                "No Sample Ratio Mismatch must be detected. An SRM indicates the traffic "
                "split is not as expected, which invalidates the experiment."
            ),
            threshold=0.0,
            direction="less",  # actual_value is 1.0 if SRM, 0.0 if not; must be < 0.5
        )
    )

    sample_size_rule: DecisionRule = field(
        default_factory=lambda: DecisionRule(
            name="sample_size_rule",
            description=(
                "The current sample size must reach the pre-calculated required sample size "
                "to ensure the experiment has run long enough to be conclusive."
            ),
            threshold=1.0,
            direction="greater",  # ratio = current_n / required_n must be >= 1.0
        )
    )

    def with_alpha(self, alpha: float) -> "DecisionRuleSet":
        """
        Return a new DecisionRuleSet with the significance threshold updated.

        Args:
            alpha: The new significance level (e.g. 0.01, 0.05, 0.10).

        Returns:
            A new DecisionRuleSet instance with the updated significance_rule.
        """
        return DecisionRuleSet(
            significance_rule=DecisionRule(
                name=self.significance_rule.name,
                description=self.significance_rule.description,
                threshold=alpha,
                direction=self.significance_rule.direction,
            ),
            power_rule=self.power_rule,
            practical_uplift_rule=self.practical_uplift_rule,
            guardrail_bounce_rate_rule=self.guardrail_bounce_rate_rule,
            srm_rule=self.srm_rule,
            sample_size_rule=self.sample_size_rule,
        )

    def with_min_practical_uplift(self, min_uplift: float) -> "DecisionRuleSet":
        """
        Return a new DecisionRuleSet with the practical uplift threshold updated.

        Args:
            min_uplift: The new minimum relative uplift (e.g. 0.05 for 5%).

        Returns:
            A new DecisionRuleSet instance with the updated practical_uplift_rule.
        """
        return DecisionRuleSet(
            significance_rule=self.significance_rule,
            power_rule=self.power_rule,
            practical_uplift_rule=DecisionRule(
                name=self.practical_uplift_rule.name,
                description=self.practical_uplift_rule.description,
                threshold=min_uplift,
                direction=self.practical_uplift_rule.direction,
            ),
            guardrail_bounce_rate_rule=self.guardrail_bounce_rate_rule,
            srm_rule=self.srm_rule,
            sample_size_rule=self.sample_size_rule,
        )


# ---------------------------------------------------------------------------
# Rule Evaluator
# ---------------------------------------------------------------------------


class RuleEvaluator:
    """
    Applies a DecisionRuleSet to measured statistical values and returns
    a list of RuleEvaluationResult objects for the RecommendationEngine.

    All evaluation methods are stateless with respect to experiment data;
    only the rule configuration is held as instance state.

    Args:
        rule_set: The configured DecisionRuleSet to evaluate against.
    """

    def __init__(self, rule_set: DecisionRuleSet) -> None:
        """
        Initialise the evaluator with the given rule set.

        Args:
            rule_set: Configured DecisionRuleSet containing all rule thresholds.
        """
        self._rule_set = rule_set
        logger.debug(
            "RuleEvaluator initialised | alpha=%.4f | power_target=%.2f | "
            "min_uplift=%.2f | guardrail_tolerance=%.2f",
            rule_set.significance_rule.threshold,
            rule_set.power_rule.threshold,
            rule_set.practical_uplift_rule.threshold,
            rule_set.guardrail_bounce_rate_rule.threshold,
        )

    # ------------------------------------------------------------------
    # Individual rule evaluations
    # ------------------------------------------------------------------

    def evaluate_significance(self, p_value: float) -> RuleEvaluationResult:
        """
        Evaluate whether the p-value meets the significance threshold.

        Args:
            p_value: The observed p-value from the hypothesis test (0 ≤ p ≤ 1).

        Returns:
            RuleEvaluationResult indicating pass/fail with a descriptive message.
        """
        rule = self._rule_set.significance_rule
        passed = p_value < rule.threshold
        if passed:
            message = (
                f"Statistically significant: p={p_value:.4f} < α={rule.threshold:.4f}."
            )
        else:
            message = (
                f"Not statistically significant: p={p_value:.4f} ≥ α={rule.threshold:.4f}. "
                f"Cannot reject the null hypothesis."
            )
        logger.debug("Significance rule: passed=%s | p=%.4f | alpha=%.4f", passed, p_value, rule.threshold)
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=p_value,
            threshold=rule.threshold,
            message=message,
        )

    def evaluate_power(self, achieved_power: float) -> RuleEvaluationResult:
        """
        Evaluate whether achieved statistical power meets the target.

        Args:
            achieved_power: Empirically computed or estimated power (0 ≤ power ≤ 1).

        Returns:
            RuleEvaluationResult indicating pass/fail with a descriptive message.
        """
        rule = self._rule_set.power_rule
        passed = achieved_power >= rule.threshold
        if passed:
            message = (
                f"Adequate power: achieved power={achieved_power:.2%} ≥ "
                f"target={rule.threshold:.2%}."
            )
        else:
            message = (
                f"Insufficient power: achieved power={achieved_power:.2%} < "
                f"target={rule.threshold:.2%}. More data needed."
            )
        logger.debug("Power rule: passed=%s | power=%.4f | target=%.4f", passed, achieved_power, rule.threshold)
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=achieved_power,
            threshold=rule.threshold,
            message=message,
        )

    def evaluate_practical_uplift(self, relative_lift: float) -> RuleEvaluationResult:
        """
        Evaluate whether the observed relative conversion lift is practically meaningful.

        Args:
            relative_lift: Relative lift = (variant_rate - control_rate) / control_rate.
                Can be negative for a regression.

        Returns:
            RuleEvaluationResult indicating pass/fail with a descriptive message.
        """
        rule = self._rule_set.practical_uplift_rule
        passed = relative_lift >= rule.threshold
        pct = relative_lift * 100
        threshold_pct = rule.threshold * 100
        if passed:
            message = (
                f"Practical significance met: relative lift={pct:.2f}% ≥ "
                f"minimum={threshold_pct:.2f}%."
            )
        else:
            message = (
                f"Practical significance not met: relative lift={pct:.2f}% < "
                f"minimum={threshold_pct:.2f}%. Effect may not justify rollout."
            )
        logger.debug("Practical uplift rule: passed=%s | lift=%.4f | min=%.4f", passed, relative_lift, rule.threshold)
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=relative_lift,
            threshold=rule.threshold,
            message=message,
        )

    def evaluate_guardrail_bounce_rate(
        self, control_rate: float, variant_rate: float
    ) -> RuleEvaluationResult:
        """
        Evaluate whether the variant bounce rate degrades beyond the guardrail tolerance.

        The degradation is computed as the relative increase in bounce rate:
            degradation = (variant_rate - control_rate) / control_rate

        If control_rate is 0 (undefined), the rule is treated as passed.

        Args:
            control_rate: Bounce rate for the control group (0 ≤ rate ≤ 1).
            variant_rate: Bounce rate for the variant group (0 ≤ rate ≤ 1).

        Returns:
            RuleEvaluationResult indicating pass/fail with a descriptive message.
        """
        rule = self._rule_set.guardrail_bounce_rate_rule

        if control_rate == 0.0:
            logger.warning("Guardrail evaluation: control bounce rate is 0, skipping.")
            return RuleEvaluationResult(
                rule_name=rule.name,
                passed=True,
                actual_value=0.0,
                threshold=rule.threshold,
                message="Guardrail not evaluated: control bounce rate is zero.",
            )

        relative_degradation = (variant_rate - control_rate) / control_rate
        passed = relative_degradation <= rule.threshold
        deg_pct = relative_degradation * 100
        threshold_pct = rule.threshold * 100

        if passed:
            message = (
                f"Bounce rate guardrail OK: relative degradation={deg_pct:.2f}% ≤ "
                f"tolerance={threshold_pct:.2f}%. "
                f"(Control={control_rate:.4f}, Variant={variant_rate:.4f})"
            )
        else:
            message = (
                f"Bounce rate guardrail BREACHED: relative degradation={deg_pct:.2f}% > "
                f"tolerance={threshold_pct:.2f}%. "
                f"(Control={control_rate:.4f}, Variant={variant_rate:.4f})"
            )
        logger.debug(
            "Bounce rate guardrail: passed=%s | degradation=%.4f | tolerance=%.4f",
            passed, relative_degradation, rule.threshold,
        )
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=relative_degradation,
            threshold=rule.threshold,
            message=message,
        )

    def evaluate_srm(self, srm_detected: bool) -> RuleEvaluationResult:
        """
        Evaluate whether a Sample Ratio Mismatch (SRM) was detected.

        An SRM invalidates the experiment regardless of statistical results.

        Args:
            srm_detected: True if the chi-squared SRM test flagged a mismatch.

        Returns:
            RuleEvaluationResult with actual_value=1.0 if SRM detected, 0.0 otherwise.
        """
        rule = self._rule_set.srm_rule
        # Pass = no SRM detected
        passed = not srm_detected
        actual_value = 1.0 if srm_detected else 0.0

        if passed:
            message = (
                "No Sample Ratio Mismatch detected. Traffic allocation is consistent "
                "with the intended split."
            )
        else:
            message = (
                "CRITICAL: Sample Ratio Mismatch detected! The observed traffic split "
                "differs significantly from the intended allocation. Statistical results "
                "are unreliable and must not be used to make decisions."
            )
        logger.debug("SRM rule: passed=%s | srm_detected=%s", passed, srm_detected)
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=actual_value,
            threshold=rule.threshold,
            message=message,
        )

    def evaluate_sample_size(self, current_n: int, required_n: int) -> RuleEvaluationResult:
        """
        Evaluate whether the experiment has accumulated sufficient sample size.

        The ratio current_n / required_n is compared against the threshold of 1.0.

        Args:
            current_n: Total number of users enrolled in the experiment so far.
            required_n: Pre-calculated minimum required sample size (per arm × 2).

        Returns:
            RuleEvaluationResult with actual_value = current_n / required_n.
        """
        rule = self._rule_set.sample_size_rule

        if required_n <= 0:
            logger.warning("Sample size rule: required_n=%d is invalid, treating as passed.", required_n)
            return RuleEvaluationResult(
                rule_name=rule.name,
                passed=True,
                actual_value=1.0,
                threshold=rule.threshold,
                message="Sample size check skipped: required sample size is not defined.",
            )

        ratio = current_n / required_n
        passed = ratio >= rule.threshold  # threshold = 1.0

        if passed:
            message = (
                f"Minimum sample size reached: {current_n:,} enrolled ≥ {required_n:,} required "
                f"({ratio:.2%} of target)."
            )
        else:
            remaining = required_n - current_n
            message = (
                f"Minimum sample size NOT reached: {current_n:,} enrolled < {required_n:,} required "
                f"({ratio:.2%} of target). Approximately {remaining:,} more users needed."
            )
        logger.debug(
            "Sample size rule: passed=%s | current=%d | required=%d | ratio=%.4f",
            passed, current_n, required_n, ratio,
        )
        return RuleEvaluationResult(
            rule_name=rule.name,
            passed=passed,
            actual_value=ratio,
            threshold=rule.threshold,
            message=message,
        )

    # ------------------------------------------------------------------
    # Aggregate evaluation
    # ------------------------------------------------------------------

    def evaluate_all(self, evaluation_inputs: dict) -> list[RuleEvaluationResult]:
        """
        Run all six rules against a dictionary of evaluation inputs and return
        a list of RuleEvaluationResult objects in deterministic order.

        Expected keys in evaluation_inputs:
            p_value (float): Observed p-value from hypothesis test.
            achieved_power (float): Achieved statistical power (0–1).
            relative_lift (float): Relative conversion rate lift (can be negative).
            control_bounce_rate (float): Control group bounce rate (0–1).
            variant_bounce_rate (float): Variant group bounce rate (0–1).
            srm_detected (bool): Whether an SRM was flagged.
            current_n (int): Current total enrolled users.
            required_n (int): Pre-calculated required sample size.

        Args:
            evaluation_inputs: Dictionary of measured values keyed as above.

        Returns:
            List of RuleEvaluationResult, one per rule, in the following order:
            [srm, significance, power, practical_uplift, guardrail_bounce_rate, sample_size]

        Raises:
            KeyError: If a required key is missing from evaluation_inputs.
        """
        logger.info("Running full rule evaluation suite")

        results: list[RuleEvaluationResult] = []

        try:
            # SRM is always checked first — it invalidates everything else
            results.append(self.evaluate_srm(evaluation_inputs["srm_detected"]))

            results.append(self.evaluate_significance(evaluation_inputs["p_value"]))

            results.append(self.evaluate_power(evaluation_inputs["achieved_power"]))

            results.append(
                self.evaluate_practical_uplift(evaluation_inputs["relative_lift"])
            )

            results.append(
                self.evaluate_guardrail_bounce_rate(
                    control_rate=evaluation_inputs["control_bounce_rate"],
                    variant_rate=evaluation_inputs["variant_bounce_rate"],
                )
            )

            results.append(
                self.evaluate_sample_size(
                    current_n=int(evaluation_inputs["current_n"]),
                    required_n=int(evaluation_inputs["required_n"]),
                )
            )

        except KeyError as exc:
            logger.error("evaluate_all: missing required key %s in evaluation_inputs", exc)
            raise

        passed_count = sum(1 for r in results if r.passed)
        logger.info(
            "Rule evaluation complete: %d/%d rules passed",
            passed_count, len(results),
        )
        return results
