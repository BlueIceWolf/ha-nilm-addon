#!/usr/bin/env python3

from app.learning.classification_pipeline import enrich_cycle_for_classification, infer_unknown_subclass, score_shape_match
from app.storage.sqlite_store import SQLiteStore


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

    assert label in {"motor_load", "variable_motor_load", "motor_start_candidate", "short_pulse_load"}
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
        "shape_signature": "[0.07, 0.98, 0.74, 0.69, 0.66, 0.65, 0.1]",
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

    assert enriched["refined_label"] in {"motor_start_candidate", "motor_load", "variable_motor_load", "refrigeration_candidate"}
    assert float(enriched["shape_confidence"]) >= 0.0
    assert float(enriched["final_confidence"]) >= 0.35


def test_missing_shape_signature_disables_shape_scoring():
    cycle = {
        "phase": "L1",
        "avg_power_w": 180.0,
        "peak_power_w": 260.0,
        "duration_s": 240.0,
        "waveform_points": _profile([0, 180, 190, 185, 0]),
        "shape_signature": "",
    }

    enriched = enrich_cycle_for_classification(cycle, [], fallback="unknown")

    assert enriched["shape_signature_status"] == "missing"
    assert float(enriched["shape_confidence"]) == 0.0
    assert enriched["shape_match"]["valid"] is False


def test_startup_only_compressor_event_stays_candidate_not_fridge():
    cycle = {
        "phase": "L1",
        "avg_power_w": 170.0,
        "peak_power_w": 290.0,
        "duration_s": 35.0,
        "power_variance": 1800.0,
        "rise_rate_w_per_s": 260.0,
        "fall_rate_w_per_s": 90.0,
        "has_motor_pattern": True,
        "truncated_start": True,
        "profile_points": _profile([15, 290, 220, 180, 120]),
        "pre_roll_samples": [],
        "post_roll_samples": [],
        "waveform_points": _profile([15, 290, 220, 180, 120]),
    }
    patterns = [{
        "id": 3,
        "phase": "L1",
        "suggestion_type": "fridge",
        "duration_s": 900.0,
        "avg_power_w": 165.0,
        "seen_count": 8,
        "avg_hour_of_day": 12.0,
        "shape_signature": "[0.0,0.2,1.0,0.9,0.9,0.8,0.6,0.2,0.0]",
    }]

    enriched = enrich_cycle_for_classification(cycle, patterns, fallback="unknown")

    assert enriched["refined_label"] in {"motor_start_candidate", "motor_load", "refrigeration_candidate"}
    assert "full_cycle_missing" in enriched["reason"] or "device_identity_downgraded" in enriched["reason"] or "segmentation" in enriched["reason"]


def test_full_waveform_generates_shape_signature_and_high_segmentation_confidence():
    cycle = {
        "phase": "L1",
        "avg_power_w": 420.0,
        "peak_power_w": 690.0,
        "duration_s": 240.0,
        "power_variance": 1200.0,
        "rise_rate_w_per_s": 85.0,
        "fall_rate_w_per_s": 70.0,
        "has_motor_pattern": True,
        "baseline_before_w": 45.0,
        "baseline_after_w": 44.0,
        "pre_roll_samples": _profile([44, 45, 45, 46]),
        "post_roll_samples": _profile([47, 45, 44, 44]),
        "waveform_points": _profile([44, 45, 46, 300, 690, 520, 430, 420, 410, 380, 90, 46, 44]),
        "profile_points": _profile([300, 690, 520, 430, 420, 410, 380, 90]),
        "pre_roll_duration_s": 3.0,
        "post_roll_duration_s": 3.0,
    }
    cycle["shape_signature"] = SQLiteStore._shape_signature_from_cycle(cycle)

    enriched = enrich_cycle_for_classification(cycle, [], fallback="unknown")

    assert enriched["shape_signature_status"] == "valid"
    assert enriched["shape_signature"] != ""
    assert float(enriched["segmentation_confidence"]) >= 0.7
    assert float(enriched["waveform_completeness_score"]) >= 0.7

def test_stable_low_power_motor_is_not_mislabeled_as_electronics():
    cycle = {
        "phase": "L3",
        "avg_power_w": 105.0,
        "peak_power_w": 145.0,
        "duration_s": 900.0,
        "power_variance": 500.0,
        "rise_rate_w_per_s": 70.0,
        "fall_rate_w_per_s": 45.0,
        "peak_to_avg_ratio": 1.38,
        "num_substates": 1,
        "step_count": 1,
        "has_motor_pattern": True,
        "profile_points": _profile([10, 145, 112, 106, 104, 103, 12]),
    }

    enriched = enrich_cycle_for_classification(cycle, [], fallback="unknown")

    assert enriched["refined_label"] not in {"electronics_cluster", "low_power_electronics"}
    assert enriched["refined_label"] in {"motor_load", "variable_motor_load", "refrigeration_candidate"}


def test_multistage_profile_stays_generic_without_device_specific_evidence():
    cycle = {
        "phase": "L2",
        "avg_power_w": 700.0,
        "peak_power_w": 2100.0,
        "duration_s": 3600.0,
        "power_variance": 180000.0,
        "rise_rate_w_per_s": 120.0,
        "fall_rate_w_per_s": 90.0,
        "num_substates": 3,
        "step_count": 4,
        "has_motor_pattern": False,
        "has_heating_pattern": False,
        "profile_points": _profile([20, 300, 1800, 250, 2100, 300, 20]),
    }

    enriched = enrich_cycle_for_classification(cycle, [], fallback="unknown")

    assert enriched["refined_label"] == "multistate_appliance"
