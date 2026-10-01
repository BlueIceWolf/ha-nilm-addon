from app.learning.feature_vector_v2 import build_feature_vector_v2
from app.learning.learning_filter_v2 import LearningFilterV2
from app.learning.drift_monitor import DriftMonitor
from app.learning.ensemble import EnsembleClassifier


def test_feature_vector_v2_has_stable_size():
    row = {
        "avg_power_w": 140,
        "peak_power_w": 420,
        "duration_s": 300,
        "energy_wh": 12,
        "phase": "L1",
        "derived_features": {
            "inrush_ratio": 3.0,
            "normalized_variance": 0.2,
            "shape_peak_position": 0.1,
        },
    }
    vec = build_feature_vector_v2(row)
    assert len(vec) == 24
    assert all(isinstance(v, float) for v in vec)


def test_learning_filter_blocks_truncated_overlap_event():
    decision = LearningFilterV2().evaluate({
        "avg_power_w": 250,
        "duration_s": 60,
        "sample_count": 3,
        "segmentation_confidence": 0.2,
        "waveform_completeness_score": 0.2,
        "baseline_quality_score": 0.2,
        "overlap_score": 0.8,
        "truncated_start": True,
        "truncated_end": True,
    })
    assert decision.accepted is False
    assert decision.tier == "blocked"
    assert "probable_multi_device_overlap" in decision.reasons


def test_learning_filter_accepts_clean_event():
    decision = LearningFilterV2().evaluate({
        "avg_power_w": 150,
        "duration_s": 300,
        "sample_count": 30,
        "segmentation_confidence": 0.9,
        "waveform_completeness_score": 0.9,
        "baseline_quality_score": 0.9,
        "overlap_score": 0.0,
    })
    assert decision.accepted is True
    assert decision.tier == "stable"


def test_drift_monitor_detects_large_profile_change():
    monitor = DriftMonitor()
    pattern = {
        "avg_power_w": 120,
        "peak_power_w": 350,
        "duration_s": 240,
        "energy_wh": 8,
        "phase": "L1",
    }
    changed = {
        "avg_power_w": 520,
        "peak_power_w": 1800,
        "duration_s": 900,
        "energy_wh": 130,
        "phase": "L1",
        "num_substates": 5,
        "step_count": 12,
    }
    result = monitor.compare(pattern, changed)
    assert result.score > 0.18
    assert result.level in {"warning", "critical"}
    assert result.changed_features


def test_ensemble_rewards_multi_model_agreement():
    result = EnsembleClassifier().combine({
        "prototype": ("fridge", 0.9),
        "shape": ("fridge", 0.85),
        "ml": ("fridge", 0.8),
        "attention": ("fridge", 0.82),
        "temporal": ("fridge", 0.7),
        "rule": ("pump", 0.3),
    })
    assert result is not None
    assert result.label == "fridge"
    assert result.confidence > 0.7
    assert result.ranking[0][0] == "fridge"
