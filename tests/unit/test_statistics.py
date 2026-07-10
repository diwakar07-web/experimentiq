import pytest
from src.statistics.hypothesis_test import HypothesisTestEngine

@pytest.mark.unit
@pytest.mark.statistical
class TestHypothesisTest:

    def test_significant_result_when_large_difference(self, known_z_test_inputs):
        engine = HypothesisTestEngine(alpha=0.05)
        result = engine.run_two_proportion_z_test(**known_z_test_inputs)
        
        assert result.is_significant is True
        assert result.p_value < 0.05
        assert result.absolute_lift == 0.05
        assert result.relative_lift_pct == 50.0

    def test_not_significant_when_no_difference(self):
        engine = HypothesisTestEngine(alpha=0.05)
        result = engine.run_two_proportion_z_test(1000, 1000, 100, 100)
        
        assert result.is_significant is False
        assert result.p_value == 1.0
        assert result.z_score == 0.0

    def test_raises_on_zero_sample_size(self):
        engine = HypothesisTestEngine(alpha=0.05)
        with pytest.raises(ValueError):
            engine.run_two_proportion_z_test(0, 1000, 0, 100)

    def test_raises_on_conversions_exceeding_n(self):
        engine = HypothesisTestEngine(alpha=0.05)
        with pytest.raises(ValueError):
            engine.run_two_proportion_z_test(100, 100, 150, 50)
