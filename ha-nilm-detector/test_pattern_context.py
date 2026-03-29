#!/usr/bin/env python3

import os
import sys
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

sys.path.append(os.path.dirname(__file__))

from app.storage.sqlite_store import SQLiteStore


def _build_cycle(start: datetime) -> dict:
    duration_s = 20.0
    profile = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 90.0},
        {"t_s": 2.0, "t_norm": 2.0 / duration_s, "power_w": 260.0},
        {"t_s": 7.0, "t_norm": 7.0 / duration_s, "power_w": 210.0},
        {"t_s": 15.0, "t_norm": 15.0 / duration_s, "power_w": 195.0},
        {"t_s": 20.0, "t_norm": 1.0, "power_w": 95.0},
    ]
    avg_power = sum(p["power_w"] for p in profile) / len(profile)
    peak_power = max(p["power_w"] for p in profile)
    return {
        "start_ts": start.isoformat(),
        "end_ts": (start + timedelta(seconds=duration_s)).isoformat(),
        "duration_s": duration_s,
        "avg_power_w": avg_power,
        "peak_power_w": peak_power,
        "energy_wh": avg_power * duration_s / 3600.0,
        "phase": "L1",
        "phase_mode": "single_phase",
        "active_phase_count": 1.0,
        "power_variance": 1200.0,
        "rise_rate_w_per_s": 80.0,
        "fall_rate_w_per_s": 55.0,
        "duty_cycle": 0.7,
        "peak_to_avg_ratio": peak_power / max(avg_power, 1.0),
        "num_substates": 2,
        "step_count": 2,
        "has_motor_pattern": True,
        "has_heating_pattern": False,
        "profile_points": profile,
    }


def test_pattern_context_contains_window_markers_and_samples():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True
            start = datetime(2026, 3, 29, 12, 30, 10)

            learn = store.learn_cycle_pattern(_build_cycle(start), suggestion_type="fridge")
            pattern = learn.get("pattern") or {}
            pattern_id = int(pattern.get("id") or 0)
            assert pattern_id > 0

            assert store._conn is not None
            conn = store._conn
            rows = []
            for idx in range(-3, 26):
                ts = start + timedelta(seconds=idx)
                power = 95.0 if idx < 0 or idx > 20 else (160.0 + (idx * 3.0))
                rows.append((ts.isoformat(), power, "L1", "{}"))

            with conn:
                conn.executemany(
                    "INSERT INTO power_readings (ts, power_w, phase, metadata) VALUES (?, ?, ?, ?)",
                    rows,
                )

            context = store.get_pattern_context(pattern_id=pattern_id, pre_seconds=2, post_seconds=2)
            assert context.get("ok") is True
            assert int(context.get("pattern_id") or 0) == pattern_id
            assert int(context.get("event_id") or 0) > 0
            assert int(context.get("event_start_offset_ms") or 0) >= 1500
            assert int(context.get("event_end_offset_ms") or 0) > int(context.get("event_start_offset_ms") or 0)

            samples = context.get("samples") or []
            assert isinstance(samples, list)
            assert len(samples) > 0

            baseline = context.get("baseline") or []
            assert isinstance(baseline, list)
            assert len(baseline) >= 2
        finally:
            store.close()
