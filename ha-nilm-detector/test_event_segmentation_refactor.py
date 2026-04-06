#!/usr/bin/env python3

from datetime import datetime, timedelta

from app.learning.pattern_learner import PatternLearner
from app.models import PowerReading


def _reading(ts: datetime, power: float) -> PowerReading:
    return PowerReading(timestamp=ts, power_w=power, phase="L1")


def _run_sequence(powers, *, start=None, learner=None):
    learner = learner or PatternLearner(
        min_cycle_seconds=5.0,
        adaptive_on_offset_w=35.0,
        adaptive_off_offset_w=12.0,
        derivative_threshold_w_per_s=90.0,
        end_hold_s=3.0,
        pre_roll_seconds=2.0,
        post_roll_seconds=2.0,
        stabilization_grace_s=2.0,
        debounce_samples=1,
        noise_filter_window=1,
    )
    start = start or datetime(2026, 4, 6, 12, 0, 0)
    completed = []
    for idx, power in enumerate(powers):
        maybe = learner.ingest(_reading(start + timedelta(seconds=idx), power))
        if maybe is not None:
            completed.append(maybe)
    return completed


def test_clean_motor_start_captures_full_cycle_with_inrush():
    learner = PatternLearner(
        min_cycle_seconds=5.0,
        adaptive_on_offset_w=30.0,
        adaptive_off_offset_w=10.0,
        derivative_threshold_w_per_s=80.0,
        end_hold_s=3.0,
        pre_roll_seconds=2.0,
        post_roll_seconds=2.0,
        stabilization_grace_s=2.0,
        debounce_samples=1,
        noise_filter_window=1,
    )
    powers = [45.0, 46.0, 44.0, 45.0, 46.0, 250.0] + [165.0] * 12 + [70.0, 48.0, 46.0, 45.0, 45.0, 45.0, 45.0, 45.0]
    completed = _run_sequence(powers, learner=learner)

    assert len(completed) == 1
    cycle = completed[0]
    assert cycle.peak_power_w >= 240.0
    assert cycle.duration_s >= 12.0
    assert cycle.truncated_start is False
    assert cycle.truncated_end is False
    assert len(cycle.pre_roll_samples) >= 2
    assert len(cycle.post_roll_samples) >= 2
    assert len(cycle.waveform_points) > len(cycle.profile_points)
    assert cycle.segmentation_flags.get("event_start_reason") in {"derivative_spike", "delta_threshold"}
    assert cycle.segmentation_flags.get("event_end_reason") == "stable_near_baseline"


def test_compressor_cycle_keeps_ramp_and_shutdown_without_truncation():
    powers = [60.0, 60.0, 61.0, 59.0, 60.0, 95.0, 145.0, 185.0] + [178.0] * 10 + [150.0, 120.0, 85.0, 68.0, 64.0, 62.0, 60.0, 60.0, 60.0, 60.0]
    completed = _run_sequence(powers)

    assert len(completed) == 1
    cycle = completed[0]
    assert cycle.truncated_start is False
    assert cycle.truncated_end is False
    assert cycle.duration_s >= 14.0
    assert cycle.event_samples[0].power_w <= 100.0
    assert cycle.event_samples[-1].power_w <= 70.0
    assert cycle.segmentation_flags.get("event_end_reason") == "stable_near_baseline"


def test_short_spike_does_not_create_false_long_event():
    powers = [50.0, 49.0, 50.0, 51.0, 50.0, 240.0, 52.0, 51.0, 50.0, 49.0, 50.0, 50.0]
    completed = _run_sequence(powers)

    assert completed == []


def test_noisy_signal_does_not_flicker_or_split_single_event():
    powers = [80.0, 83.0, 78.0, 84.0, 79.0, 82.0, 210.0] + [155.0] * 4 + [88.0] + [154.0] * 4 + [84.0, 82.0, 81.0, 80.0, 80.0, 80.0, 80.0]
    completed = _run_sequence(powers)

    assert len(completed) == 1
    cycle = completed[0]
    assert cycle.duration_s >= 9.0
    assert cycle.truncated_end is False


def test_multi_stage_load_is_not_split_into_multiple_events():
    powers = [40.0, 41.0, 39.0, 40.0, 40.0] + [220.0] * 4 + [430.0] * 4 + [260.0] * 4 + [55.0, 42.0, 40.0, 40.0, 40.0, 40.0, 40.0]
    completed = _run_sequence(powers)

    assert len(completed) == 1
    cycle = completed[0]
    assert cycle.duration_s >= 11.0
    assert cycle.peak_power_w >= 420.0
    assert cycle.truncated_start is False
    assert cycle.truncated_end is False