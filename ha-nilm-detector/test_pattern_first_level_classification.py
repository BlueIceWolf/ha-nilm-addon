#!/usr/bin/env python3

from datetime import datetime, timedelta

from app.learning.features import CycleFeatures
from app.learning.pattern_learner import LearnedCycle, PatternLearner


def _features(**overrides) -> CycleFeatures:
    base = {
        "avg_power_w": 1000.0,
        "peak_power_w": 1200.0,
        "duration_s": 120.0,
        "energy_wh": 35.0,
        "power_variance": 4000.0,
        "rise_rate_w_per_s": 30.0,
        "fall_rate_w_per_s": 25.0,
        "duty_cycle": 0.8,
        "peak_to_avg_ratio": 1.2,
        "power_std_dev": 63.0,
        "num_substates": 1,
        "substates": [(1000.0, 120.0)],
        "step_count": 1,
        "has_heating_pattern": False,
        "has_motor_pattern": False,
    }
    base.update(overrides)
    return CycleFeatures(**base)


def _cycle(avg_power_w: float, peak_power_w: float, duration_s: float, features: CycleFeatures) -> LearnedCycle:
    start = datetime(2026, 4, 6, 12, 0, 0)
    return LearnedCycle(
        start_ts=start,
        end_ts=start + timedelta(seconds=duration_s),
        duration_s=duration_s,
        avg_power_w=avg_power_w,
        peak_power_w=peak_power_w,
        energy_wh=(avg_power_w * duration_s) / 3600.0,
        sample_count=20,
        features=features,
    )


def test_first_level_classifies_distinct_kettle_signature():
    cycle = _cycle(
        avg_power_w=2100.0,
        peak_power_w=2300.0,
        duration_s=180.0,
        features=_features(
            avg_power_w=2100.0,
            peak_power_w=2300.0,
            duration_s=180.0,
            energy_wh=105.0,
            power_variance=18000.0,
            rise_rate_w_per_s=180.0,
            has_heating_pattern=True,
        ),
    )

    label, reason = PatternLearner._suggest_device_type_first_level(cycle)

    assert label == "kettle"
    assert reason == "distinct_heating_fast_rise_short_cycle"


def test_first_level_classifies_distinct_fridge_signature():
    cycle = _cycle(
        avg_power_w=165.0,
        peak_power_w=250.0,
        duration_s=900.0,
        features=_features(
            avg_power_w=165.0,
            peak_power_w=250.0,
            duration_s=900.0,
            energy_wh=41.25,
            power_variance=1600.0,
            duty_cycle=0.56,
            has_motor_pattern=True,
        ),
    )

    label, reason = PatternLearner._suggest_device_type_first_level(cycle)

    assert label == "fridge"
    assert reason == "distinct_low_power_motor_cycle"


def test_first_level_keeps_ambiguous_high_power_cycle_unknown():
    cycle = _cycle(
        avg_power_w=2200.0,
        peak_power_w=2400.0,
        duration_s=1800.0,
        features=_features(
            avg_power_w=2200.0,
            peak_power_w=2400.0,
            duration_s=1800.0,
            energy_wh=1100.0,
            power_variance=140000.0,
            has_heating_pattern=False,
            has_motor_pattern=False,
            num_substates=1,
            peak_to_avg_ratio=1.09,
        ),
    )

    label, reason = PatternLearner._suggest_device_type_first_level(cycle)

    assert label == "unknown"
    assert reason == "no_rule_matched"