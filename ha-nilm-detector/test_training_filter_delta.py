from app.core.training_filter import is_valid_training_event
from app.learning.learning_filter_v2 import LearningFilterV2


def _event(**overrides):
    event = {
        "avg_power_w": 120.0,
        "delta_avg_power_w": 80.0,
        "duration_s": 120.0,
        "quality_score": 0.9,
        "sample_count": 20,
        "segmentation_confidence": 0.9,
        "waveform_completeness_score": 0.9,
        "baseline_quality_score": 0.9,
        "overlap_score": 0.0,
    }
    event.update(overrides)
    return event


def test_training_filter_rejects_negative_delta_even_with_high_total_power():
    accepted, reason = is_valid_training_event(
        _event(avg_power_w=180.0, delta_avg_power_w=-15.0)
    )
    assert accepted is False
    assert reason == "non_positive_delta_power"


def test_training_filter_uses_positive_delta_when_available():
    accepted, reason = is_valid_training_event(
        _event(avg_power_w=180.0, delta_avg_power_w=45.0)
    )
    assert accepted is True
    assert reason is None


def test_learning_filter_blocks_negative_delta():
    decision = LearningFilterV2().evaluate(
        _event(avg_power_w=180.0, delta_avg_power_w=-12.0)
    )
    assert decision.accepted is False
    assert decision.tier == "blocked"
    assert "non_positive_delta_power" in decision.reasons
