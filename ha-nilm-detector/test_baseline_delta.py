#!/usr/bin/env python3

import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(__file__))

from app.storage.sqlite_store import SQLiteStore


def test_baseline_interpolation_produces_clean_delta_curve():
    start = datetime(2026, 4, 5, 10, 0, 0)
    duration_s = 20.0

    # Baseline ramps from 100W to 120W across the event window.
    # Device adds ~80W in the middle region.
    profile = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 100.0},
        {"t_s": 4.0, "t_norm": 0.2, "power_w": 104.0},
        {"t_s": 8.0, "t_norm": 0.4, "power_w": 188.0},
        {"t_s": 12.0, "t_norm": 0.6, "power_w": 192.0},
        {"t_s": 16.0, "t_norm": 0.8, "power_w": 116.0},
        {"t_s": 20.0, "t_norm": 1.0, "power_w": 120.0},
    ]

    cycle = {
        "start_ts": start.isoformat(),
        "end_ts": (start + timedelta(seconds=duration_s)).isoformat(),
        "duration_s": duration_s,
        "avg_power_w": 153.0,
        "peak_power_w": 192.0,
        "energy_wh": 0.85,
        "phase": "L1",
        "phase_mode": "single_phase",
        "profile_points": profile,
    }

    enriched = SQLiteStore._augment_cycle_baseline_delta(cycle)
    delta = enriched.get("delta_profile_points") or []

    assert len(delta) == len(profile)
    assert abs(float(delta[0]["power_w"])) < 5.0
    assert abs(float(delta[-1]["power_w"])) < 5.0

    # Middle should still show the device signature clearly above baseline.
    mid_peak = max(float(p["power_w"]) for p in delta)
    assert mid_peak > 60.0
    assert float(enriched.get("delta_peak_power_w", 0.0)) > 60.0
