#!/usr/bin/env python3

import os
import sys
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

sys.path.append(os.path.dirname(__file__))

from app.storage.sqlite_store import SQLiteStore


def _build_cycle(start: datetime, avg_power: float = 180.0, peak_power: float = 280.0, duration_s: float = 50.0) -> dict:
    profile = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 95.0},
        {"t_s": 3.0, "t_norm": 3.0 / duration_s, "power_w": peak_power},
        {"t_s": 12.0, "t_norm": 12.0 / duration_s, "power_w": avg_power + 20.0},
        {"t_s": 35.0, "t_norm": 35.0 / duration_s, "power_w": avg_power},
        {"t_s": duration_s, "t_norm": 1.0, "power_w": 98.0},
    ]
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
        "power_variance": 900.0,
        "rise_rate_w_per_s": 70.0,
        "fall_rate_w_per_s": 40.0,
        "duty_cycle": 0.7,
        "peak_to_avg_ratio": peak_power / max(avg_power, 1.0),
        "num_substates": 2,
        "step_count": 2,
        "has_motor_pattern": True,
        "has_heating_pattern": False,
        "profile_points": profile,
    }


def test_shared_pattern_pack_redacts_custom_labels_and_readings():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True
            t0 = datetime(2026, 4, 6, 14, 0, 0)
            learned = store.learn_cycle_pattern(_build_cycle(t0), suggestion_type="fridge")
            pattern = dict(learned.get("pattern") or {})
            pattern_id = int(pattern.get("id", 0) or 0)
            assert pattern_id > 0
            assert store.label_pattern(pattern_id, "kitchen fridge") is True

            exported = store.export_shared_pattern_pack(limit=50, confirmed_only=True)
            assert exported.get("format") == "ha_nilm_shared_pattern_pack_v1"
            patterns = list(exported.get("patterns") or [])
            assert len(patterns) == 1
            first = patterns[0]
            assert first.get("public_label") == "fridge"
            assert "readings" not in first
            assert "user_label" not in first
        finally:
            store.close()


def test_llm_review_bundle_contains_compact_review_data():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True
            t0 = datetime(2026, 4, 6, 15, 0, 0)
            store.learn_cycle_pattern(_build_cycle(t0), suggestion_type="fridge")

            bundle = store.export_llm_review_bundle(pattern_limit=20, event_limit=20)
            assert bundle.get("format") == "ha_nilm_llm_review_bundle_v1"
            assert isinstance(bundle.get("patterns"), list)
            assert isinstance(bundle.get("events"), list)
            assert isinstance(bundle.get("classification_log"), list)
            assert isinstance(bundle.get("training_log"), list)
            if bundle["patterns"]:
                assert "shape_signature" in bundle["patterns"][0]
        finally:
            store.close()