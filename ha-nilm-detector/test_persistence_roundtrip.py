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


def test_patterns_persist_after_restart():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")

        first_store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert first_store.connect() is True
            base = datetime(2026, 4, 6, 8, 0, 0)
            learned = first_store.learn_cycle_pattern(_build_cycle(base), suggestion_type="fridge")
            pattern = learned.get("pattern") or {}
            pattern_id = int(pattern.get("id", 0) or 0)
            assert pattern_id > 0
        finally:
            first_store.close()

        second_store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert second_store.connect() is True
            patterns = second_store.list_patterns(limit=50)
            assert len(patterns) >= 1
            ids = [int(p.get("id", 0) or 0) for p in patterns]
            assert pattern_id in ids
        finally:
            second_store.close()


def test_export_import_roundtrip_preserves_key_learning_fields():
    with TemporaryDirectory() as tmpdir:
        src_live = os.path.join(tmpdir, "src_live.sqlite3")
        src_patterns = os.path.join(tmpdir, "src_patterns.sqlite3")
        dst_live = os.path.join(tmpdir, "dst_live.sqlite3")
        dst_patterns = os.path.join(tmpdir, "dst_patterns.sqlite3")

        src = SQLiteStore(db_path=src_live, patterns_db_path=src_patterns)
        try:
            assert src.connect() is True
            t0 = datetime(2026, 4, 6, 12, 0, 0)
            src.learn_cycle_pattern(_build_cycle(t0, avg_power=170.0, peak_power=260.0), suggestion_type="fridge")
            src.learn_cycle_pattern(_build_cycle(t0 + timedelta(minutes=70), avg_power=172.0, peak_power=266.0), suggestion_type="fridge")
            exported = src.export_data()
            assert isinstance(exported, dict)
            assert len(exported.get("patterns", [])) >= 1
        finally:
            src.close()

        dst = SQLiteStore(db_path=dst_live, patterns_db_path=dst_patterns)
        try:
            assert dst.connect() is True
            result = dst.import_data(exported)
            assert result.get("ok") is True

            imported_patterns = dst.list_patterns(limit=100)
            assert len(imported_patterns) >= 1
            first = imported_patterns[0]
            assert "delta_avg_power_w" in first
            assert "delta_profile_points" in first
            assert "device_group_id" in first
            assert float(first.get("quality_score_avg", 0.0) or 0.0) >= 0.0

            # Ensure timestamp consistency was repaired/kept.
            from_dt = datetime.fromisoformat(str(first.get("first_seen")))
            to_dt = datetime.fromisoformat(str(first.get("last_seen")))
            assert to_dt >= from_dt
        finally:
            dst.close()
