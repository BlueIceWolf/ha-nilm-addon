from app.learning.attention_classifier import LocalAttentionClassifier
from app.learning.local_llm import LocalLLMClassifier


def _pattern(label, avg, peak, duration, phase="L1", seen=5):
    return {
        "user_label": label,
        "avg_power_w": avg,
        "peak_power_w": peak,
        "duration_s": duration,
        "energy_wh": avg * duration / 3600.0,
        "phase": phase,
        "seen_count": seen,
    }


def test_attention_prefers_similar_learned_pattern():
    classifier = LocalAttentionClassifier()
    cycle = {
        "avg_power_w": 145.0,
        "peak_power_w": 430.0,
        "duration_s": 290.0,
        "energy_wh": 11.7,
        "phase": "L1",
        "derived_features": {
            "inrush_ratio": 2.96,
            "normalized_variance": 1.1,
        },
    }
    patterns = [
        _pattern("fridge", 140.0, 420.0, 300.0, seen=12),
        _pattern("heater", 1800.0, 1820.0, 600.0, seen=8),
    ]

    result = classifier.predict(
        cycle=cycle,
        patterns=patterns,
        label_fn=lambda item: item["user_label"],
        phase="L1",
    )

    assert result is not None
    assert result.label == "fridge"
    assert 0.0 <= result.confidence <= 1.0
    assert result.top_n[0][0] == "fridge"


def test_attention_respects_phase():
    classifier = LocalAttentionClassifier()
    cycle = {
        "avg_power_w": 150.0,
        "peak_power_w": 400.0,
        "duration_s": 300.0,
        "phase": "L2",
    }
    patterns = [
        _pattern("wrong_phase", 150.0, 400.0, 300.0, phase="L1"),
        _pattern("right_phase", 155.0, 410.0, 305.0, phase="L2"),
    ]

    result = classifier.predict(
        cycle=cycle,
        patterns=patterns,
        label_fn=lambda item: item["user_label"],
        phase="L2",
    )

    assert result is not None
    assert result.label == "right_phase"


def test_compatibility_reviewer_needs_no_endpoint():
    reviewer = LocalLLMClassifier(enabled=True)

    assert reviewer.ready is True
    assert reviewer.should_review(current_label="unknown", current_confidence=0.2) is True
