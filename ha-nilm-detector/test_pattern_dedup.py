#!/usr/bin/env python3

import os
import sys
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

sys.path.append(os.path.dirname(__file__))

from app.storage.sqlite_store import SQLiteStore


def _build_cycle(start: datetime, avg_power: float, peak_power: float, duration_s: float = 40.0) -> dict:
    profile = [
        {"t_s": 0.0, "t_norm": 0.0, "power_w": 30.0},
        {"t_s": 3.0, "t_norm": 3.0 / duration_s, "power_w": peak_power},
        {"t_s": 12.0, "t_norm": 12.0 / duration_s, "power_w": avg_power + 15.0},
        {"t_s": 30.0, "t_norm": 30.0 / duration_s, "power_w": avg_power},
        {"t_s": duration_s, "t_norm": 1.0, "power_w": 30.0},
    ]
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
        "power_variance": 900.0,
        "rise_rate_w_per_s": 80.0,
        "fall_rate_w_per_s": 45.0,
        "duty_cycle": 0.72,
        "peak_to_avg_ratio": peak_power / max(avg_power, 1.0),
        "num_substates": 2,
        "step_count": 2,
        "has_motor_pattern": True,
        "has_heating_pattern": False,
        "profile_points": profile,
    }


def test_dedup_updates_existing_pattern_for_high_similarity():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            base_time = datetime(2026, 4, 1, 8, 0, 0)
            first = store.learn_cycle_pattern(_build_cycle(base_time, 160.0, 245.0), suggestion_type="fridge")
            second = store.learn_cycle_pattern(_build_cycle(base_time + timedelta(minutes=45), 162.0, 248.0), suggestion_type="fridge")

            assert first.get("pattern") is not None
            assert second.get("matched") is True
            dedup = dict(second.get("dedup") or {})
            assert dedup.get("result") in {"update_existing", "merge_mode"}
            assert store._patterns_conn is not None
            conn = store._patterns_conn

            pattern_count = conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone()
            assert int((pattern_count or [0])[0]) == 1

            seen = conn.execute("SELECT seen_count FROM learned_patterns LIMIT 1").fetchone()
            assert int((seen or [0])[0]) >= 2

            log_row = conn.execute(
                "SELECT dedup_result, similarity_score FROM training_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert log_row is not None
            assert str(log_row[0] or "") in {"update_existing", "merge_mode"}
            assert float(log_row[1] or 0.0) >= 0.85
        finally:
            store.close()


def test_dedup_creates_new_pattern_for_low_similarity():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            base_time = datetime(2026, 4, 2, 10, 0, 0)
            _ = store.learn_cycle_pattern(_build_cycle(base_time, 150.0, 220.0, duration_s=35.0), suggestion_type="fridge")
            second = store.learn_cycle_pattern(
                _build_cycle(base_time + timedelta(minutes=80), 540.0, 780.0, duration_s=210.0),
                suggestion_type="washing_machine",
            )

            assert second.get("pattern") is not None
            assert second.get("matched") is False
            dedup = dict(second.get("dedup") or {})
            assert dedup.get("result") == "create_new"
            assert store._patterns_conn is not None
            conn = store._patterns_conn

            pattern_count = conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone()
            assert int((pattern_count or [0])[0]) == 2
        finally:
            store.close()


def test_session_overlap_cooldown_skips_duplicate_cycle():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            base_time = datetime(2026, 4, 3, 9, 0, 0)
            first = store.learn_cycle_pattern(_build_cycle(base_time, 170.0, 260.0, duration_s=55.0), suggestion_type="fridge")
            assert first.get("pattern") is not None

            # Overlapping and very close cycle window should be skipped as same physical cycle.
            overlapping = _build_cycle(base_time + timedelta(seconds=20), 171.0, 262.0, duration_s=52.0)
            second = store.learn_cycle_pattern(overlapping, suggestion_type="fridge")

            assert second.get("skipped") is True
            assert second.get("reason") == "session_duplicate_cycle"
            assert store._patterns_conn is not None
            count_row = store._patterns_conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone()
            assert int((count_row or [0])[0]) == 1
        finally:
            store.close()


def test_repair_timestamp_order_migration_fixes_broken_rows():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True
            assert store._patterns_conn is not None
            conn = store._patterns_conn

            now = datetime(2026, 4, 4, 12, 0, 0)
            with conn:
                conn.execute(
                    """
                    INSERT INTO learned_patterns (
                        created_at, updated_at, first_seen, last_seen, seen_count,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        suggestion_type, user_label, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now.isoformat(),
                        now.isoformat(),
                        (now + timedelta(hours=3)).isoformat(),
                        now.isoformat(),
                        2,
                        180.0,
                        260.0,
                        40.0,
                        2.0,
                        "fridge",
                        None,
                        "active",
                    ),
                )

            # Re-run repair explicitly in test runtime.
            store._maybe_repair_pattern_timestamps(force=True)

            row = conn.execute("SELECT first_seen, last_seen FROM learned_patterns ORDER BY id DESC LIMIT 1").fetchone()
            assert row is not None
            first_seen = datetime.fromisoformat(str(row[0]))
            last_seen = datetime.fromisoformat(str(row[1]))
            assert last_seen >= first_seen
        finally:
            store.close()


def test_same_device_slightly_different_inrush_still_merges():
    with TemporaryDirectory() as tmpdir:
        live_db = os.path.join(tmpdir, "live.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        store = SQLiteStore(db_path=live_db, patterns_db_path=patterns_db)
        try:
            assert store.connect() is True

            base = datetime(2026, 4, 8, 7, 0, 0)
            a = _build_cycle(base, avg_power=165.0, peak_power=250.0, duration_s=45.0)
            b = _build_cycle(base + timedelta(minutes=50), avg_power=166.0, peak_power=285.0, duration_s=46.0)
            # Slightly different inrush profile while steady part remains close.
            b["profile_points"][1]["power_w"] = 295.0
            b["profile_points"][2]["power_w"] = 183.0

            first = store.learn_cycle_pattern(a, suggestion_type="fridge")
            second = store.learn_cycle_pattern(b, suggestion_type="fridge")

            assert first.get("pattern") is not None
            assert second.get("pattern") is not None
            dedup = dict(second.get("dedup") or {})
            assert dedup.get("result") in {"update_existing", "merge_mode"}
            assert store._patterns_conn is not None
            count_row = store._patterns_conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone()
            assert int((count_row or [0])[0]) == 1
        finally:
            store.close()
