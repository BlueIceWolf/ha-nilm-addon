#!/usr/bin/env python3

from app.learning.classification_pipeline import enrich_cycle_for_classification, infer_unknown_subclass, score_shape_match


def _profile(points):
    total = max(len(points) - 1, 1)
    return [
        {"t_s": float(idx), "t_norm": idx / total, "power_w": float(power)}
        for idx, power in enumerate(points)
    ]


def test_unknown_bucket_refinement_avoids_broad_unknown_electronics():
    cycle = {
        "phase": "L1",
        "avg_power_w": 120.0,
        "peak_power_w": 310.0,
        "duration_s": 12.0,
        "power_variance": 900.0,
        "rise_rate_w_per_s": 140.0,
        "fall_rate_w_per_s": 90.0,
        "num_substates": 1,
        "step_count": 1,
        "has_motor_pattern": True,
        "profile_points": _profile([10, 310, 160, 110, 15]),
    }

    label, reasons = infer_unknown_subclass(enrich_cycle_for_classification(cycle, [], fallback="unknown"))

    assert label in {"unknown_motor", "unknown_high_inrush", "unknown_short_pulse"}
    assert isinstance(reasons, list)


def test_shape_matching_groups_stretched_cycles_by_shape():
    pattern = {
        "id": 9,
        "phase": "L1",
        "suggestion_type": "compressor_small",
        "profile_points": _profile([20, 260, 180, 175, 170, 25]),
        "shape_signature": "[0.08, 1.0, 0.7, 0.68, 0.65, 0.09]",
        "duration_s": 120.0,
        "avg_power_w": 170.0,
    }
    candidate = {
        "phase": "L1",
        "avg_power_w": 168.0,
        "peak_power_w": 255.0,
        "duration_s": 150.0,
        "profile_points": _profile([18, 250, 190, 178, 172, 171, 28]),
    }

    match = score_shape_match(candidate, [pattern])

    assert match.label == "compressor_small"
    assert match.score >= 0.7
    assert match.dtw >= 0.7


def test_high_inrush_motor_prefers_motor_or_compressor_candidate_over_generic_pump():
    cycle = {
        "phase": "L1",
        "avg_power_w": 420.0,
        "peak_power_w": 1250.0,
        "duration_s": 35.0,
        "power_variance": 2600.0,
        "rise_rate_w_per_s": 450.0,
        "fall_rate_w_per_s": 180.0,
        "peak_to_avg_ratio": 1250.0 / 420.0,
        "num_substates": 1,
        "step_count": 1,
        "has_motor_pattern": True,
        "profile_points": _profile([25, 1250, 520, 430, 390, 30]),
    }

    enriched = enrich_cycle_for_classification(cycle, [], fallback="unknown")

    assert enriched["refined_label"] in {"compressor_candidate", "small_pump_motor", "large_pump_motor", "unknown_high_inrush"}
    assert float(enriched["shape_confidence"]) >= 0.0
    assert float(enriched["final_confidence"]) >= 0.35