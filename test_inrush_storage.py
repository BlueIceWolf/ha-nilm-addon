#!/usr/bin/env python3

import os
import sys
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

from app.storage.sqlite_store import SQLiteStore


def _build_cycle() -> dict:
    start = datetime(2026, 3, 29, 12, 0, 0)
    duration_s = 30.0
    profile = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 30.0},
        {"t_s": 2.0, "t_norm": 2.0 / duration_s, "power_w": 235.0},
        {"t_s": 5.0, "t_norm": 5.0 / duration_s, "power_w": 165.0},
        {"t_s": 10.0, "t_norm": 10.0 / duration_s, "power_w": 160.0},
        {"t_s": 18.0, "t_norm": 18.0 / duration_s, "power_w": 158.0},
        {"t_s": 25.0, "t_norm": 25.0 / duration_s, "power_w": 55.0},
        {"t_s": 30.0, "t_norm": 1.0, "power_w": 30.0},
    ]
    avg_power = sum(point["power_w"] for point in profile) / len(profile)
    peak_power = max(point["power_w"] for point in profile)
    energy_wh = avg_power * duration_s / 3600.0
    return {
        "start_ts": start.isoformat(),
        "end_ts": (start + timedelta(seconds=duration_s)).isoformat(),
        "duration_s": duration_s,
        "avg_power_w": avg_power,
        "peak_power_w": peak_power,
        "energy_wh": energy_wh,
        "phase": "L1",
        "phase_mode": "single_phase",
        "active_phase_count": 1.0,
        "power_variance": 2100.0,
        "rise_rate_w_per_s": 102.5,
        "fall_rate_w_per_s": 35.0,
        "duty_cycle": 0.76,
        "peak_to_avg_ratio": peak_power / max(avg_power, 1.0),
        "num_substates": 3,
        "step_count": 3,
        "has_motor_pattern": True,
        "has_heating_pattern": False,
        "profile_points": profile,
    }


def test_inrush_and_baseline_schema_persists_cycle_details():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            result = store.learn_cycle_pattern(_build_cycle(), suggestion_type="fridge")
            assert result["pattern"] is not None

            pattern_row = store._patterns_conn.execute(
                """
                SELECT baseline_before_w_avg, baseline_after_w_avg,
                       delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                       delta_profile_points_json, plateau_count
                FROM learned_patterns
                LIMIT 1
                """
            ).fetchone()
            assert pattern_row is not None
            assert float(pattern_row[0]) <= 35.0
            assert float(pattern_row[1]) <= 35.0
            assert float(pattern_row[2]) > 70.0
            assert float(pattern_row[3]) > 150.0
            assert float(pattern_row[4]) > 0.0
            assert "power_w" in str(pattern_row[5])
            assert int(pattern_row[6]) >= 1

            event_row = store._patterns_conn.execute(
                """
                SELECT baseline_before_w, baseline_after_w,
                       delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                       delta_points_json, delta_resampled_points_json
                FROM events
                LIMIT 1
                """
            ).fetchone()
            assert event_row is not None
            assert float(event_row[0]) <= 35.0
            assert float(event_row[2]) > 70.0
            assert float(event_row[3]) > 150.0
            assert "power_w" in str(event_row[5])
            assert "[" in str(event_row[6])

            phase_types = [
                row[0]
                for row in store._patterns_conn.execute(
                    "SELECT phase_type FROM event_phases ORDER BY phase_index ASC"
                ).fetchall()
            ]
            assert "inrush" in phase_types
            assert any(phase_type in {"steady_run", "modulated_run"} for phase_type in phase_types)

            cycle_row = store._patterns_conn.execute(
                "SELECT cycle_type, avg_inrush_peak_w, avg_run_power_w FROM device_cycles LIMIT 1"
            ).fetchone()
            assert cycle_row is not None
            assert "inrush" in str(cycle_row[0])
            assert float(cycle_row[1]) > 150.0
            assert float(cycle_row[2]) > 70.0
        finally:
            store.close()


def test_device_registry_is_neutral_explainable_and_user_confirmable():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            cycle = _build_cycle()
            cycle["device_group_id"] = "cluster:l1:test_motor"
            learned = store.learn_cycle_pattern(cycle, suggestion_type="motor_load")
            assert learned["pattern"] is not None

            devices = store.list_devices(limit=20)
            assert devices
            device = devices[0]
            assert str(device["display_name"]).startswith("Unbekanntes Gerät ")
            assert device["confirmed"] == 0
            assert "confidence" in device
            assert set(device["confidence"]) == {
                "pattern_match",
                "device_class",
                "segmentation",
                "recurrence",
            }
            assert isinstance(device["explanation"], list)
            assert device["pattern_count"] >= 1

            result = store.update_device_identity(
                int(device["device_id"]),
                "Kühlschrank Küche",
                confirmed=True,
            )
            assert result["ok"] is True

            updated_devices = store.list_devices(limit=20)
            updated = next(d for d in updated_devices if int(d["device_id"]) == int(device["device_id"]))
            assert updated["display_name"] == "Kühlschrank Küche"
            assert updated["confirmed"] == 1

            pattern_label = store._patterns_conn.execute(
                "SELECT user_label, is_confirmed FROM learned_patterns WHERE device_id = ? LIMIT 1",
                (int(device["device_id"]),),
            ).fetchone()
            assert pattern_label is not None
            assert pattern_label[0] == "Kühlschrank Küche"
            assert int(pattern_label[1] or 0) == 1
        finally:
            store.close()


def test_device_registry_keeps_separate_electrical_clusters_on_same_phase():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            first = store._get_or_create_device(
                label="motor_load",
                phase="L3",
                confidence=0.6,
                group_key="cluster:l3:a",
            )
            second = store._get_or_create_device(
                label="motor_load",
                phase="L3",
                confidence=0.6,
                group_key="cluster:l3:b",
            )
            again = store._get_or_create_device(
                label="motor_load",
                phase="L3",
                confidence=0.7,
                group_key="cluster:l3:a",
            )

            assert first
            assert second
            assert int(first) != int(second)
            assert int(again) == int(first)
        finally:
            store.close()



def test_electrical_device_fingerprint_groups_similar_cycles_and_splits_different_loads():
    base = _build_cycle()
    base["phase"] = "L3"
    base["avg_power_w"] = 102.0
    base["peak_power_w"] = 145.0
    base["duration_s"] = 900.0
    base["delta_avg_power_w"] = 95.0
    base["delta_peak_power_w"] = 135.0
    base["has_motor_pattern"] = True
    base["num_substates"] = 1
    base["profile_points"] = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 8.0},
        {"t_s": 20.0, "t_norm": 0.02, "power_w": 145.0},
        {"t_s": 120.0, "t_norm": 0.13, "power_w": 108.0},
        {"t_s": 450.0, "t_norm": 0.50, "power_w": 103.0},
        {"t_s": 780.0, "t_norm": 0.87, "power_w": 101.0},
        {"t_s": 900.0, "t_norm": 1.0, "power_w": 8.0},
    ]

    similar = dict(base)
    similar["avg_power_w"] = 109.0
    similar["peak_power_w"] = 150.0
    similar["duration_s"] = 980.0
    similar["delta_avg_power_w"] = 101.0
    similar["delta_peak_power_w"] = 140.0

    very_different = dict(base)
    very_different["avg_power_w"] = 1250.0
    very_different["peak_power_w"] = 1900.0
    very_different["duration_s"] = 7200.0
    very_different["delta_avg_power_w"] = 1180.0
    very_different["delta_peak_power_w"] = 1800.0

    first_key = SQLiteStore._device_group_id("motor_load", base)
    similar_key = SQLiteStore._device_group_id("variable_motor_load", similar)
    different_key = SQLiteStore._device_group_id("motor_load", very_different)

    assert first_key == similar_key
    assert first_key != different_key


def test_device_recluster_migration_preserves_user_named_identity():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            named = _build_cycle()
            named["device_group_id"] = "old:coarse:L1"
            named_result = store.learn_cycle_pattern(named, suggestion_type="motor_load")
            named_pattern_id = int(named_result["pattern"]["id"])
            assert store.label_pattern(named_pattern_id, "Kühlschrank Küche") is True

            other = _build_cycle()
            other["start_ts"] = (datetime(2026, 3, 29, 14, 0, 0)).isoformat()
            other["end_ts"] = (datetime(2026, 3, 29, 16, 0, 0)).isoformat()
            other["avg_power_w"] = 1200.0
            other["peak_power_w"] = 1900.0
            other["duration_s"] = 7200.0
            other["delta_avg_power_w"] = 1100.0
            other["delta_peak_power_w"] = 1800.0
            other["device_group_id"] = "old:coarse:L1"
            other_result = store.learn_cycle_pattern(other, suggestion_type="motor_load")
            other_pattern_id = int(other_result["pattern"]["id"])

            # Force the new migration to execute in this fresh test DB.
            with store._patterns_conn:
                store._patterns_conn.execute(
                    "DELETE FROM migration_events WHERE event_key = ?",
                    ("physical_device_registry_recluster:v2",),
                )
            store._maybe_recluster_device_registry_v2()

            named_row = store._patterns_conn.execute(
                "SELECT device_id, user_label FROM learned_patterns WHERE id = ?",
                (named_pattern_id,),
            ).fetchone()
            other_row = store._patterns_conn.execute(
                "SELECT device_id, user_label, device_group_id FROM learned_patterns WHERE id = ?",
                (other_pattern_id,),
            ).fetchone()

            assert named_row is not None
            assert named_row[1] == "Kühlschrank Küche"
            assert other_row is not None
            assert not str(other_row[1] or "")
            assert int(named_row[0]) != int(other_row[0])
            assert str(other_row[2]).startswith("v2:")

            device_row = store._patterns_conn.execute(
                "SELECT user_label, confirmed FROM devices WHERE device_id = ?",
                (int(named_row[0]),),
            ).fetchone()
            assert device_row is not None
            assert device_row[0] == "Kühlschrank Küche"
            assert int(device_row[1] or 0) == 1
        finally:
            store.close()
