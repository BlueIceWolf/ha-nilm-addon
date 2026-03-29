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