#!/usr/bin/env python3

from datetime import datetime, timedelta

from app.learning.event_detection import AdaptiveEventDetector, EventDetectionConfig
from app.learning.pattern_learner import PatternLearner
from app.models import PowerReading


def _reading(ts: datetime, power: float) -> PowerReading:
    return PowerReading(timestamp=ts, power_w=power, phase="L1")


def test_event_detector_requires_hold_time_below_baseline():
    detector = AdaptiveEventDetector(
        EventDetectionConfig(
            delta_on_w=30.0,
            delta_off_w=10.0,
            debounce_samples=1,
            end_hold_s=4.0,
            stabilization_grace_s=0.0,
        )
    )
    start = datetime(2026, 4, 6, 10, 0, 0)
    baseline = 50.0

    assert detector.ingest(start, 95.0, baseline).started is True
    assert detector.is_on is True
    assert detector.ingest(start + timedelta(seconds=1), 55.0, baseline).ended is False
    assert detector.ingest(start + timedelta(seconds=3), 54.0, baseline).ended is False
    assert detector.ingest(start + timedelta(seconds=5), 53.0, baseline).ended is True


def test_pattern_learner_captures_pre_and_post_roll_for_full_cycle():
    learner = PatternLearner(
        min_cycle_seconds=5.0,
        adaptive_on_offset_w=25.0,
        adaptive_off_offset_w=10.0,
        end_hold_s=3.0,
        pre_roll_seconds=2.0,
        post_roll_seconds=2.0,
        stabilization_grace_s=2.0,
    )
    start = datetime(2026, 4, 6, 12, 0, 0)
    readings = []

    for idx in range(3):
        readings.append(_reading(start + timedelta(seconds=idx), 50.0))
    readings.append(_reading(start + timedelta(seconds=3), 210.0))
    for idx in range(4, 20):
        readings.append(_reading(start + timedelta(seconds=idx), 155.0))
    for idx in range(20, 31):
        readings.append(_reading(start + timedelta(seconds=idx), 52.0))

    completed = None
    for item in readings:
        maybe = learner.ingest(item)
        if maybe is not None:
            completed = maybe

    assert completed is not None
    assert completed.duration_s >= 15.0
    assert completed.truncated_start is False
    assert completed.truncated_end is False
    assert len(completed.pre_roll_samples) >= 2
    assert len(completed.post_roll_samples) >= 2
    assert len(completed.waveform_points) > len(completed.profile_points)
    assert completed.segmentation_flags.get("event_start_reason") == "delta_crossed_start_threshold"