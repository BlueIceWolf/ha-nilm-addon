"""SQLite storage for power readings and detection events."""

import json
import hashlib
import csv
import io
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.learning.ml_classifier import LocalMLClassifier
from app.learning.online_learning import build_pattern_dataset_rows
from app.learning.pattern_matching import HybridPatternMatcher
from app.learning.pipeline_stages import (
    decide_dedup_action,
    find_best_pattern_match,
    prepare_cycle_for_learning,
)
from app.learning.substate_analysis import analyze_profile_substates
from app.models import DetectionResult, PowerReading
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SQLiteStore:
    """Persists readings/detections for diagnostics and future learning."""

    LIVE_SCHEMA_VERSION = 2
    PATTERNS_SCHEMA_VERSION = 4
    LEARNING_PARAMS: Dict[str, float] = {
        "quality_min_accept": 0.28,
        "baseline_quality_min": 0.22,
        "delta_energy_min_wh": 0.002,
        "session_overlap_cooldown_s": 120.0,
        "session_exact_window_s": 240.0,
        "mode_merge_max_dist": 0.30,
        "dedup_update_similarity": 0.94,
        "dedup_merge_similarity": 0.88,
    }

    # Legacy DB paths checked during recovery/migration (order matters: most likely first)
    LEGACY_PATTERNS_CANDIDATES: List[str] = [
        "/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3",
        "/addon_configs/ha_nilm_detector/nilm_live.sqlite3",
        "/data/ha_nilm_detector/nilm_patterns.sqlite3",
        "/data/ha_nilm_detector/nilm_live.sqlite3",
        "/data/nilm_patterns.sqlite3",
        "/data/nilm_live.sqlite3",
    ]
    LEGACY_LIVE_CANDIDATES: List[str] = [
        "/addon_configs/ha_nilm_detector/nilm_live.sqlite3",
        "/data/ha_nilm_detector/nilm_live.sqlite3",
        "/data/nilm_live.sqlite3",
    ]

    def __init__(self, db_path: str, retention_days: int = 30, patterns_db_path: str | None = None):
        self.db_path = db_path
        self.patterns_db_path = str(patterns_db_path or db_path)
        self.retention_days = max(int(retention_days), 1)
        self._conn: sqlite3.Connection | None = None
        self._patterns_conn: sqlite3.Connection | None = None
        
        # Batch writing for improved performance
        self._reading_batch: List[PowerReading] = []
        self._detection_batch: List[DetectionResult] = []
        self._max_batch_size = 100  # Flush after this many items
        self._batch_ops_since_flush = 0

        # Hybrid-AI tuning switches (configurable from Config/main)
        self.ai_enabled = True
        self.ml_enabled = False
        self.shape_matching_enabled = True
        self.online_learning_enabled = True
        self.pattern_match_threshold = 0.45
        self.ml_confidence_threshold = 0.60
        self._ml_classifier = LocalMLClassifier()
        self._pattern_matcher = HybridPatternMatcher(
            match_threshold=self.pattern_match_threshold,
            shape_matching_enabled=self.shape_matching_enabled,
        )
        self._last_hybrid_decision: Dict[str, Any] = {
            "label": "unknown",
            "confidence": 0.0,
            "source": "not_run_yet",
            "timestamp": None,
            "explain": None,
        }
        self._learning_session_keys: Dict[str, str] = {}
        self._learning_session_windows: List[Dict[str, Any]] = []

    def configure_hybrid_ai(
        self,
        ai_enabled: bool = True,
        ml_enabled: bool = False,
        shape_matching_enabled: bool = True,
        online_learning_enabled: bool = True,
        pattern_match_threshold: float = 0.45,
        ml_confidence_threshold: float = 0.60,
    ) -> None:
        """Configure hybrid AI scoring behavior at runtime."""
        self.ai_enabled = bool(ai_enabled)
        self.ml_enabled = bool(ml_enabled)
        self.shape_matching_enabled = bool(shape_matching_enabled)
        self.online_learning_enabled = bool(online_learning_enabled)
        self.pattern_match_threshold = max(0.05, min(float(pattern_match_threshold), 0.95))
        self.ml_confidence_threshold = max(0.05, min(float(ml_confidence_threshold), 0.99))
        self._pattern_matcher = HybridPatternMatcher(
            match_threshold=self.pattern_match_threshold,
            shape_matching_enabled=self.shape_matching_enabled,
        )

    def get_hybrid_debug_status(self) -> Dict[str, Any]:
        """Return latest hybrid AI decision snapshot for dashboard debug panel."""
        return dict(self._last_hybrid_decision)

    def _open_connection(self, path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(
            path,
            check_same_thread=False,
            timeout=10,
        )
        conn.execute("PRAGMA journal_mode=WAL;")
        # FULL is slower than NORMAL but safer for abrupt power loss/container crash.
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _check_integrity(self, conn: sqlite3.Connection) -> bool:
        try:
            row = conn.execute("PRAGMA quick_check;").fetchone()
            ok = bool(row and row[0] == "ok")
            if not ok:
                logger.error(f"SQLite integrity check failed: {row[0] if row else 'unknown'}")
            return ok
        except Exception as e:
            logger.error(f"SQLite integrity check error: {e}", exc_info=True)
            return False

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (str(table_name),),
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    @staticmethod
    def _list_tables(conn: sqlite3.Connection) -> List[str]:
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            return [str(r[0]) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _safe_row_count(conn: sqlite3.Connection, table_name: str) -> int:
        try:
            if not SQLiteStore._table_exists(conn, table_name):
                return 0
            row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            return int((row or [0])[0])
        except Exception:
            return 0

    # Public helpers for robust migration/recovery checks
    def table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        return self._table_exists(connection, table_name)

    def list_tables(self, connection: sqlite3.Connection) -> List[str]:
        return self._list_tables(connection)

    def count_rows(self, connection: sqlite3.Connection, table_name: str) -> int:
        return self._safe_row_count(connection, table_name)

    @staticmethod
    def _db_file_stats(path: str) -> Dict[str, Any]:
        exists = os.path.exists(path)
        size_bytes = 0
        if exists:
            try:
                size_bytes = int(os.path.getsize(path))
            except OSError:
                size_bytes = 0
        return {
            "path": path,
            "exists": exists,
            "size_bytes": size_bytes,
        }

    @staticmethod
    def _ensure_schema_version(conn: sqlite3.Connection, target: int) -> int:
        try:
            current = int((conn.execute("PRAGMA user_version").fetchone() or [0])[0])
        except Exception:
            current = 0

        if current < int(target):
            try:
                conn.execute(f"PRAGMA user_version={int(target)}")
                current = int(target)
            except Exception:
                pass
        return current

    def _log_startup_diagnostics(self, stage: str) -> None:
        """Emit startup diagnostics so persistence issues are visible in logs."""
        live_stats = self._db_file_stats(self.db_path)
        patterns_stats = self._db_file_stats(self.patterns_db_path)

        logger.info(
            "Storage init (%s): primary_path=%s live_exists=%s live_size=%sB patterns_exists=%s patterns_size=%sB",
            stage,
            os.path.dirname(self.db_path),
            live_stats["exists"],
            live_stats["size_bytes"],
            patterns_stats["exists"],
            patterns_stats["size_bytes"],
        )

        if self._conn:
            live_tables = self._list_tables(self._conn)
            live_user_version = int((self._conn.execute("PRAGMA user_version").fetchone() or [0])[0])
            logger.info("Live DB tables (%s): %s", stage, ", ".join(live_tables) if live_tables else "<none>")
            logger.info(
                "Live DB row counts (%s): power_readings=%s detections=%s user_version=%s",
                stage,
                self._safe_row_count(self._conn, "power_readings"),
                self._safe_row_count(self._conn, "detections"),
                live_user_version,
            )

        if self._patterns_conn:
            pattern_tables = self._list_tables(self._patterns_conn)
            pattern_user_version = int((self._patterns_conn.execute("PRAGMA user_version").fetchone() or [0])[0])
            logger.info("Pattern DB tables (%s): %s", stage, ", ".join(pattern_tables) if pattern_tables else "<none>")
            logger.info(
                "Pattern DB row counts (%s): learned_patterns=%s legacy_patterns=%s devices=%s events=%s event_phases=%s device_cycles=%s user_labels=%s class_log=%s user_version=%s",
                stage,
                self._safe_row_count(self._patterns_conn, "learned_patterns"),
                self._safe_row_count(self._patterns_conn, "patterns"),
                self._safe_row_count(self._patterns_conn, "devices"),
                self._safe_row_count(self._patterns_conn, "events"),
                self._safe_row_count(self._patterns_conn, "event_phases"),
                self._safe_row_count(self._patterns_conn, "device_cycles"),
                self._safe_row_count(self._patterns_conn, "user_labels"),
                self._safe_row_count(self._patterns_conn, "classification_log"),
                pattern_user_version,
            )

        if stage == "pre-init":
            # Log legacy path availability so data-loss issues are immediately visible
            checked: List[str] = []
            for leg_path in self.LEGACY_PATTERNS_CANDIDATES + self.LEGACY_LIVE_CANDIDATES:
                if leg_path in checked:
                    continue
                checked.append(leg_path)
                s = self._db_file_stats(leg_path)
                if s["exists"]:
                    logger.info(
                        "Legacy DB found: %s (size=%sB)",
                        leg_path,
                        s["size_bytes"],
                    )

    def _quarantine_corrupt_db(self) -> None:
        if not os.path.exists(self.db_path):
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_path = f"{self.db_path}.corrupt.{stamp}"
        try:
            os.replace(self.db_path, corrupt_path)
            logger.error(f"Corrupt SQLite DB moved to {corrupt_path}")
            for suffix in ["-wal", "-shm"]:
                sidecar = f"{self.db_path}{suffix}"
                if os.path.exists(sidecar):
                    os.replace(sidecar, f"{corrupt_path}{suffix}")
        except Exception as e:
            logger.error(f"Failed to quarantine corrupt DB: {e}", exc_info=True)

    def _reinitialize_database(self) -> bool:
        try:
            self._quarantine_corrupt_db()
            self._conn = self._open_connection(self.db_path)
            self._create_tables()
            logger.warning("SQLite storage was reinitialized after integrity failure")
            return True
        except Exception as e:
            logger.error(f"Failed to reinitialize SQLite DB: {e}", exc_info=True)
            return False

    def connect(self) -> bool:
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            self._conn = self._open_connection(self.db_path)
            self._log_startup_diagnostics(stage="pre-init")

            if not self._check_integrity(self._conn):
                if not self._reinitialize_database():
                    return False

            patterns_dir = os.path.dirname(self.patterns_db_path)
            if patterns_dir:
                os.makedirs(patterns_dir, exist_ok=True)
            if os.path.abspath(self.patterns_db_path) == os.path.abspath(self.db_path):
                self._patterns_conn = self._conn
            else:
                self._patterns_conn = self._open_connection(self.patterns_db_path)
                if not self._check_integrity(self._patterns_conn):
                    logger.warning("Patterns DB integrity check failed; continuing with empty patterns DB")

            self._create_tables()
            self._maybe_migrate_patterns_from_live()
            self._maybe_recover_live_from_legacy_files()
            self._maybe_recover_patterns_from_legacy_files()
            self._maybe_backfill_normalized_tables()
            self._maybe_backfill_patterns_mirror()
            self._maybe_backfill_inrush_runtime_schema()
            self._maybe_repair_pattern_timestamps()
            self.cleanup_old_data()
            self._log_startup_diagnostics(stage="post-init")
            logger.info(
                "SQLite storage initialized: "
                f"live={self.db_path}, patterns={self.patterns_db_path}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SQLite storage: {e}", exc_info=True)
            return False

    # ---------------------------------------------------------------------------
    # Migration helpers
    # ---------------------------------------------------------------------------

    def _migration_applied(self, conn: sqlite3.Connection, event_key: str) -> bool:
        """Return True if this migration was already recorded in migration_events."""
        try:
            row = conn.execute(
                "SELECT 1 FROM migration_events WHERE event_key=? LIMIT 1",
                (str(event_key),),
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    def _record_migration(self, conn: sqlite3.Connection, event_key: str, details: str = "") -> None:
        """Record a completed migration so it is not repeated on next start."""
        try:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO migration_events (event_key, executed_at, details) VALUES (?, ?, ?)",
                    (str(event_key), datetime.now().isoformat(), str(details)),
                )
        except Exception as e:
            logger.warning("Could not record migration event %s: %s", event_key, e)

    def _maybe_backfill_normalized_tables(self) -> None:
        """Backfill devices/pattern_history/pattern_features from learned_patterns once."""
        if not self._patterns_conn:
            return

        event_key = "normalized_backfill_from_learned_patterns:v1"
        if self._migration_applied(self._patterns_conn, event_key):
            return

        if not self._table_exists(self._patterns_conn, "learned_patterns"):
            self._record_migration(self._patterns_conn, event_key, "learned_patterns missing")
            return

        try:
            patterns = self.list_patterns(limit=5000)
            if not patterns:
                self._record_migration(self._patterns_conn, event_key, "no patterns to backfill")
                return

            linked_devices = 0
            history_rows = 0
            feature_rows = 0

            for pattern in patterns:
                pid = int(pattern.get("id", 0) or 0)
                if pid <= 0:
                    continue

                label = str(pattern.get("user_label") or pattern.get("suggestion_type") or "unknown").strip() or "unknown"
                phase = str(pattern.get("phase") or "L1")
                confidence = float(pattern.get("confidence_score", 0.0) or 0.0) / 100.0
                device_id = self._get_or_create_device(
                    label=label,
                    phase=phase,
                    confidence=confidence,
                    confirmed=bool(pattern.get("user_label")),
                )
                if device_id:
                    linked_devices += 1
                    with self._patterns_conn:
                        self._patterns_conn.execute(
                            """
                            UPDATE learned_patterns
                            SET device_id = COALESCE(device_id, ?),
                                candidate_name = COALESCE(NULLIF(candidate_name, ''), ?),
                                is_confirmed = CASE WHEN user_label IS NOT NULL AND TRIM(user_label) != '' THEN 1 ELSE is_confirmed END
                            WHERE id = ?
                            """,
                            (int(device_id), label, pid),
                        )

                self._record_pattern_history_snapshot(pattern)
                history_rows += 1

                synthetic_cycle = {
                    "power_variance": pattern.get("power_variance", 0.0),
                    "avg_power_w": pattern.get("avg_power_w", 0.0),
                    "num_substates": pattern.get("num_substates", 0),
                    "step_count": pattern.get("step_count", 0),
                    "rise_rate_w_per_s": pattern.get("rise_rate_w_per_s", 0.0),
                    "fall_rate_w_per_s": pattern.get("fall_rate_w_per_s", 0.0),
                    "profile_points": pattern.get("profile_points", []),
                }
                self._record_pattern_features(pid, synthetic_cycle, feature_version="backfill_v1")
                feature_rows += 1

            details = (
                f"patterns={len(patterns)} linked_devices={linked_devices} "
                f"history_rows={history_rows} feature_rows={feature_rows}"
            )
            self._record_migration(self._patterns_conn, event_key, details)
            logger.info("Backfilled normalized NILM tables: %s", details)
        except Exception as e:
            logger.warning("Normalized table backfill failed: %s", e)

        # Keep an explicit normalized patterns table in sync (separate from learned_patterns).
        self._maybe_backfill_patterns_mirror()

    def _maybe_backfill_patterns_mirror(self) -> None:
        if not self._patterns_conn:
            return
        event_key = "patterns_mirror_backfill:v1"
        if self._migration_applied(self._patterns_conn, event_key):
            return
        try:
            patterns = self.list_patterns(limit=5000)
            for pattern in patterns:
                self._upsert_patterns_mirror(pattern)
            self._record_migration(self._patterns_conn, event_key, f"mirrored={len(patterns)}")
            logger.info("Backfilled explicit patterns mirror table with %s rows", len(patterns))
        except Exception as e:
            logger.warning("Patterns mirror backfill failed: %s", e)

    def _upsert_patterns_mirror(self, pattern: Dict[str, Any]) -> None:
        if not self._patterns_conn:
            return
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT OR REPLACE INTO patterns (
                        pattern_id, device_id, created_at, updated_at, first_seen, last_seen,
                        seen_count, phase, phase_mode,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        baseline_before_w_avg, baseline_after_w_avg,
                        delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                        stability_score, confidence_score, frequency_per_day,
                        typical_interval_s, quality_score_avg,
                        suggestion_type, candidate_name, status, is_confirmed,
                        profile_points_json, delta_profile_points_json, shape_vector_json, delta_shape_vector_json, prototype_hash,
                        num_substates, step_count, plateau_count,
                        shape_similarity_score, cluster_similarity_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(pattern.get("id", 0) or 0),
                        int(pattern.get("device_id", 0) or 0) or None,
                        str(pattern.get("created_at") or datetime.now().isoformat()),
                        str(pattern.get("updated_at") or datetime.now().isoformat()),
                        str(pattern.get("first_seen") or datetime.now().isoformat()),
                        str(pattern.get("last_seen") or datetime.now().isoformat()),
                        int(pattern.get("seen_count", 0) or 0),
                        str(pattern.get("phase") or "L1"),
                        str(pattern.get("phase_mode") or "unknown"),
                        float(pattern.get("avg_power_w", 0.0) or 0.0),
                        float(pattern.get("peak_power_w", 0.0) or 0.0),
                        float(pattern.get("duration_s", 0.0) or 0.0),
                        float(pattern.get("energy_wh", 0.0) or 0.0),
                        float(pattern.get("baseline_before_w_avg", pattern.get("baseline_before_w", 0.0)) or 0.0),
                        float(pattern.get("baseline_after_w_avg", pattern.get("baseline_after_w", 0.0)) or 0.0),
                        float(pattern.get("delta_avg_power_w", 0.0) or 0.0),
                        float(pattern.get("delta_peak_power_w", 0.0) or 0.0),
                        float(pattern.get("delta_energy_wh", 0.0) or 0.0),
                        float(pattern.get("stability_score", 0.0) or 0.0),
                        float(pattern.get("confidence_score_db", pattern.get("confidence_score", 0.0)) or 0.0),
                        float(pattern.get("frequency_per_day_db", pattern.get("frequency_per_day", 0.0)) or 0.0),
                        float(pattern.get("typical_interval_s", 0.0) or 0.0),
                        float(pattern.get("quality_score_avg", 0.0) or 0.0),
                        str(pattern.get("suggestion_type") or "unknown"),
                        str(pattern.get("candidate_name") or "unknown"),
                        str(pattern.get("status") or "active"),
                        1 if bool(pattern.get("is_confirmed")) else 0,
                        json.dumps(self._normalize_profile_points(pattern.get("profile_points", []))),
                        json.dumps(self._normalize_profile_points(pattern.get("delta_profile_points", []))),
                        str(pattern.get("shape_vector_json") or "[]"),
                        str(pattern.get("delta_shape_vector_json") or json.dumps(pattern.get("delta_shape_vector", [])) or "[]"),
                        str(pattern.get("prototype_hash") or ""),
                        int(pattern.get("num_substates", 0) or 0),
                        int(pattern.get("step_count", 0) or 0),
                        int(pattern.get("plateau_count", pattern.get("num_substates", 0)) or 0),
                        0.0,
                        0.0,
                    ),
                )
        except Exception as e:
            logger.debug("_upsert_patterns_mirror failed: %s", e)

    def _migrate_from_patterns_table(
        self, src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, source_label: str
    ) -> int:
        """Migrate rows from an old-style 'patterns' table into 'learned_patterns'.

        The old schema may differ from the new one – we map what we can and fill
        the rest with safe defaults.  Returns the number of rows inserted.
        """
        try:
            pragma = src_conn.execute("PRAGMA table_info(patterns)").fetchall()
            if not pragma:
                return 0
            existing_cols = {str(r[1]) for r in pragma}

            # Build a flexible SELECT that maps old columns to new schema
            now_iso = datetime.now().isoformat()

            def _col(name: str, fallback: str) -> str:
                return name if name in existing_cols else fallback

            # suggestion_type may be stored as 'label', 'device_type', or 'suggestion_type'
            stype_expr = (
                "suggestion_type" if "suggestion_type" in existing_cols
                else ("label" if "label" in existing_cols
                      else ("device_type" if "device_type" in existing_cols
                            else "'unknown'"))
            )

            select_sql = f"""
                SELECT
                    {_col('created_at', repr(now_iso))},
                    {_col('updated_at', repr(now_iso))},
                    {_col('first_seen', repr(now_iso))},
                    {_col('last_seen', repr(now_iso))},
                    {_col('seen_count', '1')},
                    {_col('avg_power_w', '0.0')},
                    {_col('peak_power_w', '0.0')},
                    {_col('duration_s', '0.0')},
                    {_col('energy_wh', '0.0')},
                    COALESCE({stype_expr}, 'unknown'),
                    {_col('user_label', 'NULL')},
                    {_col('status', "'active'")},
                    COALESCE({_col('avg_active_phases', '1.0')}, 1.0),
                    COALESCE({_col('phase_mode', "'unknown'")}, 'unknown'),
                    COALESCE({_col('power_variance', '0.0')}, 0.0),
                    COALESCE({_col('rise_rate_w_per_s', '0.0')}, 0.0),
                    COALESCE({_col('fall_rate_w_per_s', '0.0')}, 0.0),
                    COALESCE({_col('duty_cycle', '0.0')}, 0.0),
                    COALESCE({_col('peak_to_avg_ratio', '1.0')}, 1.0),
                    COALESCE({_col('num_substates', '0')}, 0),
                    COALESCE({_col('has_heating_pattern', '0')}, 0),
                    COALESCE({_col('has_motor_pattern', '0')}, 0)
                FROM patterns
            """
            rows = src_conn.execute(select_sql).fetchall()
            if not rows:
                return 0

            with dst_conn:
                dst_conn.executemany(
                    """
                    INSERT OR IGNORE INTO learned_patterns (
                        created_at, updated_at, first_seen, last_seen, seen_count,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        suggestion_type, user_label, status,
                        avg_active_phases, phase_mode,
                        power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                        duty_cycle, peak_to_avg_ratio, num_substates,
                        has_heating_pattern, has_motor_pattern
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            logger.info("Migrated %s pattern(s) from old 'patterns' table in %s", len(rows), source_label)
            return len(rows)
        except Exception as e:
            logger.warning("_migrate_from_patterns_table failed for %s: %s", source_label, e)
            return 0

    def _maybe_migrate_patterns_from_live(self) -> None:
        """Migrate existing patterns from live DB into dedicated patterns DB once."""
        if not self._conn or not self._patterns_conn:
            return
        if self._patterns_conn is self._conn:
            return

        try:
            # --- Case A: modern 'learned_patterns' table in live DB ---------------
            if self._table_exists(self._conn, "learned_patterns"):
                src_count = self._safe_row_count(self._conn, "learned_patterns")
                if src_count == 0:
                    return

                # Only migrate when destination is empty to avoid duplicates
                dst_count = self._safe_row_count(self._patterns_conn, "learned_patterns")
                if dst_count > 0:
                    return

                migration_key = "live_to_patterns_db:learned_patterns"
                if self._migration_applied(self._patterns_conn, migration_key):
                    return

                src_rows = self._conn.execute(
                    """
                    SELECT id, created_at, updated_at, first_seen, last_seen, seen_count,
                           avg_power_w, peak_power_w, duration_s, energy_wh,
                           suggestion_type, user_label, status,
                           COALESCE(avg_active_phases, 1.0), COALESCE(phase_mode, 'unknown'),
                           COALESCE(power_variance, 0.0), COALESCE(rise_rate_w_per_s, 0.0),
                           COALESCE(fall_rate_w_per_s, 0.0), COALESCE(duty_cycle, 0.0),
                           COALESCE(peak_to_avg_ratio, 1.0), COALESCE(num_substates, 0),
                           COALESCE(has_heating_pattern, 0), COALESCE(has_motor_pattern, 0)
                    FROM learned_patterns
                    """
                ).fetchall()
                if not src_rows:
                    return

                with self._patterns_conn:
                    self._patterns_conn.executemany(
                        """
                        INSERT OR REPLACE INTO learned_patterns (
                            id, created_at, updated_at, first_seen, last_seen, seen_count,
                            avg_power_w, peak_power_w, duration_s, energy_wh,
                            suggestion_type, user_label, status,
                            avg_active_phases, phase_mode,
                            power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                            duty_cycle, peak_to_avg_ratio, num_substates,
                            has_heating_pattern, has_motor_pattern
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        src_rows,
                    )
                self._record_migration(
                    self._patterns_conn, migration_key,
                    f"migrated {len(src_rows)} patterns from live DB learned_patterns"
                )
                logger.info("Migrated %s pattern(s) from live DB into dedicated patterns DB", len(src_rows))
                return

            # --- Case B: old 'patterns' table in live DB (legacy schema) ----------
            if self._table_exists(self._conn, "patterns"):
                src_count = self._safe_row_count(self._conn, "patterns")
                logger.info(
                    "Found legacy table 'patterns' in live DB with %s rows – migrating to learned_patterns",
                    src_count,
                )

                dst_count = self._safe_row_count(self._patterns_conn, "learned_patterns")
                migration_key = "live_to_patterns_db:legacy_patterns_table"
                if dst_count > 0 or self._migration_applied(self._patterns_conn, migration_key):
                    logger.info("Destination already has data or migration already ran – skipping")
                    return

                count = self._migrate_from_patterns_table(self._conn, self._patterns_conn, "live DB")
                if count > 0:
                    self._record_migration(
                        self._patterns_conn, migration_key,
                        f"migrated {count} patterns from live DB old 'patterns' table"
                    )
                return

            logger.info("No pattern tables found in live DB – nothing to migrate")
        except Exception as e:
            logger.warning("Pattern migration to dedicated DB failed: %s", e)

    def _maybe_recover_patterns_from_legacy_files(self) -> None:
        """Recover patterns from legacy addon paths if current patterns DB is empty.

        Checks both 'learned_patterns' (modern schema) and 'patterns' (legacy schema)
        in each candidate DB file so that data is never silently lost.
        """
        if not self._patterns_conn:
            return

        try:
            dst_count = self._safe_row_count(self._patterns_conn, "learned_patterns")
            if dst_count > 0:
                return
        except Exception:
            return

        for legacy_path in self.LEGACY_PATTERNS_CANDIDATES:
            try:
                legacy_abs = os.path.abspath(str(legacy_path))
                if legacy_abs == os.path.abspath(self.patterns_db_path):
                    continue
                if not os.path.exists(legacy_abs):
                    continue

                migration_key = f"legacy_pattern_recovery:{legacy_abs}"
                if self._migration_applied(self._patterns_conn, migration_key):
                    logger.info("Legacy recovery already applied for %s – skipping", legacy_abs)
                    continue

                legacy_conn = sqlite3.connect(legacy_abs, timeout=5)
                try:
                    legacy_tables = self._list_tables(legacy_conn)
                    logger.info(
                        "Checking legacy DB for patterns: %s (tables: %s)",
                        legacy_abs,
                        ", ".join(legacy_tables) if legacy_tables else "<none>",
                    )

                    # --- Try modern schema first ----------------------------------
                    if self._table_exists(legacy_conn, "learned_patterns"):
                        src_count = self._safe_row_count(legacy_conn, "learned_patterns")
                        if src_count > 0:
                            rows = legacy_conn.execute(
                                """
                                SELECT created_at, updated_at, first_seen, last_seen, seen_count,
                                       avg_power_w, peak_power_w, duration_s, energy_wh,
                                       suggestion_type, user_label, status,
                                       COALESCE(avg_active_phases, 1.0),
                                       COALESCE(phase_mode, 'unknown'),
                                       COALESCE(power_variance, 0.0),
                                       COALESCE(rise_rate_w_per_s, 0.0),
                                       COALESCE(fall_rate_w_per_s, 0.0),
                                       COALESCE(duty_cycle, 0.0),
                                       COALESCE(peak_to_avg_ratio, 1.0),
                                       COALESCE(num_substates, 0),
                                       COALESCE(has_heating_pattern, 0),
                                       COALESCE(has_motor_pattern, 0)
                                FROM learned_patterns
                                """
                            ).fetchall()
                            if rows:
                                with self._patterns_conn:
                                    self._patterns_conn.executemany(
                                        """
                                        INSERT OR IGNORE INTO learned_patterns (
                                            created_at, updated_at, first_seen, last_seen, seen_count,
                                            avg_power_w, peak_power_w, duration_s, energy_wh,
                                            suggestion_type, user_label, status,
                                            avg_active_phases, phase_mode,
                                            power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                                            duty_cycle, peak_to_avg_ratio, num_substates,
                                            has_heating_pattern, has_motor_pattern
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        rows,
                                    )
                                self._record_migration(
                                    self._patterns_conn, migration_key,
                                    f"recovered {len(rows)} patterns from learned_patterns in {legacy_abs}"
                                )
                                logger.info(
                                    "Recovered %s pattern(s) from legacy DB learned_patterns: %s",
                                    len(rows), legacy_abs,
                                )
                                return

                    # --- Fall back to old 'patterns' table -----------------------
                    if self._table_exists(legacy_conn, "patterns"):
                        src_count = self._safe_row_count(legacy_conn, "patterns")
                        logger.info(
                            "Found legacy table 'patterns' in %s (%s rows) – migrating",
                            legacy_abs, src_count,
                        )
                        if src_count > 0:
                            count = self._migrate_from_patterns_table(
                                legacy_conn, self._patterns_conn, legacy_abs
                            )
                            if count > 0:
                                self._record_migration(
                                    self._patterns_conn, migration_key,
                                    f"recovered {count} patterns from old 'patterns' table in {legacy_abs}"
                                )
                                logger.info(
                                    "Recovered %s pattern(s) from legacy 'patterns' table: %s",
                                    count, legacy_abs,
                                )
                                return

                    logger.info("No usable pattern data found in legacy DB: %s", legacy_abs)
                finally:
                    legacy_conn.close()
            except Exception as legacy_error:
                logger.warning("Legacy pattern recovery failed for %s: %s", legacy_path, legacy_error)

    def get_warmstart_power_values(
        self,
        minutes: int = 120,
        limit: int = 300,
        fallback_limit: int = 300,
    ) -> Dict[str, Any]:
        """Load warmstart readings with diagnostics and fallback beyond time window.

        Returns:
            {
              "values": List[float],
              "source": "window"|"latest_fallback"|"none"|"error",
              "diagnostics": {...}
            }
        """
        diagnostics: Dict[str, Any] = {
            "live_db": self._db_file_stats(self.db_path),
            "query": {
                "minutes": int(max(minutes, 1)),
                "limit": int(max(limit, 1)),
                "fallback_limit": int(max(fallback_limit, 1)),
            },
            "tables": [],
            "power_readings_rows": 0,
            "recent_rows": 0,
            "fallback_rows": 0,
            "reason": "",
            "recent_sql": "SELECT power_w FROM power_readings WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            "fallback_sql": "SELECT power_w FROM power_readings ORDER BY ts DESC LIMIT ?",
        }

        if not self._conn:
            diagnostics["reason"] = "storage_not_connected"
            return {"values": [], "source": "error", "diagnostics": diagnostics}

        try:
            diagnostics["tables"] = self._list_tables(self._conn)
            if not self._table_exists(self._conn, "power_readings"):
                diagnostics["reason"] = "power_readings_table_missing"
                return {"values": [], "source": "none", "diagnostics": diagnostics}

            diagnostics["power_readings_rows"] = self._safe_row_count(self._conn, "power_readings")
            if diagnostics["power_readings_rows"] <= 0:
                diagnostics["reason"] = "power_readings_empty"
                return {"values": [], "source": "none", "diagnostics": diagnostics}

            safe_minutes = int(max(minutes, 1))
            safe_limit = int(max(limit, 1))
            cutoff = (datetime.now() - timedelta(minutes=safe_minutes)).isoformat()
            logger.debug(
                "Warmstart SQL recent: %s ; cutoff=%s ; limit=%s",
                diagnostics["recent_sql"],
                cutoff,
                safe_limit,
            )

            recent_rows = self._conn.execute(
                """
                SELECT power_w FROM power_readings
                WHERE ts >= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (cutoff, safe_limit),
            ).fetchall()
            diagnostics["recent_rows"] = len(recent_rows)
            if recent_rows:
                values = [float(row[0]) for row in reversed(recent_rows)]
                diagnostics["reason"] = "window_data_found"
                return {"values": values, "source": "window", "diagnostics": diagnostics}

            fallback_rows = self._conn.execute(
                """
                SELECT power_w FROM power_readings
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(max(fallback_limit, 1)),),
            ).fetchall()
            logger.debug(
                "Warmstart SQL fallback: %s ; limit=%s",
                diagnostics["fallback_sql"],
                int(max(fallback_limit, 1)),
            )
            diagnostics["fallback_rows"] = len(fallback_rows)
            if fallback_rows:
                values = [float(row[0]) for row in reversed(fallback_rows)]
                diagnostics["reason"] = "window_empty_using_latest_fallback"
                return {"values": values, "source": "latest_fallback", "diagnostics": diagnostics}

            diagnostics["reason"] = "no_rows_found"
            return {"values": [], "source": "none", "diagnostics": diagnostics}
        except Exception as e:
            diagnostics["reason"] = f"query_failed: {e}"
            logger.error("Warmstart query failed: %s", e, exc_info=True)
            return {"values": [], "source": "error", "diagnostics": diagnostics}

    def _maybe_recover_live_from_legacy_files(self) -> None:
        """Recover live readings/detections from legacy DB files when current live DB is empty.

        This protects against update/migration scenarios where a new empty target DB exists,
        causing path-based copy migration to be skipped.
        """
        if not self._conn:
            return

        try:
            dst_readings = int((self._conn.execute("SELECT COUNT(*) FROM power_readings").fetchone() or [0])[0])
            dst_detections = int((self._conn.execute("SELECT COUNT(*) FROM detections").fetchone() or [0])[0])
            if dst_readings > 0 or dst_detections > 0:
                return
        except Exception:
            return

        legacy_candidates = self.LEGACY_LIVE_CANDIDATES

        for legacy_path in legacy_candidates:
            try:
                legacy_abs = os.path.abspath(str(legacy_path))
                if legacy_abs == os.path.abspath(self.db_path):
                    continue
                if not os.path.exists(legacy_abs):
                    continue

                migration_key = f"legacy_live_recovery:{legacy_abs}"
                if self._migration_applied(self._conn, migration_key):
                    logger.info("Live recovery already applied for %s – skipping", legacy_abs)
                    continue

                legacy_conn = sqlite3.connect(legacy_abs, timeout=5)
                try:
                    tables = {
                        str(row[0])
                        for row in legacy_conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }

                    readings_rows: List[Tuple[Any, ...]] = []
                    detections_rows: List[Tuple[Any, ...]] = []

                    if "power_readings" in tables:
                        src_readings_count = int((legacy_conn.execute("SELECT COUNT(*) FROM power_readings").fetchone() or [0])[0])
                        if src_readings_count > 0:
                            readings_rows = legacy_conn.execute(
                                "SELECT ts, power_w, phase, metadata FROM power_readings"
                            ).fetchall()

                    if "detections" in tables:
                        src_detections_count = int((legacy_conn.execute("SELECT COUNT(*) FROM detections").fetchone() or [0])[0])
                        if src_detections_count > 0:
                            detections_rows = legacy_conn.execute(
                                "SELECT ts, device_name, state, power_w, confidence, details FROM detections"
                            ).fetchall()

                    if not readings_rows and not detections_rows:
                        logger.info("Legacy live DB has no usable data: %s", legacy_abs)
                        continue

                    with self._conn:
                        if readings_rows:
                            self._conn.executemany(
                                "INSERT OR IGNORE INTO power_readings (ts, power_w, phase, metadata) VALUES (?, ?, ?, ?)",
                                readings_rows,
                            )
                        if detections_rows:
                            self._conn.executemany(
                                "INSERT OR IGNORE INTO detections (ts, device_name, state, power_w, confidence, details) VALUES (?, ?, ?, ?, ?, ?)",
                                detections_rows,
                            )

                    self._record_migration(
                        self._conn, migration_key,
                        f"recovered readings={len(readings_rows)} detections={len(detections_rows)} from {legacy_abs}"
                    )
                    logger.info(
                        "Recovered live DB from legacy file %s (readings=%s, detections=%s)",
                        legacy_abs, len(readings_rows), len(detections_rows),
                    )
                    return
                finally:
                    legacy_conn.close()
            except Exception as legacy_error:
                logger.warning("Legacy live recovery failed for %s: %s", legacy_path, legacy_error)

    def close(self) -> None:
        # Flush and commit pending writes before closing connections.
        self.flush_pending_buffers()
        
        if self._patterns_conn and self._patterns_conn is not self._conn:
            try:
                self._patterns_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                logger.warning(f"Patterns SQLite checkpoint during close failed: {e}")
            finally:
                self._patterns_conn.close()
                self._patterns_conn = None

        if self._conn:
            try:
                self._conn.commit()
                # Flush WAL changes into main DB before shutdown.
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                logger.warning(f"SQLite checkpoint during close failed: {e}")
            finally:
                self._conn.close()
                self._conn = None

    def flush_pending_buffers(self) -> None:
        """Flush batched readings/detections and force a durable commit."""
        self._flush_reading_batch()
        self._flush_detection_batch()

        if self._conn:
            try:
                self._conn.commit()
            except Exception as e:
                logger.warning("Live DB commit failed during flush: %s", e)

        if self._patterns_conn and self._patterns_conn is not self._conn:
            try:
                self._patterns_conn.commit()
            except Exception as e:
                logger.warning("Pattern DB commit failed during flush: %s", e)

    def export_data(self) -> Dict:
        """Export learned patterns and recent readings as JSON."""
        patterns = []
        readings = []
        dataset = []
        devices: List[Dict[str, Any]] = []
        recent_events: List[Dict[str, Any]] = []
        recent_labels: List[Dict[str, Any]] = []
        
        try:
            patterns = self.list_patterns(limit=500)
        except Exception as e:
            logger.warning(f"Failed to export patterns: {e}")
        
        try:
            readings = self.get_power_series(limit=1000)
        except Exception as e:
            logger.warning(f"Failed to export readings: {e}")

        try:
            dataset = build_pattern_dataset_rows(patterns)
        except Exception as e:
            logger.warning(f"Failed to export pattern dataset rows: {e}")

        try:
            if self._patterns_conn and self._table_exists(self._patterns_conn, "devices"):
                dev_rows = self._patterns_conn.execute(
                    """
                    SELECT device_id, created_at, updated_at, phase, predicted_label,
                           user_label, final_label, confirmed, confidence_avg,
                           times_seen_total, notes, active
                    FROM devices
                    WHERE active = 1
                    ORDER BY times_seen_total DESC, updated_at DESC
                    LIMIT 500
                    """
                ).fetchall()
                devices = [
                    {
                        "device_id": int(r[0]),
                        "created_at": r[1],
                        "updated_at": r[2],
                        "phase": r[3],
                        "predicted_label": r[4],
                        "user_label": r[5],
                        "final_label": r[6],
                        "confirmed": int(r[7] or 0),
                        "confidence_avg": float(r[8] or 0.0),
                        "times_seen_total": int(r[9] or 0),
                        "notes": r[10],
                        "active": int(r[11] or 0),
                    }
                    for r in dev_rows
                ]
        except Exception as e:
            logger.warning("Failed to export devices: %s", e)

        try:
            if self._patterns_conn and self._table_exists(self._patterns_conn, "events"):
                evt_rows = self._patterns_conn.execute(
                    """
                    SELECT event_id, created_at, phase, start_ts, end_ts, duration_s,
                           avg_power_w, peak_power_w, energy_wh,
                           assigned_pattern_id, assigned_device_id,
                           final_label, final_confidence
                    FROM events
                    ORDER BY event_id DESC
                    LIMIT 1000
                    """
                ).fetchall()
                recent_events = [
                    {
                        "event_id": int(r[0]),
                        "created_at": r[1],
                        "phase": r[2],
                        "start_ts": r[3],
                        "end_ts": r[4],
                        "duration_s": float(r[5] or 0.0),
                        "avg_power_w": float(r[6] or 0.0),
                        "peak_power_w": float(r[7] or 0.0),
                        "energy_wh": float(r[8] or 0.0),
                        "assigned_pattern_id": int(r[9] or 0),
                        "assigned_device_id": int(r[10] or 0),
                        "final_label": r[11],
                        "final_confidence": float(r[12] or 0.0),
                    }
                    for r in evt_rows
                ]
        except Exception as e:
            logger.warning("Failed to export events: %s", e)

        try:
            if self._patterns_conn and self._table_exists(self._patterns_conn, "user_labels"):
                label_rows = self._patterns_conn.execute(
                    """
                    SELECT id, created_at, pattern_id, device_id, old_label, new_label, comment
                    FROM user_labels
                    ORDER BY id DESC
                    LIMIT 500
                    """
                ).fetchall()
                recent_labels = [
                    {
                        "id": int(r[0]),
                        "created_at": r[1],
                        "pattern_id": int(r[2] or 0),
                        "device_id": int(r[3] or 0),
                        "old_label": r[4],
                        "new_label": r[5],
                        "comment": r[6],
                    }
                    for r in label_rows
                ]
        except Exception as e:
            logger.warning("Failed to export user labels: %s", e)
        
        return {
            "exported_at": datetime.now().isoformat(),
            "schema": {
                "live_schema_version": self.LIVE_SCHEMA_VERSION,
                "patterns_schema_version": self.PATTERNS_SCHEMA_VERSION,
            },
            "patterns": patterns,
            "readings": readings,
            "pattern_dataset": dataset,
            "devices": devices,
            "events": recent_events,
            "user_labels": recent_labels,
        }

    def list_devices(self, limit: int = 500) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "devices"):
            return []
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT device_id, created_at, updated_at, phase, predicted_label,
                       user_label, final_label, confirmed, confidence_avg,
                       times_seen_total, notes, active,
                       device_subclass, baseline_range_min_w, baseline_range_max_w
                FROM devices
                ORDER BY times_seen_total DESC, updated_at DESC
                LIMIT ?
                """,
                (int(max(limit, 1)),),
            ).fetchall()
            return [
                {
                    "device_id": int(r[0]),
                    "created_at": r[1],
                    "updated_at": r[2],
                    "phase": r[3],
                    "predicted_label": r[4],
                    "user_label": r[5],
                    "final_label": r[6],
                    "confirmed": int(r[7] or 0),
                    "confidence_avg": float(r[8] or 0.0),
                    "times_seen_total": int(r[9] or 0),
                    "notes": r[10],
                    "active": int(r[11] or 0),
                    "device_subclass": str(r[12] or ""),
                    "baseline_range_min_w": float(r[13] or 0.0),
                    "baseline_range_max_w": float(r[14] or 0.0),
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list devices: %s", e)
            return []

    def list_events(self, limit: int = 1000) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "events"):
            return []
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT event_id, created_at, phase, start_ts, end_ts, duration_s,
                       avg_power_w, peak_power_w, energy_wh,
                       assigned_pattern_id, assigned_device_id,
                       match_score, shape_score, ml_score,
                       final_label, final_confidence, rejected_reason,
                       baseline_before_w, baseline_after_w,
                      delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                        dedup_result, matched_pattern_id, similarity_score, dedup_reason,
                        prototype_score, dtw_score, hybrid_score, decision_reason
                FROM events
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (int(max(limit, 1)),),
            ).fetchall()
            return [
                {
                    "event_id": int(r[0]),
                    "created_at": r[1],
                    "phase": r[2],
                    "start_ts": r[3],
                    "end_ts": r[4],
                    "duration_s": float(r[5] or 0.0),
                    "avg_power_w": float(r[6] or 0.0),
                    "peak_power_w": float(r[7] or 0.0),
                    "energy_wh": float(r[8] or 0.0),
                    "assigned_pattern_id": int(r[9] or 0),
                    "assigned_device_id": int(r[10] or 0),
                    "match_score": float(r[11] or 0.0),
                    "shape_score": float(r[12] or 0.0),
                    "ml_score": float(r[13] or 0.0),
                    "final_label": r[14],
                    "final_confidence": float(r[15] or 0.0),
                    "rejected_reason": r[16],
                    "baseline_before_w": float(r[17] or 0.0),
                    "baseline_after_w": float(r[18] or 0.0),
                    "delta_avg_power_w": float(r[19] or 0.0),
                    "delta_peak_power_w": float(r[20] or 0.0),
                    "delta_energy_wh": float(r[21] or 0.0),
                    "dedup_result": str(r[22] or ""),
                    "matched_pattern_id": int(r[23] or 0),
                    "similarity_score": float(r[24] or 0.0),
                    "dedup_reason": str(r[25] or ""),
                    "prototype_score": float(r[26] or 0.0),
                    "dtw_score": float(r[27] or 0.0),
                    "hybrid_score": float(r[28] or 0.0),
                    "decision_reason": str(r[29] or ""),
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list events: %s", e)
            return []

    def list_event_phases(self, limit: int = 2000, event_id: int | None = None) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "event_phases"):
            return []
        try:
            params: Tuple[Any, ...]
            if event_id is not None and int(event_id) > 0:
                rows = self._patterns_conn.execute(
                    """
                    SELECT phase_id, event_id, phase_index, phase_type,
                           start_offset_s, end_offset_s, duration_s,
                           avg_power_w, peak_power_w,
                           baseline_reference_w, delta_avg_power_w, delta_peak_power_w,
                           step_into_phase_w, step_out_of_phase_w,
                           slope_in_w_per_s, slope_out_w_per_s
                    FROM event_phases
                    WHERE event_id = ?
                    ORDER BY event_id DESC, phase_index ASC
                    LIMIT ?
                    """,
                    (int(event_id), int(max(limit, 1))),
                ).fetchall()
            else:
                rows = self._patterns_conn.execute(
                    """
                    SELECT phase_id, event_id, phase_index, phase_type,
                           start_offset_s, end_offset_s, duration_s,
                           avg_power_w, peak_power_w,
                           baseline_reference_w, delta_avg_power_w, delta_peak_power_w,
                           step_into_phase_w, step_out_of_phase_w,
                           slope_in_w_per_s, slope_out_w_per_s
                    FROM event_phases
                    ORDER BY event_id DESC, phase_index ASC
                    LIMIT ?
                    """,
                    (int(max(limit, 1)),),
                ).fetchall()

            return [
                {
                    "phase_id": int(r[0] or 0),
                    "event_id": int(r[1] or 0),
                    "phase_index": int(r[2] or 0),
                    "phase_type": str(r[3] or "unknown"),
                    "start_offset_s": float(r[4] or 0.0),
                    "end_offset_s": float(r[5] or 0.0),
                    "duration_s": float(r[6] or 0.0),
                    "avg_power_w": float(r[7] or 0.0),
                    "peak_power_w": float(r[8] or 0.0),
                    "baseline_reference_w": float(r[9] or 0.0),
                    "delta_avg_power_w": float(r[10] or 0.0),
                    "delta_peak_power_w": float(r[11] or 0.0),
                    "step_into_phase_w": float(r[12] or 0.0),
                    "step_out_of_phase_w": float(r[13] or 0.0),
                    "slope_in_w_per_s": float(r[14] or 0.0),
                    "slope_out_w_per_s": float(r[15] or 0.0),
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list event phases: %s", e)
            return []

    def list_device_cycles(self, limit: int = 1000, device_id: int | None = None) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "device_cycles"):
            return []
        try:
            if device_id is not None and int(device_id) > 0:
                rows = self._patterns_conn.execute(
                    """
                    SELECT cycle_id, device_id, pattern_id, cycle_name, cycle_type,
                           created_at, updated_at, seen_count,
                           avg_total_duration_s, avg_inrush_duration_s, avg_run_duration_s,
                           avg_shutdown_duration_s, avg_delta_power_w, avg_inrush_peak_w,
                           avg_run_power_w, cycle_signature_json
                    FROM device_cycles
                    WHERE device_id = ?
                    ORDER BY seen_count DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (int(device_id), int(max(limit, 1))),
                ).fetchall()
            else:
                rows = self._patterns_conn.execute(
                    """
                    SELECT cycle_id, device_id, pattern_id, cycle_name, cycle_type,
                           created_at, updated_at, seen_count,
                           avg_total_duration_s, avg_inrush_duration_s, avg_run_duration_s,
                           avg_shutdown_duration_s, avg_delta_power_w, avg_inrush_peak_w,
                           avg_run_power_w, cycle_signature_json
                    FROM device_cycles
                    ORDER BY seen_count DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (int(max(limit, 1)),),
                ).fetchall()

            return [
                {
                    "cycle_id": int(r[0] or 0),
                    "device_id": int(r[1] or 0),
                    "pattern_id": int(r[2] or 0),
                    "cycle_name": str(r[3] or ""),
                    "cycle_type": str(r[4] or "unknown"),
                    "created_at": r[5],
                    "updated_at": r[6],
                    "seen_count": int(r[7] or 0),
                    "avg_total_duration_s": float(r[8] or 0.0),
                    "avg_inrush_duration_s": float(r[9] or 0.0),
                    "avg_run_duration_s": float(r[10] or 0.0),
                    "avg_shutdown_duration_s": float(r[11] or 0.0),
                    "avg_delta_power_w": float(r[12] or 0.0),
                    "avg_inrush_peak_w": float(r[13] or 0.0),
                    "avg_run_power_w": float(r[14] or 0.0),
                    "cycle_signature_json": str(r[15] or "{}"),
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list device cycles: %s", e)
            return []

    def list_classification_logs(self, limit: int = 1000) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "classification_log"):
            return []
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT id, created_at, event_id, pattern_id, device_id,
                       prototype_label, prototype_score,
                       shape_label, shape_score,
                       ml_label, ml_confidence,
                       rule_label, rule_reason,
                       final_label, final_confidence, decision_source
                FROM classification_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(max(limit, 1)),),
            ).fetchall()
            return [
                {
                    "id": int(r[0]),
                    "created_at": r[1],
                    "event_id": int(r[2] or 0),
                    "pattern_id": int(r[3] or 0),
                    "device_id": int(r[4] or 0),
                    "prototype_label": r[5],
                    "prototype_score": float(r[6] or 0.0),
                    "shape_label": r[7],
                    "shape_score": float(r[8] or 0.0),
                    "ml_label": r[9],
                    "ml_confidence": float(r[10] or 0.0),
                    "rule_label": r[11],
                    "rule_reason": r[12],
                    "final_label": r[13],
                    "final_confidence": float(r[14] or 0.0),
                    "decision_source": r[15],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list classification logs: %s", e)
            return []

    def list_user_labels(self, limit: int = 1000) -> List[Dict[str, Any]]:
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "user_labels"):
            return []
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT id, created_at, pattern_id, device_id, old_label, new_label,
                       confirmed_by_user, comment
                FROM user_labels
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(max(limit, 1)),),
            ).fetchall()
            return [
                {
                    "id": int(r[0]),
                    "created_at": r[1],
                    "pattern_id": int(r[2] or 0),
                    "device_id": int(r[3] or 0),
                    "old_label": r[4],
                    "new_label": r[5],
                    "confirmed_by_user": int(r[6] or 0),
                    "comment": r[7],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to list user labels: %s", e)
            return []
    
    def import_data(self, data: Dict) -> Dict:
        """Import patterns and readings from JSON export."""
        if not self._conn or not self._patterns_conn:
            return {"ok": False, "error": "storage not connected"}
        
        patterns_imported = 0
        readings_imported = 0
        errors = []
        
        try:
            # Import patterns (best-effort rich import; keeps user labels and learned delta features)
            patterns = data.get("patterns", [])
            for pattern in patterns:
                try:
                    now = datetime.now().isoformat()
                    first_seen, last_seen = self._normalize_seen_bounds(
                        first_seen=str(pattern.get("first_seen", now)),
                        last_seen=str(pattern.get("last_seen", now)),
                        fallback_start=str(pattern.get("first_seen", now)),
                        fallback_end=str(pattern.get("last_seen", now)),
                    )
                    with self._patterns_conn:
                        self._patterns_conn.execute(
                            """
                            INSERT OR REPLACE INTO learned_patterns (
                                id, created_at, updated_at, first_seen, last_seen, seen_count,
                                avg_power_w, peak_power_w, duration_s, energy_wh,
                                suggestion_type, user_label, status,
                                phase, phase_mode, candidate_name, is_confirmed,
                                profile_points_json, delta_profile_points_json,
                                baseline_before_w_avg, baseline_after_w_avg,
                                delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                                curve_hash, shape_signature,
                                device_group_id, mode_key, quality_score_avg,
                                occurrence_count
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(pattern.get("id", 0)) or None,  # Let DB auto-gen if 0
                                pattern.get("created_at", now),
                                now,
                                first_seen,
                                last_seen,
                                max(int(pattern.get("seen_count", 1)), 1),
                                float(pattern.get("avg_power_w", 0.0)),
                                float(pattern.get("peak_power_w", 0.0)),
                                float(pattern.get("duration_s", 0.0)),
                                float(pattern.get("energy_wh", 0.0)),
                                str(pattern.get("suggestion_type", "unknown")),
                                str(pattern.get("user_label", "")) or None,
                                str(pattern.get("status", "active")),
                                str(pattern.get("phase", "L1")),
                                str(pattern.get("phase_mode", "unknown")),
                                str(pattern.get("candidate_name", "")) or None,
                                1 if bool(pattern.get("is_confirmed", False)) else 0,
                                json.dumps(self._normalize_profile_points(pattern.get("profile_points", []))),
                                json.dumps(self._normalize_profile_points(pattern.get("delta_profile_points", []))),
                                float(pattern.get("baseline_before_w_avg", pattern.get("baseline_before_w", 0.0)) or 0.0),
                                float(pattern.get("baseline_after_w_avg", pattern.get("baseline_after_w", 0.0)) or 0.0),
                                float(pattern.get("delta_avg_power_w", 0.0) or 0.0),
                                float(pattern.get("delta_peak_power_w", 0.0) or 0.0),
                                float(pattern.get("delta_energy_wh", 0.0) or 0.0),
                                str(pattern.get("curve_hash", "") or ""),
                                str(pattern.get("shape_signature", "") or ""),
                                str(pattern.get("device_group_id", "") or ""),
                                str(pattern.get("mode_key", "") or ""),
                                float(pattern.get("quality_score_avg", 0.5) or 0.5),
                                int(pattern.get("occurrence_count", pattern.get("seen_count", 1)) or 1),
                            ),
                        )
                    patterns_imported += 1
                except Exception as e:
                    logger.debug(f"Skipped pattern import: {e}")
                    errors.append(f"pattern {pattern.get('id')}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Pattern import failed: {e}", exc_info=True)
            errors.append(f"pattern batch: {e}")

        try:
            # Import devices (optional)
            devices = data.get("devices", [])
            for dev in devices:
                try:
                    now = datetime.now().isoformat()
                    with self._patterns_conn:
                        self._patterns_conn.execute(
                            """
                            INSERT OR REPLACE INTO devices (
                                device_id, created_at, updated_at, phase, predicted_label,
                                user_label, final_label, confirmed, confidence_avg,
                                times_seen_total, notes, active
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(dev.get("device_id", 0)) or None,
                                str(dev.get("created_at", now)),
                                now,
                                str(dev.get("phase", "")),
                                str(dev.get("predicted_label", "")) or None,
                                str(dev.get("user_label", "")) or None,
                                str(dev.get("final_label", "")) or None,
                                int(dev.get("confirmed", 0) or 0),
                                float(dev.get("confidence_avg", 0.0) or 0.0),
                                int(dev.get("times_seen_total", 0) or 0),
                                str(dev.get("notes", "")) or None,
                                int(dev.get("active", 1) or 1),
                            ),
                        )
                except Exception as e:
                    errors.append(f"device {dev.get('device_id')}: {e}")
                    continue
        except Exception as e:
            errors.append(f"devices batch: {e}")
        
        try:
            # Import readings
            readings = data.get("readings", [])
            batch = []
            for reading in readings:
                try:
                    ts = reading.get("timestamp", "")
                    power = float(reading.get("power_w", 0.0))
                    phase = str(reading.get("phase", "TOTAL"))
                    metadata = reading.get("phases", {})
                    
                    batch.append((
                        ts,
                        power,
                        phase,
                        json.dumps({"phase_powers_w": metadata}),
                    ))
                except Exception as e:
                    logger.debug(f"Skipped reading: {e}")
                    continue
            
            if batch:
                with self._conn:
                    self._conn.executemany(
                        "INSERT INTO power_readings (ts, power_w, phase, metadata) VALUES (?, ?, ?, ?)",
                        batch,
                    )
                readings_imported = len(batch)
        except Exception as e:
            logger.error(f"Reading import failed: {e}", exc_info=True)
            errors.append(f"readings batch: {e}")

        try:
            # Import events (optional, subset)
            events = data.get("events", [])
            for ev in events:
                try:
                    with self._patterns_conn:
                        self._patterns_conn.execute(
                            """
                            INSERT OR REPLACE INTO events (
                                event_id, created_at, phase, start_ts, end_ts, duration_s,
                                avg_power_w, peak_power_w, energy_wh,
                                assigned_pattern_id, assigned_device_id,
                                final_label, final_confidence
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(ev.get("event_id", 0)) or None,
                                str(ev.get("created_at", datetime.now().isoformat())),
                                str(ev.get("phase", "L1")),
                                str(ev.get("start_ts", "")),
                                str(ev.get("end_ts", "")),
                                float(ev.get("duration_s", 0.0) or 0.0),
                                float(ev.get("avg_power_w", 0.0) or 0.0),
                                float(ev.get("peak_power_w", 0.0) or 0.0),
                                float(ev.get("energy_wh", 0.0) or 0.0),
                                int(ev.get("assigned_pattern_id", 0) or 0) or None,
                                int(ev.get("assigned_device_id", 0) or 0) or None,
                                str(ev.get("final_label", "")) or None,
                                float(ev.get("final_confidence", 0.0) or 0.0),
                            ),
                        )
                except Exception as e:
                    errors.append(f"event {ev.get('event_id')}: {e}")
                    continue
        except Exception as e:
            errors.append(f"events batch: {e}")

        try:
            # Import user label history (optional)
            labels = data.get("user_labels", [])
            if labels and self._table_exists(self._patterns_conn, "user_labels"):
                for item in labels:
                    try:
                        with self._patterns_conn:
                            self._patterns_conn.execute(
                                """
                                INSERT OR REPLACE INTO user_labels (
                                    id, created_at, pattern_id, device_id, old_label, new_label,
                                    confirmed_by_user, comment
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    int(item.get("id", 0)) or None,
                                    str(item.get("created_at", datetime.now().isoformat())),
                                    int(item.get("pattern_id", 0) or 0) or None,
                                    int(item.get("device_id", 0) or 0) or None,
                                    str(item.get("old_label", "")) or None,
                                    str(item.get("new_label", "")) or None,
                                    1,
                                    str(item.get("comment", "")) or None,
                                ),
                            )
                    except Exception as e:
                        errors.append(f"user_label {item.get('id')}: {e}")
                        continue
        except Exception as e:
            errors.append(f"user_labels batch: {e}")

        self._maybe_repair_pattern_timestamps(force=True)
        
        return {
            "ok": True,
            "patterns_imported": patterns_imported,
            "readings_imported": readings_imported,
            "errors": errors,
        }

    def export_training_dataset_jsonl(self, limit: int = 5000) -> str:
        """Export cycle events with labels as JSONL for downstream ML training."""
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "events"):
            return ""
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT event_id, created_at, phase, duration_s, avg_power_w, peak_power_w,
                       energy_wh, assigned_pattern_id, assigned_device_id, final_label,
                       final_confidence, resampled_points_json
                FROM events
                WHERE COALESCE(final_label, '') != ''
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            lines: List[str] = []
            for r in rows:
                payload = {
                    "event_id": int(r[0]),
                    "created_at": r[1],
                    "phase": r[2],
                    "duration_s": float(r[3] or 0.0),
                    "avg_power_w": float(r[4] or 0.0),
                    "peak_power_w": float(r[5] or 0.0),
                    "energy_wh": float(r[6] or 0.0),
                    "pattern_id": int(r[7] or 0),
                    "device_id": int(r[8] or 0),
                    "label": r[9],
                    "confidence": float(r[10] or 0.0),
                    "resampled_points": json.loads(str(r[11] or "[]")),
                }
                lines.append(json.dumps(payload, ensure_ascii=True))
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to export JSONL training dataset: %s", e)
            return ""

    def export_features_csv(self, limit: int = 5000) -> str:
        """Export labeled event-level features as CSV for model experimentation."""
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "events"):
            return ""
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT event_id, created_at, phase, duration_s, avg_power_w, peak_power_w,
                       energy_wh, match_score, shape_score, ml_score,
                       final_label, final_confidence
                FROM events
                WHERE COALESCE(final_label, '') != ''
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                "event_id", "created_at", "phase", "duration_s", "avg_power_w", "peak_power_w",
                "energy_wh", "match_score", "shape_score", "ml_score", "final_label", "final_confidence",
            ])
            for r in rows:
                writer.writerow([
                    int(r[0]), r[1], r[2], float(r[3] or 0.0), float(r[4] or 0.0), float(r[5] or 0.0),
                    float(r[6] or 0.0), float(r[7] or 0.0), float(r[8] or 0.0), float(r[9] or 0.0),
                    r[10], float(r[11] or 0.0),
                ])
            return buffer.getvalue()
        except Exception as e:
            logger.warning("Failed to export feature CSV: %s", e)
            return ""

    def _create_tables(self) -> None:
        if not self._conn:
            return

        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS power_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    power_w REAL NOT NULL,
                    phase TEXT,
                    metadata TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    power_w REAL NOT NULL,
                    confidence REAL NOT NULL,
                    details TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_power_readings_ts ON power_readings(ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detections_ts ON detections(ts)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS migration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE NOT NULL,
                    executed_at TEXT NOT NULL,
                    details TEXT
                )
                """
            )
            self._ensure_schema_version(self._conn, self.LIVE_SCHEMA_VERSION)

        if not self._patterns_conn:
            return

        with self._patterns_conn:
            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id INTEGER PRIMARY KEY,
                    device_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    phase TEXT,
                    phase_mode TEXT,
                    avg_power_w REAL,
                    peak_power_w REAL,
                    duration_s REAL,
                    energy_wh REAL,
                    stability_score REAL,
                    confidence_score REAL,
                    frequency_per_day REAL,
                    typical_interval_s REAL,
                    quality_score_avg REAL,
                    suggestion_type TEXT,
                    candidate_name TEXT,
                    status TEXT,
                    is_confirmed INTEGER DEFAULT 0,
                    profile_points_json TEXT,
                    shape_vector_json TEXT,
                    prototype_hash TEXT,
                    num_substates INTEGER DEFAULT 0,
                    step_count INTEGER DEFAULT 0,
                    plateau_count INTEGER DEFAULT 0,
                    shape_similarity_score REAL DEFAULT 0.0,
                    cluster_similarity_score REAL DEFAULT 0.0
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_patterns_seen ON patterns(last_seen)"
            )
            self._ensure_column(self._patterns_conn, "patterns", "baseline_before_w_avg", "REAL")
            self._ensure_column(self._patterns_conn, "patterns", "baseline_after_w_avg", "REAL")
            self._ensure_column(self._patterns_conn, "patterns", "delta_avg_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "patterns", "delta_peak_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "patterns", "delta_energy_wh", "REAL")
            self._ensure_column(self._patterns_conn, "patterns", "delta_profile_points_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "patterns", "delta_shape_vector_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "patterns", "curve_hash", "TEXT DEFAULT ''")
            self._ensure_column(self._patterns_conn, "patterns", "shape_signature", "TEXT DEFAULT ''")
            self._ensure_column(self._patterns_conn, "patterns", "occurrence_count", "INTEGER DEFAULT 1")
            self._ensure_column(self._patterns_conn, "patterns", "device_group_id", "TEXT")
            self._ensure_column(self._patterns_conn, "patterns", "mode_key", "TEXT")

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    avg_power_w REAL NOT NULL,
                    peak_power_w REAL NOT NULL,
                    duration_s REAL NOT NULL,
                    energy_wh REAL NOT NULL,
                    suggestion_type TEXT NOT NULL,
                    user_label TEXT,
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learned_patterns_seen ON learned_patterns(last_seen)"
            )

            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_active_phases", "REAL DEFAULT 1.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "phase_mode", "TEXT DEFAULT 'unknown'")
            self._ensure_column(self._patterns_conn, "learned_patterns", "phase", "TEXT DEFAULT 'L1'")  # Explicit phase attribution (L1/L2/L3)
            
            # Advanced features inspired by NILM research (Torch-NILM concepts)
            self._ensure_column(self._patterns_conn, "learned_patterns", "power_variance", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "rise_rate_w_per_s", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "fall_rate_w_per_s", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "duty_cycle", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "peak_to_avg_ratio", "REAL DEFAULT 1.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "num_substates", "INTEGER DEFAULT 0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "step_count", "INTEGER DEFAULT 0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "has_heating_pattern", "INTEGER DEFAULT 0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "has_motor_pattern", "INTEGER DEFAULT 0")
            
            # Multi-mode learning (intelligent!)
            self._ensure_column(self._patterns_conn, "learned_patterns", "operating_modes", "TEXT DEFAULT ''")  # JSON
            self._ensure_column(self._patterns_conn, "learned_patterns", "has_multiple_modes", "INTEGER DEFAULT 0")
            
            # Temporal pattern tracking (for anomaly detection and prediction)
            self._ensure_column(self._patterns_conn, "learned_patterns", "typical_interval_s", "REAL DEFAULT 0.0")  # Avg time between cycles
            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_hour_of_day", "REAL DEFAULT 12.0")  # Typical hour (0-24)
            self._ensure_column(self._patterns_conn, "learned_patterns", "last_intervals_json", "TEXT DEFAULT '[]'")  # Last N intervals
            self._ensure_column(self._patterns_conn, "learned_patterns", "hour_distribution_json", "TEXT DEFAULT '{}'")  # Hour frequency map
            self._ensure_column(self._patterns_conn, "learned_patterns", "profile_points_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "learned_patterns", "quality_score_avg", "REAL DEFAULT 0.5")
            self._ensure_column(self._patterns_conn, "learned_patterns", "device_id", "INTEGER")
            self._ensure_column(self._patterns_conn, "learned_patterns", "confidence_score", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "frequency_per_day", "REAL DEFAULT 0.0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "candidate_name", "TEXT")
            self._ensure_column(self._patterns_conn, "learned_patterns", "is_confirmed", "INTEGER DEFAULT 0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "shape_vector_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "learned_patterns", "prototype_hash", "TEXT DEFAULT ''")
            self._ensure_column(self._patterns_conn, "learned_patterns", "baseline_before_w_avg", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "baseline_after_w_avg", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "delta_avg_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "delta_peak_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "delta_energy_wh", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "delta_profile_points_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "learned_patterns", "delta_shape_vector_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "learned_patterns", "plateau_count", "INTEGER DEFAULT 0")
            self._ensure_column(self._patterns_conn, "learned_patterns", "curve_hash", "TEXT DEFAULT ''")
            self._ensure_column(self._patterns_conn, "learned_patterns", "shape_signature", "TEXT DEFAULT ''")
            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_delta_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_duration_s", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_peak_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "avg_inrush_duration_s", "REAL")
            self._ensure_column(self._patterns_conn, "learned_patterns", "occurrence_count", "INTEGER DEFAULT 1")
            self._ensure_column(self._patterns_conn, "learned_patterns", "device_group_id", "TEXT")
            self._ensure_column(self._patterns_conn, "learned_patterns", "mode_key", "TEXT")
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learned_patterns_curve_hash ON learned_patterns(curve_hash)"
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learned_patterns_group_mode ON learned_patterns(device_group_id, mode_key)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    phase TEXT,
                    predicted_label TEXT,
                    user_label TEXT,
                    final_label TEXT,
                    confirmed INTEGER DEFAULT 0,
                    confidence_avg REAL DEFAULT 0.0,
                    times_seen_total INTEGER DEFAULT 0,
                    notes TEXT,
                    active INTEGER DEFAULT 1
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_devices_final_label_phase ON devices(final_label, phase)"
            )
            self._ensure_column(self._patterns_conn, "devices", "device_subclass", "TEXT")
            self._ensure_column(self._patterns_conn, "devices", "baseline_range_min_w", "REAL")
            self._ensure_column(self._patterns_conn, "devices", "baseline_range_max_w", "REAL")

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    phase TEXT,
                    start_ts TEXT,
                    end_ts TEXT,
                    duration_s REAL,
                    avg_power_w REAL,
                    peak_power_w REAL,
                    energy_wh REAL,
                    raw_points_json TEXT,
                    resampled_points_json TEXT,
                    assigned_pattern_id INTEGER,
                    assigned_device_id INTEGER,
                    match_score REAL,
                    shape_score REAL,
                    ml_score REAL,
                    final_label TEXT,
                    final_confidence REAL,
                    rejected_reason TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)"
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_pattern ON events(assigned_pattern_id)"
            )
            self._ensure_column(self._patterns_conn, "events", "baseline_before_w", "REAL")
            self._ensure_column(self._patterns_conn, "events", "baseline_after_w", "REAL")
            self._ensure_column(self._patterns_conn, "events", "delta_avg_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "events", "delta_peak_power_w", "REAL")
            self._ensure_column(self._patterns_conn, "events", "delta_energy_wh", "REAL")
            self._ensure_column(self._patterns_conn, "events", "delta_points_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "events", "delta_resampled_points_json", "TEXT DEFAULT '[]'")
            self._ensure_column(self._patterns_conn, "events", "start_time", "TEXT")
            self._ensure_column(self._patterns_conn, "events", "end_time", "TEXT")
            self._ensure_column(self._patterns_conn, "events", "sample_start_index", "INTEGER")
            self._ensure_column(self._patterns_conn, "events", "sample_end_index", "INTEGER")
            self._ensure_column(self._patterns_conn, "events", "raw_trace_id", "TEXT")
            self._ensure_column(self._patterns_conn, "events", "dedup_result", "TEXT")
            self._ensure_column(self._patterns_conn, "events", "matched_pattern_id", "INTEGER")
            self._ensure_column(self._patterns_conn, "events", "similarity_score", "REAL")
            self._ensure_column(self._patterns_conn, "events", "dedup_reason", "TEXT")
            self._ensure_column(self._patterns_conn, "events", "prototype_score", "REAL")
            self._ensure_column(self._patterns_conn, "events", "dtw_score", "REAL")
            self._ensure_column(self._patterns_conn, "events", "hybrid_score", "REAL")
            self._ensure_column(self._patterns_conn, "events", "decision_reason", "TEXT")

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pattern_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_id INTEGER NOT NULL,
                    feature_version TEXT NOT NULL,
                    power_variance REAL,
                    power_std REAL,
                    power_cv REAL,
                    power_range REAL,
                    num_substates INTEGER,
                    step_count INTEGER,
                    max_step_w REAL,
                    avg_step_w REAL,
                    plateau_count INTEGER,
                    dominant_power_levels_json TEXT,
                    substate_durations_json TEXT,
                    substate_power_levels_json TEXT,
                    rise_rate_w_per_s REAL,
                    fall_rate_w_per_s REAL,
                    shape_embedding_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pattern_features_pattern ON pattern_features(pattern_id, created_at DESC)"
            )
            self._ensure_column(self._patterns_conn, "pattern_features", "delta_power_std", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "delta_power_cv", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "delta_power_range", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "dominant_delta_levels_json", "TEXT")
            self._ensure_column(self._patterns_conn, "pattern_features", "inrush_peak_w", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "inrush_ratio", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "settling_time_s", "REAL")
            self._ensure_column(self._patterns_conn, "pattern_features", "delta_shape_embedding_json", "TEXT")

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_phases (
                    phase_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    phase_index INTEGER NOT NULL,
                    phase_type TEXT NOT NULL,
                    start_offset_s REAL,
                    end_offset_s REAL,
                    duration_s REAL,
                    avg_power_w REAL,
                    peak_power_w REAL,
                    baseline_reference_w REAL,
                    delta_avg_power_w REAL,
                    delta_peak_power_w REAL,
                    step_into_phase_w REAL,
                    step_out_of_phase_w REAL,
                    slope_in_w_per_s REAL,
                    slope_out_w_per_s REAL,
                    phase_points_json TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_phases_event ON event_phases(event_id, phase_index)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_cycles (
                    cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER NOT NULL,
                    pattern_id INTEGER,
                    cycle_name TEXT,
                    cycle_type TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    seen_count INTEGER DEFAULT 0,
                    avg_total_duration_s REAL,
                    avg_inrush_duration_s REAL,
                    avg_run_duration_s REAL,
                    avg_shutdown_duration_s REAL,
                    avg_delta_power_w REAL,
                    avg_inrush_peak_w REAL,
                    avg_run_power_w REAL,
                    cycle_signature_json TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_cycles_unique ON device_cycles(device_id, cycle_type)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS classification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_id INTEGER,
                    pattern_id INTEGER,
                    device_id INTEGER,
                    prototype_label TEXT,
                    prototype_score REAL,
                    shape_label TEXT,
                    shape_score REAL,
                    ml_label TEXT,
                    ml_confidence REAL,
                    rule_label TEXT,
                    rule_reason TEXT,
                    final_label TEXT,
                    final_confidence REAL,
                    decision_source TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_classification_log_created ON classification_log(created_at)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    pattern_id INTEGER,
                    device_id INTEGER,
                    old_label TEXT,
                    new_label TEXT,
                    confirmed_by_user INTEGER DEFAULT 1,
                    comment TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_labels_pattern ON user_labels(pattern_id, created_at DESC)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pattern_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_id INTEGER NOT NULL,
                    snapshot_ts TEXT NOT NULL,
                    seen_count INTEGER,
                    avg_power_w REAL,
                    peak_power_w REAL,
                    duration_s REAL,
                    confidence_score REAL,
                    profile_points_json TEXT,
                    quality_score_avg REAL
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pattern_history_pattern ON pattern_history(pattern_id, snapshot_ts DESC)"
            )

            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS label_phase_locks (
                    label_key TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_label_phase_locks_phase ON label_phase_locks(phase)"
            )

            # Migration tracking table – one row per migration event (unique key prevents re-runs)
            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS migration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE NOT NULL,
                    executed_at TEXT NOT NULL,
                    details TEXT
                )
                """
            )

            # Training-filter audit log – records every accept/reject decision so
            # operators can inspect why events were or were not used for learning.
            self._patterns_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS training_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_id INTEGER,
                    accepted INTEGER NOT NULL DEFAULT 0,
                    rejected INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    label TEXT
                )
                """
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_log_created ON training_log(created_at)"
            )
            self._patterns_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_log_event ON training_log(event_id)"
            )
            self._ensure_column(self._patterns_conn, "training_log", "dedup_result", "TEXT")
            self._ensure_column(self._patterns_conn, "training_log", "matched_pattern_id", "INTEGER")
            self._ensure_column(self._patterns_conn, "training_log", "similarity_score", "REAL")
            self._ensure_column(self._patterns_conn, "training_log", "dedup_reason", "TEXT")
            self._ensure_column(self._patterns_conn, "training_log", "prototype_score", "REAL")
            self._ensure_column(self._patterns_conn, "training_log", "shape_score", "REAL")
            self._ensure_column(self._patterns_conn, "training_log", "ml_score", "REAL")
            self._ensure_column(self._patterns_conn, "training_log", "final_score", "REAL")
            self._ensure_column(self._patterns_conn, "training_log", "decision_reason", "TEXT")
            self._ensure_column(self._patterns_conn, "training_log", "agreement_flag", "INTEGER DEFAULT 0")

            self._ensure_schema_version(self._patterns_conn, self.PATTERNS_SCHEMA_VERSION)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_def: str,
    ) -> None:
        """Add a missing column in a backward-compatible way."""
        try:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            existing = {str(row[1]) for row in rows}
            if column_name in existing:
                return
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
        except Exception as e:
            logger.warning(f"Failed to ensure column {table_name}.{column_name}: {e}")

    @staticmethod
    def _normalize_profile_points(points: object) -> List[Dict[str, float]]:
        """Return a compact, safe profile point list for DB/UI usage."""
        if not isinstance(points, list):
            return []

        out: List[Dict[str, float]] = []
        for item in points:
            if not isinstance(item, dict):
                continue
            try:
                t_s = float(item.get("t_s", 0.0))
                p_w = float(item.get("power_w", 0.0))
                t_norm = float(item.get("t_norm", 0.0))
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "t_s": round(max(t_s, 0.0), 3),
                    "power_w": round(p_w, 3),
                    "t_norm": round(min(max(t_norm, 0.0), 1.0), 6),
                }
            )

        return out[:128]

    @staticmethod
    def _profile_shape_distance(existing: Dict, candidate: Dict, sample_count: int = 16) -> float | None:
        """Compare normalized profile curves if both patterns provide profile points."""
        existing_points = SQLiteStore._normalize_profile_points(existing.get("delta_profile_points", []))
        if len(existing_points) < 2:
            existing_points = SQLiteStore._normalize_profile_points(existing.get("profile_points", []))
        candidate_points = SQLiteStore._normalize_profile_points(candidate.get("delta_profile_points", []))
        if len(candidate_points) < 2:
            candidate_points = SQLiteStore._normalize_profile_points(candidate.get("profile_points", []))
        if len(existing_points) < 2 or len(candidate_points) < 2:
            return None

        def interpolate(points: List[Dict[str, float]], t_norm: float) -> float:
            left = points[0]
            for idx in range(1, len(points)):
                right = points[idx]
                if right["t_norm"] >= t_norm:
                    span = max(right["t_norm"] - left["t_norm"], 1e-6)
                    alpha = (t_norm - left["t_norm"]) / span
                    return left["power_w"] * (1.0 - alpha) + right["power_w"] * alpha
                left = right
            return points[-1]["power_w"]

        existing_peak = max(float(existing.get("peak_power_w", 1.0)), 1.0)
        candidate_peak = max(float(candidate.get("peak_power_w", 1.0)), 1.0)
        total = 0.0
        for i in range(sample_count):
            t = i / max(sample_count - 1, 1)
            ev = interpolate(existing_points, t) / existing_peak
            cv = interpolate(candidate_points, t) / candidate_peak
            total += abs(ev - cv)
        return min(total / float(sample_count), 1.0)

    @staticmethod
    def _learning_quality_score(cycle: Dict) -> float:
        """Estimate cycle quality (0..1) to suppress noisy self-learning updates."""
        score = 1.0
        avg_power = float(cycle.get("avg_power_w", 0.0))
        duration_s = float(cycle.get("duration_s", 0.0))
        duty_cycle = float(cycle.get("duty_cycle", 0.0))
        peak_to_avg = float(cycle.get("peak_to_avg_ratio", 1.0))
        num_substates = int(cycle.get("num_substates", 0))

        if avg_power < 30.0:
            score -= 0.22
        if duration_s < 8.0:
            score -= 0.25
        if peak_to_avg > 6.0:
            score -= 0.18
        if duration_s > 600 and (duty_cycle < 0.03 or duty_cycle > 0.98):
            score -= 0.12
        if num_substates > 10:
            score -= 0.10

        profile_points = SQLiteStore._normalize_profile_points(cycle.get("profile_points", []))
        if profile_points and len(profile_points) < 6:
            score -= 0.08

        baseline_quality = SQLiteStore._safe_float(cycle.get("baseline_quality_score"), 0.5)
        if baseline_quality < SQLiteStore.LEARNING_PARAMS["baseline_quality_min"]:
            score -= 0.30
        elif baseline_quality < 0.45:
            score -= 0.14

        delta_energy = SQLiteStore._safe_float(cycle.get("delta_energy_wh"), 0.0)
        if delta_energy < SQLiteStore.LEARNING_PARAMS["delta_energy_min_wh"]:
            score -= 0.20

        return max(0.0, min(1.0, score))

    @classmethod
    def _iso_min(cls, a: str, b: str) -> str:
        a_dt = cls._parse_iso_timestamp(a)
        b_dt = cls._parse_iso_timestamp(b)
        if a_dt and b_dt:
            return a if a_dt <= b_dt else b
        return str(a or b or "")

    @classmethod
    def _iso_max(cls, a: str, b: str) -> str:
        a_dt = cls._parse_iso_timestamp(a)
        b_dt = cls._parse_iso_timestamp(b)
        if a_dt and b_dt:
            return a if a_dt >= b_dt else b
        return str(a or b or "")

    @classmethod
    def _normalize_seen_bounds(
        cls,
        first_seen: str,
        last_seen: str,
        fallback_start: str,
        fallback_end: str,
    ) -> Tuple[str, str]:
        first = str(first_seen or fallback_start or fallback_end or datetime.now().isoformat())
        last = str(last_seen or fallback_end or fallback_start or first)
        first_dt = cls._parse_iso_timestamp(first)
        last_dt = cls._parse_iso_timestamp(last)
        if first_dt and last_dt and last_dt < first_dt:
            first, last = last, first
        return first, last

    @staticmethod
    def _resample_profile_points(points: List[Dict[str, float]], sample_count: int = 32) -> List[float]:
        """Resample normalized profile points to a fixed vector length."""
        normalized = SQLiteStore._normalize_profile_points(points)
        if len(normalized) < 2:
            return []

        def interpolate(t_norm: float) -> float:
            left = normalized[0]
            for idx in range(1, len(normalized)):
                right = normalized[idx]
                if right["t_norm"] >= t_norm:
                    span = max(right["t_norm"] - left["t_norm"], 1e-6)
                    alpha = (t_norm - left["t_norm"]) / span
                    return left["power_w"] * (1.0 - alpha) + right["power_w"] * alpha
                left = right
            return normalized[-1]["power_w"]

        out: List[float] = []
        for idx in range(max(sample_count, 8)):
            t = idx / max(sample_count - 1, 1)
            out.append(round(float(interpolate(t)), 3))
        return out

    @staticmethod
    def _median(values: List[float], default: float = 0.0) -> float:
        clean = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
        if not clean:
            return float(default)
        mid = len(clean) // 2
        if len(clean) % 2 == 1:
            return float(clean[mid])
        return float((clean[mid - 1] + clean[mid]) / 2.0)

    @staticmethod
    def _profile_points_with_time(points: object, duration_s: float) -> List[Dict[str, float]]:
        normalized = SQLiteStore._normalize_profile_points(points)
        if not normalized:
            return []

        has_span = False
        if len(normalized) >= 2:
            first_t = float(normalized[0].get("t_s", 0.0) or 0.0)
            last_t = float(normalized[-1].get("t_s", 0.0) or 0.0)
            has_span = abs(last_t - first_t) > 1e-6

        total_duration = max(float(duration_s or 0.0), 1.0)
        count = max(len(normalized) - 1, 1)
        out: List[Dict[str, float]] = []
        for idx, point in enumerate(normalized):
            if has_span:
                t_s = max(float(point.get("t_s", 0.0) or 0.0), 0.0)
                t_norm = min(max(t_s / total_duration, 0.0), 1.0)
            else:
                t_norm = idx / count
                t_s = t_norm * total_duration
            out.append(
                {
                    "t_s": round(t_s, 3),
                    "t_norm": round(t_norm, 6),
                    "power_w": round(float(point.get("power_w", 0.0) or 0.0), 3),
                }
            )
        return out

    @classmethod
    def _augment_cycle_baseline_delta(cls, cycle: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(cycle)
        duration_s = float(enriched.get("duration_s", 0.0) or 0.0)
        points = cls._profile_points_with_time(enriched.get("profile_points", []), duration_s)

        if not points:
            baseline_before = float(enriched.get("baseline_before_w", 0.0) or 0.0)
            baseline_after = float(enriched.get("baseline_after_w", baseline_before) or baseline_before)
            delta_avg = float(enriched.get("delta_avg_power_w", float(enriched.get("avg_power_w", 0.0) or 0.0) - baseline_before) or 0.0)
            delta_peak = float(enriched.get("delta_peak_power_w", float(enriched.get("peak_power_w", 0.0) or 0.0) - baseline_before) or 0.0)
            delta_energy = float(enriched.get("delta_energy_wh", max(delta_avg, 0.0) * max(duration_s, 0.0) / 3600.0) or 0.0)
            plateau_count = int(enriched.get("plateau_count", enriched.get("num_substates", 0)) or 0)
            enriched.update(
                {
                    "profile_points": points,
                    "baseline_before_w": baseline_before,
                    "baseline_after_w": baseline_after,
                    "delta_avg_power_w": delta_avg,
                    "delta_peak_power_w": delta_peak,
                    "delta_energy_wh": delta_energy,
                    "delta_profile_points": [],
                    "delta_resampled_points": [],
                    "delta_shape_vector": [],
                    "inrush_peak_w": max(delta_peak, 0.0),
                    "inrush_ratio": max(delta_peak, 0.0) / max(abs(delta_avg), 1.0),
                    "settling_time_s": 0.0,
                    "plateau_count": plateau_count,
                }
            )
            return enriched

        head_count = max(1, min(len(points) // 5, 6))
        tail_count = max(1, min(len(points) // 5, 6))
        head_values = [p["power_w"] for p in points[:head_count]]
        tail_values = [p["power_w"] for p in points[-tail_count:]]
        baseline_before = float(enriched.get("baseline_before_w", cls._median(head_values, default=0.0)) or 0.0)
        baseline_after = float(enriched.get("baseline_after_w", cls._median(tail_values, default=baseline_before)) or baseline_before)

        baseline_noise_head = cls._median([abs(v - baseline_before) for v in head_values], default=0.0)
        baseline_noise_tail = cls._median([abs(v - baseline_after) for v in tail_values], default=0.0)
        baseline_noise = max(float(baseline_noise_head), float(baseline_noise_tail))
        baseline_drift = abs(baseline_after - baseline_before)
        baseline_scale = max(abs(baseline_before), abs(baseline_after), 40.0)
        baseline_stability = max(0.0, 1.0 - (baseline_noise / baseline_scale) - (baseline_drift / (baseline_scale * 2.5)))

        delta_points: List[Dict[str, float]] = []
        positive_delta_values: List[float] = []
        for point in points:
            t_norm = float(point.get("t_norm", 0.0) or 0.0)
            baseline_at_t = baseline_before + ((baseline_after - baseline_before) * min(max(t_norm, 0.0), 1.0))
            delta_power = float(point.get("power_w", 0.0) or 0.0) - baseline_at_t
            delta_point = {
                "t_s": float(point["t_s"]),
                "t_norm": float(point["t_norm"]),
                "power_w": round(delta_power, 3),
            }
            delta_points.append(delta_point)
            positive_delta_values.append(max(delta_power, 0.0))

        delta_avg = float(enriched.get("delta_avg_power_w", float(enriched.get("avg_power_w", 0.0) or 0.0) - baseline_before) or 0.0)
        delta_peak = float(enriched.get("delta_peak_power_w", max((p["power_w"] for p in delta_points), default=0.0)) or 0.0)

        delta_energy = float(enriched.get("delta_energy_wh", 0.0) or 0.0)
        if delta_energy <= 0.0:
            watt_seconds = 0.0
            for idx in range(1, len(delta_points)):
                prev = delta_points[idx - 1]
                cur = delta_points[idx]
                dt = max(float(cur["t_s"]) - float(prev["t_s"]), 0.0)
                avg_delta = (max(float(prev["power_w"]), 0.0) + max(float(cur["power_w"]), 0.0)) / 2.0
                watt_seconds += avg_delta * dt
            delta_energy = watt_seconds / 3600.0

        stable_candidates = positive_delta_values
        if len(stable_candidates) >= 5:
            trim = max(1, len(stable_candidates) // 5)
            stable_candidates = stable_candidates[trim:-trim] or stable_candidates
        steady_level = max(cls._median(stable_candidates, default=max(delta_avg, 0.0)), 0.0)
        inrush_peak = max(positive_delta_values) if positive_delta_values else max(delta_peak, 0.0)
        inrush_ratio = inrush_peak / max(steady_level if steady_level > 0 else abs(delta_avg), 1.0)

        settling_time_s = 0.0
        if delta_points and steady_level > 0:
            tolerance = max(steady_level * 0.15, 8.0)
            peak_idx = max(range(len(delta_points)), key=lambda idx: delta_points[idx]["power_w"])
            for idx in range(peak_idx, len(delta_points)):
                if abs(delta_points[idx]["power_w"] - steady_level) <= tolerance:
                    settling_time_s = float(delta_points[idx]["t_s"])
                    break

        plateau_count = int(enriched.get("plateau_count", enriched.get("num_substates", 0)) or 0)
        if plateau_count <= 0 and steady_level > 0:
            tolerance = max(steady_level * 0.12, 6.0)
            in_plateau = False
            for value in positive_delta_values:
                current = abs(value - steady_level) <= tolerance
                if current and not in_plateau:
                    plateau_count += 1
                in_plateau = current

        enriched.update(
            {
                "profile_points": points,
                "baseline_before_w": baseline_before,
                "baseline_after_w": baseline_after,
                "delta_avg_power_w": delta_avg,
                "delta_peak_power_w": delta_peak,
                "delta_energy_wh": delta_energy,
                "delta_profile_points": delta_points,
                "delta_resampled_points": cls._resample_profile_points(delta_points, sample_count=32),
                "delta_shape_vector": cls._resample_profile_points(delta_points, sample_count=32),
                "inrush_peak_w": inrush_peak,
                "inrush_ratio": inrush_ratio,
                "settling_time_s": settling_time_s,
                "plateau_count": plateau_count,
                "steady_delta_power_w": steady_level,
                "baseline_noise_w": baseline_noise,
                "baseline_drift_w": baseline_drift,
                "baseline_quality_score": baseline_stability,
                "baseline_unstable": baseline_stability < cls.LEARNING_PARAMS["baseline_quality_min"],
            }
        )
        return enriched

    @classmethod
    def _build_event_phase_rows(cls, cycle: Dict[str, Any], baseline_before_w: float, baseline_after_w: float) -> List[Dict[str, Any]]:
        enriched = cls._augment_cycle_baseline_delta(cycle)
        points = enriched.get("profile_points", [])
        delta_points = enriched.get("delta_profile_points", [])
        if not points or not delta_points:
            return []

        deltas = [float(point.get("power_w", 0.0) or 0.0) for point in delta_points]
        active_threshold = max(5.0, float(enriched.get("delta_peak_power_w", 0.0) or 0.0) * 0.12, float(enriched.get("delta_avg_power_w", 0.0) or 0.0) * 0.20)
        active_indices = [idx for idx, value in enumerate(deltas) if value >= active_threshold]
        if not active_indices:
            return []

        active_start = active_indices[0]
        active_end = active_indices[-1]
        steady_level = max(float(enriched.get("steady_delta_power_w", 0.0) or 0.0), float(enriched.get("delta_avg_power_w", 0.0) or 0.0), active_threshold)
        peak_idx = max(range(len(deltas)), key=lambda idx: deltas[idx])
        peak_val = deltas[peak_idx]
        has_inrush = peak_idx <= active_start + max(1, (active_end - active_start + 1) // 4) and peak_val >= max(steady_level * 1.2, steady_level + 12.0)

        phase_ranges: List[Tuple[str, int, int]] = []
        if active_start > 0:
            phase_ranges.append(("baseline", 0, active_start))

        run_start = active_start
        if has_inrush:
            settle_threshold = max(steady_level * 1.12, active_threshold)
            settle_idx = peak_idx
            while settle_idx < active_end and deltas[settle_idx] > settle_threshold:
                settle_idx += 1
            settle_idx = min(settle_idx, active_end)
            if settle_idx > active_start:
                phase_ranges.append(("inrush", active_start, settle_idx))
                run_start = settle_idx

        shutdown_start = None
        tail_threshold = max(active_threshold, steady_level * 0.35)
        for idx in range(active_end, run_start, -1):
            if deltas[idx] <= tail_threshold:
                shutdown_start = max(run_start + 1, idx - 1)
                break

        run_end = shutdown_start if shutdown_start is not None else active_end
        if run_end > run_start:
            run_values = deltas[run_start:run_end + 1]
            avg_run = sum(run_values) / max(len(run_values), 1)
            variance = sum((value - avg_run) ** 2 for value in run_values) / max(len(run_values), 1)
            run_type = "modulated_run" if variance > max(avg_run * avg_run * 0.08, 25.0) else "steady_run"
            phase_ranges.append((run_type, run_start, run_end))

        if shutdown_start is not None and active_end >= shutdown_start:
            phase_ranges.append(("shutdown", shutdown_start, active_end))

        if active_end < len(points) - 1:
            phase_ranges.append(("cooldown", active_end, len(points) - 1))

        phase_rows: List[Dict[str, Any]] = []
        for phase_index, (phase_type, start_idx, end_idx) in enumerate(phase_ranges):
            if end_idx < start_idx:
                continue
            segment = points[start_idx:end_idx + 1]
            delta_segment = delta_points[start_idx:end_idx + 1]
            if not segment:
                continue

            start_offset = float(segment[0]["t_s"])
            end_offset = float(segment[-1]["t_s"])
            if len(segment) == 1 and len(points) > 1:
                sample_step = max(float(points[min(start_idx + 1, len(points) - 1)]["t_s"]) - float(points[start_idx]["t_s"]), 0.0)
                end_offset = start_offset + sample_step
            duration_s = max(end_offset - start_offset, 0.0)

            prev_delta = float(delta_points[start_idx - 1]["power_w"]) if start_idx > 0 else 0.0
            next_delta = float(delta_points[end_idx + 1]["power_w"]) if end_idx + 1 < len(delta_points) else 0.0
            delta_values = [float(p["power_w"]) for p in delta_segment]
            abs_values = [float(p["power_w"]) for p in segment]
            phase_rows.append(
                {
                    "phase_index": phase_index,
                    "phase_type": phase_type,
                    "start_offset_s": start_offset,
                    "end_offset_s": end_offset,
                    "duration_s": duration_s,
                    "avg_power_w": sum(abs_values) / max(len(abs_values), 1),
                    "peak_power_w": max(abs_values) if abs_values else 0.0,
                    "baseline_reference_w": baseline_before_w if phase_type != "cooldown" else baseline_after_w,
                    "delta_avg_power_w": sum(delta_values) / max(len(delta_values), 1),
                    "delta_peak_power_w": max(delta_values) if delta_values else 0.0,
                    "step_into_phase_w": (delta_values[0] if delta_values else 0.0) - prev_delta,
                    "step_out_of_phase_w": next_delta - (delta_values[-1] if delta_values else 0.0),
                    "slope_in_w_per_s": ((delta_values[-1] - delta_values[0]) / duration_s) if duration_s > 0 and delta_values else 0.0,
                    "slope_out_w_per_s": ((next_delta - delta_values[-1]) / max(duration_s, 1.0)) if delta_values else 0.0,
                    "phase_points_json": json.dumps(segment),
                }
            )

        return phase_rows

    @classmethod
    def _derive_device_subclass(cls, label: str, cycle: Dict[str, Any]) -> str:
        label_key = str(label or "unknown").strip().lower().replace(" ", "_")
        inrush_ratio = float(cycle.get("inrush_ratio", 0.0) or 0.0)
        has_motor = bool(cycle.get("has_motor_pattern", False))
        has_heating = bool(cycle.get("has_heating_pattern", False))

        if "fridge" in label_key or "kühlschrank" in label_key:
            return "fridge_compressor"
        if has_motor and inrush_ratio >= 1.35:
            return "motor_high_inrush"
        if has_motor:
            return "pump_stable" if float(cycle.get("delta_avg_power_w", 0.0) or 0.0) < 800.0 else "motor_stable"
        if has_heating:
            return "heater_resistive"
        if label_key.startswith("unknown"):
            return cls._infer_unknown_subclass(cycle)
        return label_key or "unknown_device"

    @classmethod
    def _build_device_cycle_summary(cls, cycle: Dict[str, Any], phase_rows: List[Dict[str, Any]], final_label: str) -> Dict[str, Any]:
        inrush_duration = sum(float(item.get("duration_s", 0.0) or 0.0) for item in phase_rows if item.get("phase_type") == "inrush")
        run_phases = [item for item in phase_rows if item.get("phase_type") in {"steady_run", "modulated_run"}]
        run_duration = sum(float(item.get("duration_s", 0.0) or 0.0) for item in run_phases)
        shutdown_duration = sum(float(item.get("duration_s", 0.0) or 0.0) for item in phase_rows if item.get("phase_type") in {"shutdown", "cooldown"})
        avg_run_power = 0.0
        if run_phases:
            avg_run_power = sum(float(item.get("delta_avg_power_w", 0.0) or 0.0) for item in run_phases) / len(run_phases)

        cycle_type_parts = []
        if inrush_duration > 0.0:
            cycle_type_parts.append("inrush")
        cycle_type_parts.append("modulated" if any(item.get("phase_type") == "modulated_run" for item in run_phases) else "steady")
        total_duration = float(cycle.get("duration_s", 0.0) or 0.0)
        cycle_type_parts.append("long" if total_duration >= 600.0 else ("short" if total_duration <= 120.0 else "normal"))
        cycle_type = "_".join(cycle_type_parts)
        label_key = str(final_label or cycle.get("suggestion_type") or "device").strip().lower().replace(" ", "_")

        return {
            "cycle_name": f"{label_key}_{cycle_type}",
            "cycle_type": cycle_type,
            "avg_total_duration_s": total_duration,
            "avg_inrush_duration_s": inrush_duration,
            "avg_run_duration_s": run_duration,
            "avg_shutdown_duration_s": shutdown_duration,
            "avg_delta_power_w": float(cycle.get("delta_avg_power_w", 0.0) or 0.0),
            "avg_inrush_peak_w": float(cycle.get("inrush_peak_w", 0.0) or 0.0),
            "avg_run_power_w": avg_run_power,
            "cycle_signature_json": json.dumps(
                {
                    "label": final_label,
                    "phase_types": [str(item.get("phase_type") or "") for item in phase_rows],
                    "inrush_ratio": round(float(cycle.get("inrush_ratio", 0.0) or 0.0), 3),
                    "steady_delta_power_w": round(float(cycle.get("steady_delta_power_w", 0.0) or 0.0), 3),
                    "delta_peak_power_w": round(float(cycle.get("delta_peak_power_w", 0.0) or 0.0), 3),
                },
                sort_keys=True,
            ),
        }

    @staticmethod
    def _prototype_hash_from_cycle(cycle: Dict) -> str:
        """Create a stable fingerprint for a cycle prototype."""
        payload = {
            "avg": round(float(cycle.get("avg_power_w", 0.0)), 2),
            "peak": round(float(cycle.get("peak_power_w", 0.0)), 2),
            "dur": round(float(cycle.get("duration_s", 0.0)), 2),
            "ene": round(float(cycle.get("energy_wh", 0.0)), 3),
            "sub": int(cycle.get("num_substates", 0) or 0),
            "step": int(cycle.get("step_count", 0) or 0),
            "profile": SQLiteStore._resample_profile_points(cycle.get("profile_points", []), sample_count=24),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
            if math.isfinite(out):
                return out
        except Exception:
            pass
        return float(default)

    @classmethod
    def _shape_signature_from_cycle(cls, cycle: Dict[str, Any]) -> str:
        profile_points = cls._normalize_profile_points(cycle.get("delta_profile_points", []))
        if not profile_points:
            profile_points = cls._normalize_profile_points(cycle.get("profile_points", []))
        vec = cls._resample_profile_points(profile_points, sample_count=16)
        if not vec:
            return ""
        vec_max = max((abs(float(v)) for v in vec), default=1.0)
        denom = max(vec_max, 1.0)
        normalized = [round(float(v) / denom, 3) for v in vec]
        return json.dumps(normalized, separators=(",", ":"))

    @classmethod
    def _curve_hash_from_cycle(cls, cycle: Dict[str, Any]) -> str:
        payload = {
            "phase": str(cycle.get("phase") or "L1"),
            "avg": round(cls._safe_float(cycle.get("avg_power_w"), 0.0), 2),
            "peak": round(cls._safe_float(cycle.get("peak_power_w"), 0.0), 2),
            "dur": round(cls._safe_float(cycle.get("duration_s"), 0.0), 2),
            "delta": round(cls._safe_float(cycle.get("delta_avg_power_w"), 0.0), 2),
            "inrush": round(cls._safe_float(cycle.get("inrush_peak_w"), 0.0), 2),
            "shape": cls._shape_signature_from_cycle(cycle),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _mode_key_from_cycle(cycle: Dict[str, Any]) -> str:
        phase_mode = str(cycle.get("phase_mode") or "unknown")
        substates = int(cycle.get("num_substates", 0) or 0)
        duty = SQLiteStore._safe_float(cycle.get("duty_cycle"), 0.0)
        duration = SQLiteStore._safe_float(cycle.get("duration_s"), 0.0)
        duration_bucket = "short" if duration < 90.0 else ("long" if duration > 900.0 else "normal")
        duty_bucket = "low" if duty < 0.2 else ("high" if duty > 0.8 else "mid")
        return f"{phase_mode}:{substates}:{duration_bucket}:{duty_bucket}"

    @staticmethod
    def _device_group_id(label: str, cycle: Dict[str, Any]) -> str:
        clean = SQLiteStore._normalize_pattern_name(label)
        phase = str(cycle.get("phase") or "L1")
        return f"{clean or 'unknown'}:{phase}"

    @classmethod
    def _dedup_similarity(cls, existing: Dict[str, Any], candidate: Dict[str, Any]) -> float:
        def sim_rel(a: float, b: float) -> float:
            base = max(abs(a), abs(b), 1.0)
            return max(0.0, 1.0 - (abs(a - b) / base))

        profile_dist = cls._profile_shape_distance(existing, candidate)
        if profile_dist is None:
            shape_sim = 0.0
        else:
            shape_sim = max(0.0, min(1.0, 1.0 - profile_dist))

        duration_sim = sim_rel(
            cls._safe_float(existing.get("duration_s"), cls._safe_float(existing.get("avg_duration_s"), 0.0)),
            cls._safe_float(candidate.get("duration_s"), 0.0),
        )
        delta_sim = sim_rel(
            cls._safe_float(existing.get("delta_avg_power_w"), cls._safe_float(existing.get("avg_delta_power_w"), 0.0)),
            cls._safe_float(candidate.get("delta_avg_power_w"), 0.0),
        )
        peak_sim = sim_rel(
            cls._safe_float(existing.get("peak_power_w"), cls._safe_float(existing.get("avg_peak_power_w"), 0.0)),
            cls._safe_float(candidate.get("peak_power_w"), 0.0),
        )
        inrush_sim = sim_rel(
            cls._safe_float(existing.get("avg_inrush_duration_s"), 0.0),
            cls._safe_float(candidate.get("settling_time_s"), 0.0),
        )
        peak_inrush_sim = (peak_sim * 0.7) + (inrush_sim * 0.3)

        score = (
            (shape_sim * 0.50)
            + (duration_sim * 0.20)
            + (delta_sim * 0.20)
            + (peak_inrush_sim * 0.10)
        )
        existing_curve_hash = str(existing.get("curve_hash") or "").strip()
        candidate_curve_hash = str(candidate.get("curve_hash") or "").strip()
        if existing_curve_hash and candidate_curve_hash and existing_curve_hash == candidate_curve_hash:
            score += 0.10

        existing_proto = str(existing.get("prototype_hash") or "").strip()
        candidate_proto = str(candidate.get("prototype_hash") or cls._prototype_hash_from_cycle(candidate)).strip()
        if existing_proto and candidate_proto and existing_proto == candidate_proto:
            score += 0.08
        return max(0.0, min(1.0, score))

    @staticmethod
    def _ranges_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
        a0 = SQLiteStore._parse_iso_timestamp(start_a)
        a1 = SQLiteStore._parse_iso_timestamp(end_a)
        b0 = SQLiteStore._parse_iso_timestamp(start_b)
        b1 = SQLiteStore._parse_iso_timestamp(end_b)
        if not a0 or not a1 or not b0 or not b1:
            return False
        if a1 < a0:
            a0, a1 = a1, a0
        if b1 < b0:
            b0, b1 = b1, b0
        return max(a0, b0) <= min(a1, b1)

    def _is_session_duplicate(self, cycle: Dict[str, Any], label: str) -> bool:
        start_ts = str(cycle.get("start_ts") or "")
        end_ts = str(cycle.get("end_ts") or "")
        key = "|".join(
            [
                str(cycle.get("phase") or "L1"),
                str(self._normalize_pattern_name(label) or "unknown"),
                start_ts,
                end_ts,
                str(round(self._safe_float(cycle.get("duration_s"), 0.0), 1)),
                str(round(self._safe_float(cycle.get("avg_power_w"), 0.0), 1)),
                str(round(self._safe_float(cycle.get("delta_avg_power_w"), 0.0), 1)),
            ]
        )
        if key in self._learning_session_keys:
            return True

        start_ts = str(cycle.get("start_ts") or "")
        end_ts = str(cycle.get("end_ts") or "")
        phase = str(cycle.get("phase") or "L1")
        group_id = str(cycle.get("device_group_id") or self._device_group_id(label, cycle))
        cooldown_s = float(self.LEARNING_PARAMS["session_overlap_cooldown_s"])
        for row in self._learning_session_windows:
            if str(row.get("phase") or "") != phase:
                continue
            if str(row.get("device_group_id") or "") != group_id:
                continue
            if self._ranges_overlap(start_ts, end_ts, str(row.get("start_ts") or ""), str(row.get("end_ts") or "")):
                return True
            prev_end = self._parse_iso_timestamp(str(row.get("end_ts") or ""))
            cur_start = self._parse_iso_timestamp(start_ts)
            if prev_end and cur_start and 0.0 <= (cur_start - prev_end).total_seconds() <= cooldown_s:
                return True

        self._learning_session_keys[key] = end_ts or datetime.now().isoformat()
        self._learning_session_windows.append(
            {
                "phase": phase,
                "device_group_id": group_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
            }
        )
        max_windows = 2000
        if len(self._learning_session_windows) > max_windows:
            self._learning_session_windows = self._learning_session_windows[-1500:]
        if len(self._learning_session_keys) > 2000:
            # Keep memory bounded during long runtimes.
            for old_key in list(self._learning_session_keys.keys())[:500]:
                self._learning_session_keys.pop(old_key, None)
        return False

    @staticmethod
    def _infer_unknown_subclass(cycle: Dict) -> str:
        """Refine unknown classes for better internal diagnostics and future ML."""
        avg_power = float(cycle.get("avg_power_w", 0.0) or 0.0)
        duration_s = float(cycle.get("duration_s", 0.0) or 0.0)
        if bool(cycle.get("has_motor_pattern", False)):
            return "unknown_motor_like"
        if bool(cycle.get("has_heating_pattern", False)):
            return "unknown_heater_like"
        if duration_s <= 12.0:
            return "unknown_short_pulse"
        if duration_s >= 1800.0:
            return "unknown_long_running"
        if avg_power <= 60.0:
            return "unknown_low_power_cycle"
        return "unknown_electronics"

    def _get_or_create_device(self, label: str, phase: str, confidence: float, confirmed: bool = False) -> int | None:
        """Return device_id for label/phase pair, creating it if needed."""
        if not self._patterns_conn:
            return None

        clean_label = str(label or "").strip() or "unknown"
        now = datetime.now().isoformat()
        try:
            row = self._patterns_conn.execute(
                """
                SELECT device_id, times_seen_total, confidence_avg, confirmed
                FROM devices
                WHERE final_label = ? AND COALESCE(phase, '') = ? AND active = 1
                ORDER BY device_id ASC
                LIMIT 1
                """,
                (clean_label, str(phase or "")),
            ).fetchone()
            if row:
                device_id = int(row[0])
                seen = int(row[1] or 0) + 1
                prev_conf = float(row[2] or 0.0)
                conf_avg = ((prev_conf * max(seen - 1, 0)) + float(confidence)) / float(max(seen, 1))
                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE devices
                        SET updated_at = ?, times_seen_total = ?, confidence_avg = ?, confirmed = ?
                        WHERE device_id = ?
                        """,
                        (now, seen, conf_avg, 1 if (confirmed or bool(row[3])) else 0, device_id),
                    )
                return device_id

            with self._patterns_conn:
                cur = self._patterns_conn.execute(
                    """
                    INSERT INTO devices (
                        created_at, updated_at, phase, predicted_label, user_label,
                        final_label, confirmed, confidence_avg, times_seen_total, notes, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        now,
                        str(phase or ""),
                        clean_label,
                        clean_label if confirmed else None,
                        clean_label,
                        1 if confirmed else 0,
                        float(confidence),
                        1,
                        "auto-created from pattern learning",
                        1,
                    ),
                )
                return int(cur.lastrowid or 0)
        except Exception as e:
            logger.debug("_get_or_create_device failed: %s", e)
            return None

    def _record_cycle_event(
        self,
        cycle: Dict,
        assigned_pattern_id: int | None,
        assigned_device_id: int | None,
        final_label: str,
        final_confidence: float,
        rejected_reason: str | None = None,
        dedup_result: str | None = None,
        matched_pattern_id: int | None = None,
        similarity_score: float | None = None,
        dedup_reason: str | None = None,
    ) -> int | None:
        """Persist one detected cycle event for long-term training/replay."""
        if not self._patterns_conn:
            return None
        now = datetime.now().isoformat()
        try:
            enriched = self._augment_cycle_baseline_delta(cycle)
            explain = dict(self._last_hybrid_decision.get("explain") or {})
            fusion = dict(explain.get("fusion") or {})
            prototype_score = float(explain.get("prototype_confidence", 0.0) or 0.0)
            shape_score = float(explain.get("shape_confidence", 0.0) or 0.0)
            ml_score = float((dict(explain.get("ml") or {}).get("confidence", 0.0)) or 0.0)
            decision_reason = str(explain.get("decision_reason") or "")
            hybrid_score = float(fusion.get("final_score", final_confidence) or final_confidence or 0.0)
            start_ts_iso = str(enriched.get("start_ts", ""))
            end_ts_iso = str(enriched.get("end_ts", ""))
            profile_points = self._normalize_profile_points(enriched.get("profile_points", []))
            resampled = self._resample_profile_points(profile_points, sample_count=32)
            delta_points = self._normalize_profile_points(enriched.get("delta_profile_points", []))
            delta_resampled = self._resample_profile_points(delta_points, sample_count=32)
            params = (
                now,
                str(enriched.get("phase", "L1")),
                start_ts_iso,
                end_ts_iso,
                float(enriched.get("duration_s", 0.0)),
                start_ts_iso,
                end_ts_iso,
                float(enriched.get("avg_power_w", 0.0)),
                float(enriched.get("peak_power_w", 0.0)),
                float(enriched.get("energy_wh", 0.0)),
                float(enriched.get("baseline_before_w", 0.0) or 0.0),
                float(enriched.get("baseline_after_w", 0.0) or 0.0),
                float(enriched.get("delta_avg_power_w", 0.0) or 0.0),
                float(enriched.get("delta_peak_power_w", 0.0) or 0.0),
                float(enriched.get("delta_energy_wh", 0.0) or 0.0),
                json.dumps(profile_points),
                json.dumps(delta_points),
                json.dumps(resampled),
                json.dumps(delta_resampled),
                None,
                None,
                str(enriched.get("raw_trace_id") or ""),
                int(assigned_pattern_id) if assigned_pattern_id else None,
                int(assigned_device_id) if assigned_device_id else None,
                float(self._last_hybrid_decision.get("confidence", 0.0) or 0.0),
                shape_score,
                ml_score,
                str(final_label or "unknown"),
                float(final_confidence or 0.0),
                str(rejected_reason) if rejected_reason else None,
                str(dedup_result) if dedup_result else None,
                int(matched_pattern_id) if matched_pattern_id else None,
                float(similarity_score) if similarity_score is not None else None,
                str(dedup_reason) if dedup_reason else None,
                prototype_score,
                shape_score,
                hybrid_score,
                decision_reason,
            )
            placeholders = ", ".join(["?"] * len(params))
            with self._patterns_conn:
                cur = self._patterns_conn.execute(
                    f"""
                    INSERT INTO events (
                        created_at, phase, start_ts, end_ts, duration_s,
                        start_time, end_time,
                        avg_power_w, peak_power_w, energy_wh,
                        baseline_before_w, baseline_after_w,
                        delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                        raw_points_json, delta_points_json, resampled_points_json, delta_resampled_points_json,
                        sample_start_index, sample_end_index, raw_trace_id,
                        assigned_pattern_id, assigned_device_id,
                        match_score, shape_score, ml_score,
                        final_label, final_confidence, rejected_reason,
                        dedup_result, matched_pattern_id, similarity_score, dedup_reason,
                        prototype_score, dtw_score, hybrid_score, decision_reason
                    ) VALUES ({placeholders})
                    """,
                    params,
                )
                event_id = int(cur.lastrowid or 0)

            if event_id > 0:
                phase_rows = self._build_event_phase_rows(
                    enriched,
                    baseline_before_w=float(enriched.get("baseline_before_w", 0.0) or 0.0),
                    baseline_after_w=float(enriched.get("baseline_after_w", 0.0) or 0.0),
                )
                self._record_event_phases(event_id, phase_rows)
                self._upsert_device_cycle(
                    device_id=assigned_device_id,
                    pattern_id=assigned_pattern_id,
                    cycle=enriched,
                    phase_rows=phase_rows,
                    final_label=final_label,
                )
            return event_id
        except Exception as e:
            logger.error("_record_cycle_event failed: %s", e, exc_info=True)
            return None

    @staticmethod
    def _parse_iso_timestamp(ts: str) -> datetime | None:
        raw = str(ts or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def get_pattern_context(self, pattern_id: int, pre_seconds: float = 2.0, post_seconds: float = 2.0) -> Dict[str, Any]:
        """Return one pattern detail payload including raw context samples around the latest event."""
        if not self._patterns_conn:
            return {"ok": False, "error": "patterns_storage_not_connected"}

        pre_s = max(0.0, min(float(pre_seconds), 60.0))
        post_s = max(0.0, min(float(post_seconds), 60.0))

        try:
            pattern_row = self._patterns_conn.execute(
                """
                SELECT id, COALESCE(user_label, ''), COALESCE(suggestion_type, 'unknown'),
                       COALESCE(phase, 'L1'), COALESCE(avg_power_w, 0.0),
                       COALESCE(peak_power_w, 0.0), COALESCE(duration_s, 0.0)
                FROM learned_patterns
                WHERE id = ?
                LIMIT 1
                """,
                (int(pattern_id),),
            ).fetchone()
            if not pattern_row:
                return {"ok": False, "error": "pattern_not_found", "pattern_id": int(pattern_id)}

            event_row = self._patterns_conn.execute(
                """
                SELECT event_id, phase,
                       COALESCE(start_time, start_ts), COALESCE(end_time, end_ts),
                       COALESCE(start_ts, start_time), COALESCE(end_ts, end_time),
                       COALESCE(duration_s, 0.0),
                       COALESCE(avg_power_w, 0.0), COALESCE(peak_power_w, 0.0), COALESCE(energy_wh, 0.0),
                       COALESCE(baseline_before_w, 0.0), COALESCE(baseline_after_w, 0.0),
                       COALESCE(delta_avg_power_w, 0.0), COALESCE(delta_peak_power_w, 0.0),
                       COALESCE(raw_points_json, '[]'),
                       sample_start_index, sample_end_index, COALESCE(raw_trace_id, '')
                FROM events
                WHERE assigned_pattern_id = ?
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (int(pattern_id),),
            ).fetchone()
            if not event_row:
                return {
                    "ok": False,
                    "error": "no_event_for_pattern",
                    "pattern_id": int(pattern_id),
                }

            event_phase = str(event_row[1] or pattern_row[3] or "L1")
            event_start_iso = str(event_row[2] or event_row[4] or "")
            event_end_iso = str(event_row[3] or event_row[5] or "")
            event_start_dt = self._parse_iso_timestamp(event_start_iso)
            event_end_dt = self._parse_iso_timestamp(event_end_iso)
            if not event_start_dt or not event_end_dt:
                return {
                    "ok": False,
                    "error": "invalid_event_timestamps",
                    "pattern_id": int(pattern_id),
                    "event_id": int(event_row[0] or 0),
                }

            requested_context_start = event_start_dt - timedelta(seconds=pre_s)
            requested_context_end = event_end_dt + timedelta(seconds=post_s)

            samples: List[Dict[str, Any]] = []
            min_ts: datetime | None = None
            max_ts: datetime | None = None
            min_max_row = None
            if self._conn and self._table_exists(self._conn, "power_readings"):
                min_max_row = self._conn.execute(
                    """
                    SELECT MIN(ts), MAX(ts)
                    FROM power_readings
                    WHERE phase = ?
                    """,
                    (event_phase,),
                ).fetchone()
                if min_max_row and min_max_row[0] and min_max_row[1]:
                    min_ts = self._parse_iso_timestamp(str(min_max_row[0]))
                    max_ts = self._parse_iso_timestamp(str(min_max_row[1]))

            context_start_dt = requested_context_start
            context_end_dt = requested_context_end
            if min_ts and max_ts:
                context_start_dt = max(requested_context_start, min_ts)
                context_end_dt = min(requested_context_end, max_ts)

            if self._conn and self._table_exists(self._conn, "power_readings"):
                rows = self._conn.execute(
                    """
                    SELECT ts, power_w
                    FROM power_readings
                    WHERE ts >= ? AND ts <= ? AND phase = ?
                    ORDER BY ts ASC
                    """,
                    (
                        context_start_dt.isoformat(),
                        context_end_dt.isoformat(),
                        event_phase,
                    ),
                ).fetchall()
                if not rows and event_phase in {"L1", "L2", "L3"}:
                    rows = self._conn.execute(
                        """
                        SELECT ts, power_w
                        FROM power_readings
                        WHERE ts >= ? AND ts <= ? AND phase = 'TOTAL'
                        ORDER BY ts ASC
                        """,
                        (
                            context_start_dt.isoformat(),
                            context_end_dt.isoformat(),
                        ),
                    ).fetchall()

                samples = [
                    {"ts": str(r[0]), "power": float(r[1] or 0.0)}
                    for r in rows
                ]

            context_warning = ""
            if not samples:
                try:
                    raw_points = json.loads(str(event_row[14] or "[]"))
                except Exception:
                    raw_points = []
                if isinstance(raw_points, list) and raw_points:
                    samples = []
                    for point in raw_points:
                        if not isinstance(point, dict):
                            continue
                        t_offset = self._safe_float(point.get("t_s"), 0.0)
                        p_w = self._safe_float(point.get("power_w"), 0.0)
                        point_ts = event_start_dt + timedelta(seconds=t_offset)
                        samples.append({"ts": point_ts.isoformat(), "power": p_w})
                    context_start_dt = event_start_dt
                    context_end_dt = event_end_dt
                    context_warning = "live_raw_samples_unavailable_fallback_to_event_curve"
                else:
                    context_warning = "no_raw_samples_available"

            offset_start_ms = int(max((event_start_dt - context_start_dt).total_seconds() * 1000.0, 0.0))
            offset_end_ms = int(max((event_end_dt - context_start_dt).total_seconds() * 1000.0, 0.0))
            peak_power = self._safe_float(event_row[8], 0.0)
            baseline_before = self._safe_float(event_row[10], 0.0)
            baseline_after = self._safe_float(event_row[11], 0.0)

            event_phase_rows: List[Dict[str, Any]] = []
            if self._table_exists(self._patterns_conn, "event_phases"):
                try:
                    phase_rows = self._patterns_conn.execute(
                        """
                        SELECT phase_index, phase_type, start_offset_s, end_offset_s, duration_s,
                               avg_power_w, peak_power_w,
                               delta_avg_power_w, delta_peak_power_w,
                               step_into_phase_w, step_out_of_phase_w,
                               slope_in_w_per_s, slope_out_w_per_s
                        FROM event_phases
                        WHERE event_id = ?
                        ORDER BY phase_index ASC
                        """,
                        (int(event_row[0] or 0),),
                    ).fetchall()
                    for pr in phase_rows:
                        event_phase_rows.append(
                            {
                                "phase_index": int(pr[0] or 0),
                                "phase_type": str(pr[1] or "unknown"),
                                "start_offset_s": float(pr[2] or 0.0),
                                "end_offset_s": float(pr[3] or 0.0),
                                "duration_s": float(pr[4] or 0.0),
                                "avg_power_w": float(pr[5] or 0.0),
                                "peak_power_w": float(pr[6] or 0.0),
                                "delta_avg_power_w": float(pr[7] or 0.0),
                                "delta_peak_power_w": float(pr[8] or 0.0),
                                "step_into_phase_w": float(pr[9] or 0.0),
                                "step_out_of_phase_w": float(pr[10] or 0.0),
                                "slope_in_w_per_s": float(pr[11] or 0.0),
                                "slope_out_w_per_s": float(pr[12] or 0.0),
                            }
                        )
                except Exception as phase_err:
                    logger.debug("pattern context event phase load failed: %s", phase_err)

            return {
                "ok": True,
                "pattern_id": int(pattern_row[0]),
                "pattern": {
                    "id": int(pattern_row[0]),
                    "label": str(pattern_row[1] or pattern_row[2] or "unknown"),
                    "suggestion_type": str(pattern_row[2] or "unknown"),
                    "phase": str(pattern_row[3] or event_phase),
                    "avg_power_w": self._safe_float(pattern_row[4], 0.0),
                    "peak_power_w": self._safe_float(pattern_row[5], 0.0),
                    "duration_s": self._safe_float(pattern_row[6], 0.0),
                },
                "event_id": int(event_row[0] or 0),
                "phase": event_phase,
                "start_time": event_start_iso,
                "end_time": event_end_iso,
                "event_start_time": event_start_iso,
                "event_end_time": event_end_iso,
                "context_start": context_start_dt.isoformat(),
                "context_end": context_end_dt.isoformat(),
                "event_start_offset_ms": offset_start_ms,
                "event_end_offset_ms": offset_end_ms,
                "event": {
                    "event_id": int(event_row[0] or 0),
                    "phase": event_phase,
                    "duration_s": self._safe_float(event_row[6], 0.0),
                    "avg_power_w": self._safe_float(event_row[7], 0.0),
                    "peak_power_w": peak_power,
                    "energy_wh": self._safe_float(event_row[9], 0.0),
                    "delta_avg_power_w": self._safe_float(event_row[12], 0.0),
                    "delta_peak_power_w": self._safe_float(event_row[13], 0.0),
                    "sample_start_index": int(event_row[15]) if event_row[15] is not None else None,
                    "sample_end_index": int(event_row[16]) if event_row[16] is not None else None,
                    "raw_trace_id": str(event_row[17] or "") or None,
                },
                "samples": samples,
                "baseline": [
                    {"ts": context_start_dt.isoformat(), "power": baseline_before},
                    {"ts": event_start_iso, "power": baseline_before},
                    {"ts": event_end_iso, "power": baseline_after},
                    {"ts": context_end_dt.isoformat(), "power": baseline_after},
                ],
                "markers": {
                    "event_start": event_start_iso,
                    "event_end": event_end_iso,
                    "peak_power_w": peak_power,
                },
                "event_phases": event_phase_rows,
                "requested_pre_seconds": pre_s,
                "requested_post_seconds": post_s,
                "warning": context_warning or None,
            }
        except Exception as e:
            logger.error("get_pattern_context failed for pattern %s: %s", pattern_id, e, exc_info=True)
            return {"ok": False, "error": str(e), "pattern_id": int(pattern_id)}

    def _record_event_phases(self, event_id: int, phase_rows: List[Dict[str, Any]]) -> None:
        if not self._patterns_conn or not event_id or not phase_rows:
            return
        try:
            with self._patterns_conn:
                self._patterns_conn.execute("DELETE FROM event_phases WHERE event_id = ?", (int(event_id),))
                for row in phase_rows:
                    self._patterns_conn.execute(
                        """
                        INSERT INTO event_phases (
                            event_id, phase_index, phase_type,
                            start_offset_s, end_offset_s, duration_s,
                            avg_power_w, peak_power_w,
                            baseline_reference_w, delta_avg_power_w, delta_peak_power_w,
                            step_into_phase_w, step_out_of_phase_w,
                            slope_in_w_per_s, slope_out_w_per_s,
                            phase_points_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(event_id),
                            int(row.get("phase_index", 0) or 0),
                            str(row.get("phase_type") or "steady_run"),
                            float(row.get("start_offset_s", 0.0) or 0.0),
                            float(row.get("end_offset_s", 0.0) or 0.0),
                            float(row.get("duration_s", 0.0) or 0.0),
                            float(row.get("avg_power_w", 0.0) or 0.0),
                            float(row.get("peak_power_w", 0.0) or 0.0),
                            float(row.get("baseline_reference_w", 0.0) or 0.0),
                            float(row.get("delta_avg_power_w", 0.0) or 0.0),
                            float(row.get("delta_peak_power_w", 0.0) or 0.0),
                            float(row.get("step_into_phase_w", 0.0) or 0.0),
                            float(row.get("step_out_of_phase_w", 0.0) or 0.0),
                            float(row.get("slope_in_w_per_s", 0.0) or 0.0),
                            float(row.get("slope_out_w_per_s", 0.0) or 0.0),
                            str(row.get("phase_points_json") or "[]"),
                        ),
                    )
        except Exception as e:
            logger.debug("_record_event_phases failed: %s", e)

    def _upsert_device_cycle(
        self,
        device_id: int | None,
        pattern_id: int | None,
        cycle: Dict[str, Any],
        phase_rows: List[Dict[str, Any]],
        final_label: str,
    ) -> None:
        if not self._patterns_conn or not device_id:
            return
        summary = self._build_device_cycle_summary(cycle, phase_rows, final_label)
        try:
            row = self._patterns_conn.execute(
                """
                SELECT cycle_id, seen_count,
                       avg_total_duration_s, avg_inrush_duration_s, avg_run_duration_s,
                       avg_shutdown_duration_s, avg_delta_power_w, avg_inrush_peak_w, avg_run_power_w
                FROM device_cycles
                WHERE device_id = ? AND cycle_type = ?
                LIMIT 1
                """,
                (int(device_id), str(summary.get("cycle_type") or "unknown")),
            ).fetchone()
            now = datetime.now().isoformat()
            if row:
                seen_count = int(row[1] or 0) + 1
                alpha = 1.0 / max(seen_count, 1)

                def blend(old_value: Any, new_value: Any) -> float:
                    return float(old_value or 0.0) * (1.0 - alpha) + float(new_value or 0.0) * alpha

                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE device_cycles
                        SET pattern_id = ?, cycle_name = ?, updated_at = ?, seen_count = ?,
                            avg_total_duration_s = ?, avg_inrush_duration_s = ?, avg_run_duration_s = ?,
                            avg_shutdown_duration_s = ?, avg_delta_power_w = ?, avg_inrush_peak_w = ?,
                            avg_run_power_w = ?, cycle_signature_json = ?
                        WHERE cycle_id = ?
                        """,
                        (
                            int(pattern_id) if pattern_id else None,
                            str(summary.get("cycle_name") or "cycle"),
                            now,
                            seen_count,
                            blend(row[2], summary.get("avg_total_duration_s")),
                            blend(row[3], summary.get("avg_inrush_duration_s")),
                            blend(row[4], summary.get("avg_run_duration_s")),
                            blend(row[5], summary.get("avg_shutdown_duration_s")),
                            blend(row[6], summary.get("avg_delta_power_w")),
                            blend(row[7], summary.get("avg_inrush_peak_w")),
                            blend(row[8], summary.get("avg_run_power_w")),
                            str(summary.get("cycle_signature_json") or "{}"),
                            int(row[0]),
                        ),
                    )
            else:
                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        INSERT INTO device_cycles (
                            device_id, pattern_id, cycle_name, cycle_type,
                            created_at, updated_at, seen_count,
                            avg_total_duration_s, avg_inrush_duration_s, avg_run_duration_s,
                            avg_shutdown_duration_s, avg_delta_power_w, avg_inrush_peak_w,
                            avg_run_power_w, cycle_signature_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(device_id),
                            int(pattern_id) if pattern_id else None,
                            str(summary.get("cycle_name") or "cycle"),
                            str(summary.get("cycle_type") or "unknown"),
                            now,
                            now,
                            1,
                            float(summary.get("avg_total_duration_s", 0.0) or 0.0),
                            float(summary.get("avg_inrush_duration_s", 0.0) or 0.0),
                            float(summary.get("avg_run_duration_s", 0.0) or 0.0),
                            float(summary.get("avg_shutdown_duration_s", 0.0) or 0.0),
                            float(summary.get("avg_delta_power_w", 0.0) or 0.0),
                            float(summary.get("avg_inrush_peak_w", 0.0) or 0.0),
                            float(summary.get("avg_run_power_w", 0.0) or 0.0),
                            str(summary.get("cycle_signature_json") or "{}"),
                        ),
                    )
        except Exception as e:
            logger.debug("_upsert_device_cycle failed: %s", e)

    def _maybe_backfill_inrush_runtime_schema(self) -> None:
        if not self._patterns_conn:
            return
        event_key = "inrush_runtime_schema_backfill:v1"
        if self._migration_applied(self._patterns_conn, event_key):
            return

        try:
            updated_patterns = 0
            updated_events = 0
            created_event_phases = 0
            created_cycles = 0

            for pattern in self.list_patterns(limit=5000):
                pattern_id = int(pattern.get("id", 0) or 0)
                if pattern_id <= 0:
                    continue
                enriched = self._augment_cycle_baseline_delta(pattern)
                subclass = self._derive_device_subclass(
                    label=str(pattern.get("user_label") or pattern.get("candidate_name") or pattern.get("suggestion_type") or "unknown"),
                    cycle=enriched,
                )
                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE learned_patterns
                        SET baseline_before_w_avg = ?, baseline_after_w_avg = ?,
                            delta_avg_power_w = ?, delta_peak_power_w = ?, delta_energy_wh = ?,
                            delta_profile_points_json = ?, delta_shape_vector_json = ?, plateau_count = ?
                        WHERE id = ?
                        """,
                        (
                            float(enriched.get("baseline_before_w", 0.0) or 0.0),
                            float(enriched.get("baseline_after_w", 0.0) or 0.0),
                            float(enriched.get("delta_avg_power_w", 0.0) or 0.0),
                            float(enriched.get("delta_peak_power_w", 0.0) or 0.0),
                            float(enriched.get("delta_energy_wh", 0.0) or 0.0),
                            json.dumps(enriched.get("delta_profile_points", [])),
                            json.dumps(enriched.get("delta_shape_vector", [])),
                            int(enriched.get("plateau_count", 0) or 0),
                            pattern_id,
                        ),
                    )
                    if int(pattern.get("device_id", 0) or 0) > 0 and self._table_exists(self._patterns_conn, "devices"):
                        self._patterns_conn.execute(
                            """
                            UPDATE devices
                            SET device_subclass = ?,
                                baseline_range_min_w = COALESCE(baseline_range_min_w, ?),
                                baseline_range_max_w = COALESCE(baseline_range_max_w, ?),
                                updated_at = ?
                            WHERE device_id = ?
                            """,
                            (
                                subclass,
                                float(enriched.get("baseline_before_w", 0.0) or 0.0),
                                float(enriched.get("baseline_after_w", 0.0) or 0.0),
                                datetime.now().isoformat(),
                                int(pattern.get("device_id", 0) or 0),
                            ),
                        )
                pattern.update(
                    {
                        "baseline_before_w_avg": float(enriched.get("baseline_before_w", 0.0) or 0.0),
                        "baseline_after_w_avg": float(enriched.get("baseline_after_w", 0.0) or 0.0),
                        "delta_avg_power_w": float(enriched.get("delta_avg_power_w", 0.0) or 0.0),
                        "delta_peak_power_w": float(enriched.get("delta_peak_power_w", 0.0) or 0.0),
                        "delta_energy_wh": float(enriched.get("delta_energy_wh", 0.0) or 0.0),
                        "delta_profile_points": enriched.get("delta_profile_points", []),
                        "delta_shape_vector_json": json.dumps(enriched.get("delta_shape_vector", [])),
                        "plateau_count": int(enriched.get("plateau_count", 0) or 0),
                    }
                )
                self._upsert_patterns_mirror(pattern)
                updated_patterns += 1

            event_rows = self._patterns_conn.execute(
                """
                SELECT event_id, phase, start_ts, end_ts, duration_s, avg_power_w, peak_power_w, energy_wh,
                       raw_points_json, assigned_pattern_id, assigned_device_id, final_label,
                       baseline_before_w, baseline_after_w, delta_avg_power_w, delta_peak_power_w, delta_energy_wh
                FROM events
                ORDER BY event_id ASC
                LIMIT 5000
                """
            ).fetchall()
            for row in event_rows:
                event_id = int(row[0] or 0)
                raw_points = []
                try:
                    raw_points = json.loads(str(row[8] or "[]"))
                except Exception:
                    raw_points = []
                cycle = {
                    "phase": str(row[1] or "L1"),
                    "start_ts": str(row[2] or ""),
                    "end_ts": str(row[3] or ""),
                    "duration_s": float(row[4] or 0.0),
                    "avg_power_w": float(row[5] or 0.0),
                    "peak_power_w": float(row[6] or 0.0),
                    "energy_wh": float(row[7] or 0.0),
                    "profile_points": raw_points,
                    "baseline_before_w": row[12],
                    "baseline_after_w": row[13],
                    "delta_avg_power_w": row[14],
                    "delta_peak_power_w": row[15],
                    "delta_energy_wh": row[16],
                }
                enriched = self._augment_cycle_baseline_delta(cycle)
                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE events
                        SET baseline_before_w = ?, baseline_after_w = ?,
                            delta_avg_power_w = ?, delta_peak_power_w = ?, delta_energy_wh = ?,
                            delta_points_json = ?, delta_resampled_points_json = ?
                        WHERE event_id = ?
                        """,
                        (
                            float(enriched.get("baseline_before_w", 0.0) or 0.0),
                            float(enriched.get("baseline_after_w", 0.0) or 0.0),
                            float(enriched.get("delta_avg_power_w", 0.0) or 0.0),
                            float(enriched.get("delta_peak_power_w", 0.0) or 0.0),
                            float(enriched.get("delta_energy_wh", 0.0) or 0.0),
                            json.dumps(enriched.get("delta_profile_points", [])),
                            json.dumps(enriched.get("delta_resampled_points", [])),
                            event_id,
                        ),
                    )
                updated_events += 1

                has_phase_row = self._patterns_conn.execute(
                    "SELECT 1 FROM event_phases WHERE event_id = ? LIMIT 1",
                    (event_id,),
                ).fetchone()
                if not has_phase_row:
                    phase_rows = self._build_event_phase_rows(
                        enriched,
                        baseline_before_w=float(enriched.get("baseline_before_w", 0.0) or 0.0),
                        baseline_after_w=float(enriched.get("baseline_after_w", 0.0) or 0.0),
                    )
                    if phase_rows:
                        self._record_event_phases(event_id, phase_rows)
                        created_event_phases += len(phase_rows)
                        before_cycles = self._safe_row_count(self._patterns_conn, "device_cycles")
                        self._upsert_device_cycle(
                            device_id=int(row[10] or 0) or None,
                            pattern_id=int(row[9] or 0) or None,
                            cycle=enriched,
                            phase_rows=phase_rows,
                            final_label=str(row[11] or "unknown"),
                        )
                        after_cycles = self._safe_row_count(self._patterns_conn, "device_cycles")
                        created_cycles += max(after_cycles - before_cycles, 0)

            self._record_migration(
                self._patterns_conn,
                event_key,
                f"patterns={updated_patterns} events={updated_events} event_phases={created_event_phases} device_cycles={created_cycles}",
            )
            logger.info(
                "Backfilled inrush/runtime schema: patterns=%s events=%s event_phases=%s device_cycles=%s",
                updated_patterns,
                updated_events,
                created_event_phases,
                created_cycles,
            )
        except Exception as e:
            logger.warning("Inrush/runtime schema backfill failed: %s", e)

    def _record_classification_log(
        self,
        event_id: int | None,
        pattern_id: int | None,
        device_id: int | None,
        final_label: str,
        final_confidence: float,
        decision_source: str,
    ) -> None:
        """Persist explainable classification decision details."""
        if not self._patterns_conn:
            return
        explain = dict(self._last_hybrid_decision.get("explain") or {})
        ml = dict(explain.get("ml") or {})
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO classification_log (
                        created_at, event_id, pattern_id, device_id,
                        prototype_label, prototype_score,
                        shape_label, shape_score,
                        ml_label, ml_confidence,
                        rule_label, rule_reason,
                        final_label, final_confidence, decision_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now().isoformat(),
                        int(event_id) if event_id else None,
                        int(pattern_id) if pattern_id else None,
                        int(device_id) if device_id else None,
                        str(explain.get("best_label") or "unknown"),
                        float(explain.get("prototype_confidence", 0.0) or 0.0),
                        str(explain.get("best_label") or "unknown"),
                        float(explain.get("shape_confidence", 0.0) or 0.0),
                        str(ml.get("label") or "unknown"),
                        float(ml.get("confidence", 0.0) or 0.0),
                        str(final_label or "unknown"),
                        str(decision_source or "unspecified"),
                        str(final_label or "unknown"),
                        float(final_confidence or 0.0),
                        str(decision_source or "unspecified"),
                    ),
                )
        except Exception as e:
            logger.debug("_record_classification_log failed: %s", e)

    def _record_pattern_features(self, pattern_id: int, cycle: Dict, feature_version: str = "v2") -> None:
        """Store a versioned feature snapshot for one pattern update/create event."""
        if not self._patterns_conn or not pattern_id:
            return

        enriched = self._augment_cycle_baseline_delta(cycle)
        profile_points = self._normalize_profile_points(enriched.get("profile_points", []))
        delta_profile_points = self._normalize_profile_points(enriched.get("delta_profile_points", []))
        power_levels = [float(p.get("power_w", 0.0)) for p in profile_points]
        delta_levels = [float(p.get("power_w", 0.0)) for p in delta_profile_points]
        if power_levels:
            power_min = min(power_levels)
            power_max = max(power_levels)
            power_range = power_max - power_min
            power_std = (float(enriched.get("power_variance", 0.0) or 0.0) ** 0.5)
            power_cv = (power_std / max(float(enriched.get("avg_power_w", 0.0) or 1.0), 1.0))
        else:
            power_range = 0.0
            power_std = 0.0
            power_cv = 0.0

        if delta_levels:
            delta_min = min(delta_levels)
            delta_max = max(delta_levels)
            delta_range = delta_max - delta_min
            delta_mean = max(abs(sum(delta_levels) / max(len(delta_levels), 1)), 1.0)
            delta_std = (sum((value - (sum(delta_levels) / max(len(delta_levels), 1))) ** 2 for value in delta_levels) / max(len(delta_levels), 1)) ** 0.5
            delta_cv = delta_std / delta_mean
        else:
            delta_range = 0.0
            delta_std = 0.0
            delta_cv = 0.0

        step_count = int(enriched.get("step_count", 0) or 0)
        avg_step_w = (power_range / max(step_count, 1)) if step_count > 0 else 0.0

        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO pattern_features (
                        pattern_id, feature_version,
                        power_variance, power_std, power_cv, power_range,
                        delta_power_std, delta_power_cv, delta_power_range,
                        num_substates, step_count, max_step_w, avg_step_w,
                        plateau_count, dominant_power_levels_json, dominant_delta_levels_json,
                        substate_durations_json, substate_power_levels_json,
                        rise_rate_w_per_s, fall_rate_w_per_s,
                        inrush_peak_w, inrush_ratio, settling_time_s,
                        shape_embedding_json, delta_shape_embedding_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(pattern_id),
                        str(feature_version),
                        float(enriched.get("power_variance", 0.0) or 0.0),
                        power_std,
                        power_cv,
                        power_range,
                        delta_std,
                        delta_cv,
                        delta_range,
                        int(enriched.get("num_substates", 0) or 0),
                        step_count,
                        power_range,
                        avg_step_w,
                        int(enriched.get("plateau_count", enriched.get("num_substates", 0)) or 0),
                        json.dumps(power_levels[:16]),
                        json.dumps(delta_levels[:16]),
                        "[]",
                        "[]",
                        float(enriched.get("rise_rate_w_per_s", 0.0) or 0.0),
                        float(enriched.get("fall_rate_w_per_s", 0.0) or 0.0),
                        float(enriched.get("inrush_peak_w", 0.0) or 0.0),
                        float(enriched.get("inrush_ratio", 0.0) or 0.0),
                        float(enriched.get("settling_time_s", 0.0) or 0.0),
                        json.dumps(self._resample_profile_points(profile_points, sample_count=32)),
                        json.dumps(self._resample_profile_points(delta_profile_points, sample_count=32)),
                        datetime.now().isoformat(),
                    ),
                )
        except Exception as e:
            logger.debug("_record_pattern_features failed: %s", e)

    def _record_pattern_history_snapshot(self, pattern: Dict) -> None:
        """Persist lightweight history snapshots for drift tracking."""
        if not self._patterns_conn:
            return
        pattern_id = int(pattern.get("id", 0) or 0)
        if pattern_id <= 0:
            return
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO pattern_history (
                        pattern_id, snapshot_ts, seen_count,
                        avg_power_w, peak_power_w, duration_s,
                        confidence_score, profile_points_json, quality_score_avg
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pattern_id,
                        datetime.now().isoformat(),
                        int(pattern.get("seen_count", 0) or 0),
                        float(pattern.get("avg_power_w", 0.0) or 0.0),
                        float(pattern.get("peak_power_w", 0.0) or 0.0),
                        float(pattern.get("duration_s", 0.0) or 0.0),
                        float(pattern.get("confidence_score", 0.0) or 0.0),
                        json.dumps(self._normalize_profile_points(pattern.get("profile_points", []))),
                        float(pattern.get("quality_score_avg", 0.0) or 0.0),
                    ),
                )
        except Exception as e:
            logger.debug("_record_pattern_history_snapshot failed: %s", e)

    def _record_user_label_change(
        self,
        pattern_id: int,
        device_id: int | None,
        old_label: str,
        new_label: str,
        comment: str | None = None,
    ) -> None:
        """Persist user label corrections for later supervised ML training."""
        if not self._patterns_conn:
            return
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO user_labels (
                        created_at, pattern_id, device_id, old_label, new_label,
                        confirmed_by_user, comment
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now().isoformat(),
                        int(pattern_id),
                        int(device_id) if device_id else None,
                        str(old_label or ""),
                        str(new_label or ""),
                        1,
                        str(comment) if comment else None,
                    ),
                )
        except Exception as e:
            logger.debug("_record_user_label_change failed: %s", e)

    @staticmethod
    def _parse_operating_modes(raw: object) -> List[Dict]:
        """Parse persisted operating modes safely from JSON string/list."""
        if isinstance(raw, list):
            base = raw
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                base = parsed if isinstance(parsed, list) else []
            except Exception:
                base = []
        else:
            base = []

        out: List[Dict] = []
        for item in base:
            if not isinstance(item, dict):
                continue
            try:
                out.append(
                    {
                        "avg_power_w": float(item.get("avg_power_w", 0.0)),
                        "duration_s": float(item.get("duration_s", 0.0)),
                        "peak_power_w": float(item.get("peak_power_w", 0.0)),
                        "seen_count": max(1, int(item.get("seen_count", 1))),
                        "last_seen": str(item.get("last_seen", "")),
                    }
                )
            except (TypeError, ValueError):
                continue
        return out[:12]

    @staticmethod
    def _build_mode_signature(cycle: Dict, end_ts: str) -> Dict:
        """Create a compact mode signature from a learned cycle."""
        return {
            "avg_power_w": float(cycle.get("avg_power_w", 0.0)),
            "duration_s": float(cycle.get("duration_s", 0.0)),
            "peak_power_w": float(cycle.get("peak_power_w", 0.0)),
            "seen_count": 1,
            "last_seen": str(end_ts),
        }

    @staticmethod
    def _merge_operating_modes(existing_modes: List[Dict], candidate_mode: Dict, max_modes: int = 6) -> List[Dict]:
        """Merge candidate cycle into nearest operating mode or create a new mode cluster."""

        def rel(a: float, b: float) -> float:
            base = max(abs(a), abs(b), 1.0)
            return abs(a - b) / base

        modes = [dict(m) for m in existing_modes]
        if not candidate_mode:
            return modes[:max_modes]

        best_idx = -1
        best_dist = 999.0
        for idx, mode in enumerate(modes):
            dist = (
                rel(float(mode.get("avg_power_w", 0.0)), float(candidate_mode.get("avg_power_w", 0.0))) * 0.55
                + rel(float(mode.get("duration_s", 0.0)), float(candidate_mode.get("duration_s", 0.0))) * 0.35
                + rel(float(mode.get("peak_power_w", 0.0)), float(candidate_mode.get("peak_power_w", 0.0))) * 0.10
            )
            if dist < best_dist:
                best_dist = dist
                best_idx = idx

        if best_idx >= 0 and best_dist <= SQLiteStore.LEARNING_PARAMS["mode_merge_max_dist"]:
            mode = modes[best_idx]
            seen = max(1, int(mode.get("seen_count", 1)))
            alpha = 1.0 / float(seen + 1)
            mode["avg_power_w"] = float(mode.get("avg_power_w", 0.0)) * (1.0 - alpha) + float(candidate_mode.get("avg_power_w", 0.0)) * alpha
            mode["duration_s"] = float(mode.get("duration_s", 0.0)) * (1.0 - alpha) + float(candidate_mode.get("duration_s", 0.0)) * alpha
            mode["peak_power_w"] = float(mode.get("peak_power_w", 0.0)) * (1.0 - alpha) + float(candidate_mode.get("peak_power_w", 0.0)) * alpha
            mode["seen_count"] = seen + 1
            mode["last_seen"] = str(candidate_mode.get("last_seen", mode.get("last_seen", "")))
            modes[best_idx] = mode
        else:
            modes.append(dict(candidate_mode))

        modes.sort(key=lambda item: int(item.get("seen_count", 1)), reverse=True)
        return modes[:max_modes]

    @staticmethod
    def _effective_classification_label(item: Dict) -> str:
        """Resolve a stable classification label with clear precedence.

        Precedence: confirmed user label > candidate_name > detector/ML suggestion.
        """
        user_label = str(item.get("user_label") or "").strip()
        if user_label:
            return user_label
        candidate_name = str(item.get("candidate_name") or "").strip()
        if candidate_name:
            return candidate_name
        suggestion = str(item.get("suggestion_type") or "").strip()
        return suggestion or "unknown"

    @staticmethod
    def _device_group_key(item: Dict) -> str:
        """Build a stable group key so multiple patterns can belong to one device group."""
        raw = SQLiteStore._effective_classification_label(item)
        key = SQLiteStore._normalize_pattern_name(raw)
        return key or "unbekannt"

    def _maybe_repair_pattern_timestamps(self, force: bool = False) -> None:
        """Repair broken learned_patterns timestamps where last_seen < first_seen."""
        if not self._patterns_conn:
            return
        event_key = "repair_pattern_timestamps:v1"
        if not force and self._migration_applied(self._patterns_conn, event_key):
            return

        repaired = 0
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT id, first_seen, last_seen
                FROM learned_patterns
                """
            ).fetchall()
            with self._patterns_conn:
                for row in rows:
                    pattern_id = int(row[0] or 0)
                    first_seen = str(row[1] or "")
                    last_seen = str(row[2] or "")
                    first_norm, last_norm = self._normalize_seen_bounds(
                        first_seen=first_seen,
                        last_seen=last_seen,
                        fallback_start=first_seen,
                        fallback_end=last_seen,
                    )
                    if first_norm != first_seen or last_norm != last_seen:
                        self._patterns_conn.execute(
                            """
                            UPDATE learned_patterns
                            SET first_seen = ?,
                                last_seen = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (first_norm, last_norm, datetime.now().isoformat(), pattern_id),
                        )
                        repaired += 1

            if not force:
                self._record_migration(self._patterns_conn, event_key, f"repaired={repaired}")
            if repaired > 0:
                logger.info("Repaired learned_patterns timestamp order for %s rows", repaired)
        except Exception as e:
            logger.warning("Pattern timestamp repair migration failed: %s", e)

    @staticmethod
    def _incremental_rise_w(signature: Dict) -> float:
        """Estimate added load above baseline (incremental rise) from profile/metrics."""
        points = SQLiteStore._normalize_profile_points(signature.get("profile_points", []))
        if len(points) >= 3:
            # Use first 20% of samples as baseline approximation.
            head_count = max(1, int(len(points) * 0.2))
            baseline = sum(float(p.get("power_w", 0.0)) for p in points[:head_count]) / float(head_count)
            peak = max(float(p.get("power_w", 0.0)) for p in points)
            return max(0.0, peak - baseline)

        peak = float(signature.get("peak_power_w", 0.0))
        avg = float(signature.get("avg_power_w", 0.0))
        # Fallback when no profile exists: infer a conservative added-load proxy.
        return max(0.0, peak - max(0.0, avg * 0.75))

    @staticmethod
    def _peak_timing_ratio(signature: Dict) -> float | None:
        """Return relative peak position in cycle (0=start, 1=end) if profile exists."""
        points = SQLiteStore._normalize_profile_points(signature.get("profile_points", []))
        if len(points) < 3:
            return None

        best = max(points, key=lambda item: float(item.get("power_w", 0.0)))
        try:
            return min(1.0, max(0.0, float(best.get("t_norm", 0.0))))
        except (TypeError, ValueError):
            return None

    def store_reading(self, reading: PowerReading) -> None:
        if not self._conn:
            return
        
        self._reading_batch.append(reading)
        self._batch_ops_since_flush += 1
        
        if len(self._reading_batch) >= self._max_batch_size:
            self._flush_reading_batch()
    
    def _flush_reading_batch(self) -> None:
        if not self._conn or not self._reading_batch:
            return
        
        try:
            batch_copy = self._reading_batch[:]
            self._reading_batch.clear()
            
            rows = [
                (
                    reading.timestamp.isoformat(),
                    float(reading.power_w),
                    reading.phase,
                    json.dumps(reading.metadata or {}),
                )
                for reading in batch_copy
            ]
            
            with self._conn:
                self._conn.executemany(
                    "INSERT INTO power_readings (ts, power_w, phase, metadata) VALUES (?, ?, ?, ?)",
                    rows,
                )
            
            if len(rows) > 1:
                logger.debug(f"Flushed {len(rows)} power readings to SQLite")
        except sqlite3.DatabaseError as db_error:
            logger.error(f"SQLite DB error while flushing readings: {db_error}", exc_info=True)
            if "malformed" in str(db_error).lower():
                self._reinitialize_database()
        except Exception as e:
            logger.error(f"Failed to flush power readings: {e}", exc_info=True)

    def store_detection(self, result: DetectionResult) -> None:
        if not self._conn:
            return
        
        self._detection_batch.append(result)
        self._batch_ops_since_flush += 1
        
        if len(self._detection_batch) >= self._max_batch_size:
            self._flush_detection_batch()
    
    def _flush_detection_batch(self) -> None:
        if not self._conn or not self._detection_batch:
            return
        
        try:
            batch_copy = self._detection_batch[:]
            self._detection_batch.clear()
            
            rows = [
                (
                    result.timestamp.isoformat(),
                    result.device_name,
                    result.state.value,
                    float(result.power_w),
                    float(result.confidence),
                    json.dumps(result.details or {}),
                )
                for result in batch_copy
            ]
            
            with self._conn:
                self._conn.executemany(
                    """
                    INSERT INTO detections (ts, device_name, state, power_w, confidence, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            
            if len(rows) > 1:
                logger.debug(f"Flushed {len(rows)} detection results to SQLite")
        except sqlite3.DatabaseError as db_error:
            logger.error(f"SQLite DB error while flushing detections: {db_error}", exc_info=True)
            if "malformed" in str(db_error).lower():
                self._reinitialize_database()
        except Exception as e:
            logger.error(f"Failed to flush detection results: {e}", exc_info=True)

    def get_recent_power_values(self, minutes: int = 60, limit: int = 300) -> List[float]:
        if not self._conn:
            return []
        if not self._table_exists(self._conn, "power_readings"):
            logger.info("Warmstart skipped: table power_readings is missing")
            return []

        try:
            cutoff = (datetime.now() - timedelta(minutes=max(minutes, 1))).isoformat()
            cur = self._conn.execute(
                """
                SELECT power_w FROM power_readings
                WHERE ts >= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (cutoff, int(limit)),
            )
            rows = cur.fetchall()
            return [float(row[0]) for row in reversed(rows)]
        except Exception as e:
            logger.error(f"Failed to load recent power values: {e}", exc_info=True)
            return []

    def get_power_series(self, limit: int = 300, offset: int = 0, max_limit: int = 2000) -> List[Dict]:
        if not self._conn:
            return []
        if not self._table_exists(self._conn, "power_readings"):
            logger.info("Power series unavailable: table power_readings is missing")
            return []

        try:
            safe_max_limit = max(10, min(int(max_limit), 100000))
            safe_limit = max(10, min(int(limit), safe_max_limit))
            safe_offset = max(0, int(offset))
            # Hole Gesamtleistungen
            cur = self._conn.execute(
                """
                SELECT ts, power_w, phase, metadata FROM power_readings
                ORDER BY ts DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit * 4, safe_offset * 4),  # *4 wegen potenzieller L1/L2/L3-Einträge
            )
            rows = cur.fetchall()
            
            # Gruppiere nach Zeitstempeln und aggregiere Phasen
            points_by_ts = {}
            for row in rows:
                ts = row[0]
                power_w = float(row[1])
                phase = row[2] if len(row) > 2 else None
                raw_metadata = row[3] if len(row) > 3 else None
                
                if ts not in points_by_ts:
                    points_by_ts[ts] = {
                        "timestamp": ts,
                        "power_w": 0.0,
                        "phases": {}
                    }

                # Prefer detailed phase data from reading metadata when available.
                metadata = {}
                if isinstance(raw_metadata, str) and raw_metadata.strip():
                    try:
                        metadata = json.loads(raw_metadata)
                    except Exception:
                        metadata = {}

                phase_powers = metadata.get("phase_powers_w", {}) if isinstance(metadata, dict) else {}
                if isinstance(phase_powers, dict):
                    for phase_name in ("L1", "L2", "L3"):
                        if phase_name in phase_powers:
                            try:
                                points_by_ts[ts]["phases"][phase_name] = float(phase_powers[phase_name])
                            except (TypeError, ValueError):
                                continue

                    if points_by_ts[ts]["phases"]:
                        points_by_ts[ts]["power_w"] = float(sum(points_by_ts[ts]["phases"].values()))
                        continue
                
                # Wenn es eine einzelne Phase ist, speichere sie
                if phase and phase in ("L1", "L2", "L3"):
                    points_by_ts[ts]["phases"][phase] = power_w
                    # Addiere zur Gesamtleistung
                    points_by_ts[ts]["power_w"] += power_w
                else:
                    # Ohne Phasen-Info, nutze direkt den Wert
                    points_by_ts[ts]["power_w"] = power_w
            
            # Sortiere und limitiere
            sorted_points = sorted(points_by_ts.values(), key=lambda p: p["timestamp"])
            return sorted_points[-safe_limit:]
        except Exception as e:
            logger.error(f"Failed to load power series: {e}", exc_info=True)
            return []

    def get_summary(self, hours: int = 24) -> Dict:
        if not self._conn:
            return {
                "reading_count": 0,
                "avg_power_w": 0.0,
                "min_power_w": 0.0,
                "max_power_w": 0.0,
            }
        if not self._table_exists(self._conn, "power_readings"):
            return {
                "reading_count": 0,
                "avg_power_w": 0.0,
                "min_power_w": 0.0,
                "max_power_w": 0.0,
            }

        try:
            cutoff = (datetime.now() - timedelta(hours=max(hours, 1))).isoformat()
            cur = self._conn.execute(
                """
                SELECT COUNT(*), AVG(power_w), MIN(power_w), MAX(power_w)
                FROM power_readings
                WHERE ts >= ?
                """,
                (cutoff,),
            )
            row = cur.fetchone() or (0, None, None, None)
            return {
                "reading_count": int(row[0] or 0),
                "avg_power_w": float(row[1] or 0.0),
                "min_power_w": float(row[2] or 0.0),
                "max_power_w": float(row[3] or 0.0),
            }
        except Exception as e:
            logger.error(f"Failed to build summary stats: {e}", exc_info=True)
            return {
                "reading_count": 0,
                "avg_power_w": 0.0,
                "min_power_w": 0.0,
                "max_power_w": 0.0,
            }

    def cleanup_old_data(self) -> None:
        if not self._conn:
            return

        try:
            cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
            with self._conn:
                self._conn.execute("DELETE FROM power_readings WHERE ts < ?", (cutoff,))
                self._conn.execute("DELETE FROM detections WHERE ts < ?", (cutoff,))
            if self._patterns_conn:
                with self._patterns_conn:
                    self._patterns_conn.execute("DELETE FROM learned_patterns WHERE last_seen < ?", (cutoff,))
        except Exception as e:
            logger.error(f"Failed to clean old SQLite data: {e}", exc_info=True)

    def flush_debug_data(self, reset_patterns: bool = True) -> Dict:
        """Delete runtime data for debugging and return deletion statistics."""
        if not self._conn:
            return {"ok": False, "error": "storage not connected"}

        try:
            cur_readings = self._conn.execute("SELECT COUNT(*) FROM power_readings")
            cur_detections = self._conn.execute("SELECT COUNT(*) FROM detections")
            cur_patterns = self._patterns_conn.execute("SELECT COUNT(*) FROM learned_patterns") if self._patterns_conn else None

            deleted_readings = int((cur_readings.fetchone() or [0])[0])
            deleted_detections = int((cur_detections.fetchone() or [0])[0])
            deleted_patterns = int((cur_patterns.fetchone() or [0])[0]) if (reset_patterns and cur_patterns) else 0

            with self._conn:
                self._conn.execute("DELETE FROM power_readings")
                self._conn.execute("DELETE FROM detections")
            if reset_patterns and self._patterns_conn:
                with self._patterns_conn:
                    self._patterns_conn.execute("DELETE FROM learned_patterns")

            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                if self._patterns_conn and self._patterns_conn is not self._conn:
                    self._patterns_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.execute("VACUUM;")
            except Exception as vacuum_error:
                logger.warning(f"SQLite checkpoint/vacuum after flush failed: {vacuum_error}")

            logger.warning(
                "Debug DB flush executed: "
                f"readings={deleted_readings}, detections={deleted_detections}, patterns={deleted_patterns}"
            )

            return {
                "ok": True,
                "deleted": {
                    "power_readings": deleted_readings,
                    "detections": deleted_detections,
                    "learned_patterns": deleted_patterns,
                },
                "reset_patterns": bool(reset_patterns),
            }
        except Exception as e:
            logger.error(f"Failed to flush debug DB data: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _pattern_distance(existing: Dict, candidate: Dict) -> float:
        """Calculate similarity distance between two patterns.
        
        Enhanced with advanced features inspired by NILM research for better accuracy.
        Returns 0.0 for identical patterns, higher values for more different ones.
        """
        def rel(a: float, b: float) -> float:
            base = max(abs(a), abs(b), 1.0)
            return abs(a - b) / base

        # Core power characteristics (65% weight)
        avg_dist = rel(float(existing["avg_power_w"]), float(candidate["avg_power_w"]))
        peak_dist = rel(float(existing["peak_power_w"]), float(candidate["peak_power_w"]))
        duration_dist = rel(float(existing["duration_s"]), float(candidate["duration_s"]))
        energy_dist = rel(float(existing["energy_wh"]), float(candidate["energy_wh"]))
        phase_dist = rel(float(existing.get("avg_active_phases", 1.0)), float(candidate.get("active_phase_count", 1.0)))

        # Added-load evaluation: how much power came on top of baseline.
        incremental_dist = rel(
            SQLiteStore._incremental_rise_w(existing),
            SQLiteStore._incremental_rise_w(candidate),
        )
        
        core_distance = (
            (avg_dist * 0.20)
            + (peak_dist * 0.15)
            + (duration_dist * 0.14)
            + (incremental_dist * 0.12)
            + (energy_dist * 0.03)
            + (phase_dist * 0.02)
        )
        
        # Advanced shape features (35% weight) - this is where we gain accuracy!
        shape_distance = 0.0
        
        # Rise/fall rates (how appliance turns on/off)
        if "rise_rate_w_per_s" in existing and "rise_rate_w_per_s" in candidate:
            rise_dist = rel(float(existing.get("rise_rate_w_per_s", 0.0)), float(candidate.get("rise_rate_w_per_s", 0.0)))
            fall_dist = rel(float(existing.get("fall_rate_w_per_s", 0.0)), float(candidate.get("fall_rate_w_per_s", 0.0)))
            shape_distance += (rise_dist * 0.08) + (fall_dist * 0.07)
        else:
            # Fallback if no advanced features: increase weight on basic features
            shape_distance += 0.15
        
        # Duty cycle and variance (power stability)
        if "duty_cycle" in existing and "duty_cycle" in candidate:
            duty_dist = abs(float(existing.get("duty_cycle", 0.0)) - float(candidate.get("duty_cycle", 0.0)))
            variance_dist = rel(float(existing.get("power_variance", 0.0)), float(candidate.get("power_variance", 0.0)))
            shape_distance += (duty_dist * 0.06) + (variance_dist * 0.05)
        else:
            shape_distance += 0.11
        
        # Peak-to-average ratio (spikiness)
        if "peak_to_avg_ratio" in existing and "peak_to_avg_ratio" in candidate:
            ratio_dist = rel(float(existing.get("peak_to_avg_ratio", 1.0)), float(candidate.get("peak_to_avg_ratio", 1.0)))
            shape_distance += ratio_dist * 0.04
        else:
            shape_distance += 0.04
        
        # Multi-state detection (washing machine phases, etc.)
        if "num_substates" in existing and "num_substates" in candidate:
            substates_dist = abs(int(existing.get("num_substates", 0)) - int(candidate.get("num_substates", 0))) / 5.0
            shape_distance += substates_dist * 0.05
        else:
            shape_distance += 0.05
        
        # Pattern type matching (heating vs motor)
        pattern_penalty = 0.0
        if "has_heating_pattern" in existing and "has_heating_pattern" in candidate:
            if bool(existing.get("has_heating_pattern", 0)) != bool(candidate.get("has_heating_pattern", 0)):
                pattern_penalty += 0.03
        if "has_motor_pattern" in existing and "has_motor_pattern" in candidate:
            if bool(existing.get("has_motor_pattern", 0)) != bool(candidate.get("has_motor_pattern", 0)):
                pattern_penalty += 0.02
        
        shape_distance += pattern_penalty

        # Curve shape similarity from real stored profile points.
        profile_dist = SQLiteStore._profile_shape_distance(existing, candidate)
        if profile_dist is None:
            shape_distance += 0.05
        else:
            shape_distance += profile_dist * 0.12

        # Peak timing in cycle: helps distinguish short spikes vs late-heating peaks.
        existing_peak_t = SQLiteStore._peak_timing_ratio(existing)
        candidate_peak_t = SQLiteStore._peak_timing_ratio(candidate)
        if existing_peak_t is not None and candidate_peak_t is not None:
            shape_distance += abs(existing_peak_t - candidate_peak_t) * 0.05
        else:
            shape_distance += 0.02
        
        # Weights are already baked into core_distance (0.65) and shape_distance (0.35)
        # So we combine them directly to get normalized 0-1 distance
        total_distance = core_distance + shape_distance
        return min(total_distance, 1.0)

    def suggest_cycle_label(self, cycle: Dict, fallback: str = "unknown") -> Dict:
        """Hybrid cycle label suggestion.

        Combines prototype similarity, shape similarity, and optional local ML.
        Returns an explainable decision payload with score components.
        """
        def _remember(decision: Dict[str, Any]) -> Dict[str, Any]:
            self._last_hybrid_decision = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "label": decision.get("label", fallback),
                "confidence": float(decision.get("confidence", 0.0) or 0.0),
                "source": str(decision.get("source", "unknown")),
                "explain": decision.get("explain"),
            }
            return decision

        if not self._patterns_conn:
            return _remember({"label": fallback, "confidence": 0.0, "source": "fallback"})

        if not self.ai_enabled:
            return _remember({"label": fallback, "confidence": 0.0, "source": "ai_disabled"})

        patterns = self.list_patterns(limit=500)
        if not patterns:
            return _remember({"label": fallback, "confidence": 0.0, "source": "fallback"})

        cycle_phase = str(cycle.get("phase") or "L1")
        phase_locks = self.get_label_phase_locks()

        if cycle_phase in {"L1", "L2", "L3"}:
            filtered_patterns: List[Dict[str, Any]] = []
            for pattern in patterns:
                pattern_phase = str(pattern.get("phase") or "")
                group_label = self._device_group_key(pattern)
                locked_phase = str(phase_locks.get(group_label) or "")

                # 1) Always avoid cross-phase matching for explicitly phase-tagged patterns.
                if pattern_phase in {"L1", "L2", "L3"} and pattern_phase != cycle_phase:
                    continue

                # 2) If user locked label->phase, suppress this label on other phases.
                if locked_phase in {"L1", "L2", "L3"} and locked_phase != cycle_phase:
                    continue

                filtered_patterns.append(pattern)

            if filtered_patterns:
                patterns = filtered_patterns

        # Enrich cycle with substate-derived features if missing.
        substate = analyze_profile_substates(cycle.get("profile_points", []))
        if int(cycle.get("num_substates", 0) or 0) <= 0:
            cycle["num_substates"] = int(substate.num_substates)
        if float(cycle.get("peak_to_avg_ratio", 0.0) or 0.0) <= 0.0:
            avg_power = max(float(cycle.get("avg_power_w", 0.0) or 0.0), 1.0)
            peak_power = max(float(cycle.get("peak_power_w", 0.0) or 0.0), avg_power)
            cycle["peak_to_avg_ratio"] = peak_power / avg_power

        matcher_result = self._pattern_matcher.match(
            cycle=cycle,
            patterns=patterns,
            distance_fn=self._pattern_distance,
            group_key_fn=self._device_group_key,
        )
        if matcher_result is None:
            return _remember({"label": fallback, "confidence": 0.0, "source": "fallback"})

        best_group = matcher_result.best_group
        best_label = matcher_result.best_label
        prototype_confidence = matcher_result.prototype_confidence
        shape_confidence = matcher_result.shape_confidence
        heuristic_confidence = matcher_result.confidence
        best_distance_overall = matcher_result.best_distance

        ml_result = None
        if self.ml_enabled:
            try:
                ml_result = self._ml_classifier.predict(
                    patterns=patterns,
                    cycle=cycle,
                    confidence_threshold=self.ml_confidence_threshold,
                )
            except Exception as ml_error:
                logger.debug("Local ML prediction failed: %s", ml_error)
                ml_result = None

        final_label = best_label
        final_confidence = heuristic_confidence
        source = "hybrid_phase1_shape_proto"
        decision_reason = "shape_prototype_only"

        ml_label = "unknown"
        ml_conf = 0.0
        if ml_result:
            ml_label = str(ml_result.label or "unknown")
            ml_conf = float(ml_result.confidence or 0.0)

        if ml_result and ml_result.source.startswith("ml"):
            ml_valid = ml_label != "unknown" and ml_conf >= self.ml_confidence_threshold
            if ml_valid:
                # Phase 1 fusion: boosting 45%, shape 35%, prototype 20%.
                fused_score = (0.45 * ml_conf) + (0.35 * shape_confidence) + (0.20 * prototype_confidence)
                final_confidence = max(final_confidence, fused_score)

                # Agreement: keep matcher label but increase trust.
                if ml_label == best_group or ml_label == best_label:
                    final_label = best_label
                    source = "hybrid_phase1_agreement"
                    decision_reason = "boosting_and_shape_agree"
                else:
                    # Controlled override: only with clear margin and acceptable shape fit.
                    if ml_conf > (heuristic_confidence + 0.12) and shape_confidence >= 0.40:
                        final_label = ml_label
                        source = "hybrid_phase1_ml_override"
                        decision_reason = "boosting_strong_override"
                    else:
                        final_label = best_label
                        source = "hybrid_phase1_shape_proto"
                        decision_reason = "shape_prototype_preferred"

        confidence = max(0.0, min(1.0, float(final_confidence)))

        normalized_final_label = self._normalize_pattern_name(str(final_label or ""))
        label_lock_phase = str(phase_locks.get(normalized_final_label) or "")
        if label_lock_phase in {"L1", "L2", "L3"} and cycle_phase in {"L1", "L2", "L3"} and label_lock_phase != cycle_phase:
            return _remember({
                "label": fallback,
                "confidence": min(confidence, 0.2),
                "source": "phase_lock_reject",
                "explain": {
                    **dict(matcher_result.explain),
                    "decision_reason": "phase_lock_reject",
                    "cycle_phase": cycle_phase,
                    "phase_lock": {
                        "label": normalized_final_label,
                        "locked_phase": label_lock_phase,
                    },
                },
            })

        # Unknown labels must never look "certain" in UI/debug output.
        normalized_label = str(final_label or "").strip().lower()
        if normalized_label in {"", "unknown", "unbekannt"}:
            capped_unknown_conf = min(confidence, 0.35)
            return _remember({
                "label": fallback,
                "confidence": capped_unknown_conf,
                "source": "fallback_unknown_label",
                "explain": {
                    **dict(matcher_result.explain),
                    "decision_reason": "unknown_label_blocked",
                    "unknown_label_capped": True,
                    "ml": (
                        {
                            "label": ml_result.label,
                            "confidence": round(float(ml_result.confidence), 4),
                            "source": ml_result.source,
                            "top_n": ml_result.top_n,
                        }
                        if ml_result
                        else None
                    ),
                },
            })

        # Guard against label collapse: if the nearest prototype is still too far,
        # trust the heuristic fallback even if relative vote confidence is high.
        match_threshold = max(0.10, min(float(self.pattern_match_threshold), 0.95))
        if best_distance_overall is None or best_distance_overall > match_threshold:
            return _remember({
                "label": fallback,
                "confidence": confidence,
                "source": "fallback_distance_gate",
                "explain": {
                    **dict(matcher_result.explain),
                    "decision_reason": "distance_gate_reject",
                },
            })

        # Keep fallback if confidence is too low.
        if confidence < 0.45:
            return _remember({
                "label": fallback,
                "confidence": confidence,
                "source": "fallback_low_confidence",
                "explain": {
                    **dict(matcher_result.explain),
                    "decision_reason": "low_confidence_reject",
                },
            })

        return _remember({
            "label": final_label,
            "confidence": confidence,
            "source": source,
            "explain": {
                **dict(matcher_result.explain),
                "decision_reason": decision_reason,
                "fusion": {
                    "phase": "phase1",
                    "weights": {
                        "boosting": 0.45,
                        "shape": 0.35,
                        "prototype": 0.20,
                    },
                    "inputs": {
                        "boosting": round(float(ml_conf), 4),
                        "shape": round(float(shape_confidence), 4),
                        "prototype": round(float(prototype_confidence), 4),
                    },
                    "final_score": round(float(confidence), 4),
                },
                "ml": (
                    {
                        "label": ml_result.label,
                        "confidence": round(float(ml_result.confidence), 4),
                        "source": ml_result.source,
                        "top_n": ml_result.top_n,
                    }
                    if ml_result
                    else None
                ),
            },
        })

    def run_nightly_learning_pass(self, merge_tolerance: float = 0.20, max_patterns: int = 800) -> Dict:
        """Run a lightweight nightly pattern consolidation pass.

        Keeps runtime cheap by running once nightly and merging very similar active
        patterns so the model becomes more stable over time.
        """
        if not self._patterns_conn:
            return {"ok": False, "error": "storage not connected"}

        patterns = self.list_patterns(limit=max_patterns)
        active = [p for p in patterns if p.get("status") == "active"]
        if len(active) < 2:
            return {"ok": True, "merged": 0, "patterns_considered": len(active)}

        # Build best non-overlapping merge pairs first, then apply in one transaction.
        pairs: List[Tuple[Dict, Dict, float]] = []
        for idx in range(len(active)):
            a = active[idx]
            for jdx in range(idx + 1, len(active)):
                b = active[jdx]
                if (a.get("phase_mode") or "unknown") != (b.get("phase_mode") or "unknown"):
                    continue
                dist = self._pattern_distance(a, b)
                if dist <= merge_tolerance:
                    pairs.append((a, b, dist))

        if not pairs:
            return {"ok": True, "merged": 0, "patterns_considered": len(active)}

        pairs.sort(key=lambda item: item[2])
        used_ids = set()
        selected: List[Tuple[Dict, Dict, float]] = []
        for a, b, dist in pairs:
            a_id = int(a["id"])
            b_id = int(b["id"])
            if a_id in used_ids or b_id in used_ids:
                continue
            selected.append((a, b, dist))
            used_ids.add(a_id)
            used_ids.add(b_id)

        if not selected:
            return {"ok": True, "merged": 0, "patterns_considered": len(active)}

        def _weighted_value(a_val: float, a_n: int, b_val: float, b_n: int) -> float:
            total = max(a_n + b_n, 1)
            return ((a_val * a_n) + (b_val * b_n)) / float(total)

        merged = 0
        now = datetime.now().isoformat()
        try:
            with self._patterns_conn:
                for a, b, _dist in selected:
                    a_id = int(a["id"])
                    b_id = int(b["id"])
                    a_seen = int(a.get("seen_count", 1))
                    b_seen = int(b.get("seen_count", 1))
                    total_seen = a_seen + b_seen

                    avg_power = _weighted_value(float(a["avg_power_w"]), a_seen, float(b["avg_power_w"]), b_seen)
                    peak_power = _weighted_value(float(a["peak_power_w"]), a_seen, float(b["peak_power_w"]), b_seen)
                    duration = _weighted_value(float(a["duration_s"]), a_seen, float(b["duration_s"]), b_seen)
                    energy = _weighted_value(float(a["energy_wh"]), a_seen, float(b["energy_wh"]), b_seen)
                    avg_phases = _weighted_value(
                        float(a.get("avg_active_phases", 1.0)),
                        a_seen,
                        float(b.get("avg_active_phases", 1.0)),
                        b_seen,
                    )
                    quality_avg = _weighted_value(
                        float(a.get("quality_score_avg", 0.5)),
                        a_seen,
                        float(b.get("quality_score_avg", 0.5)),
                        b_seen,
                    )

                    # Prefer confirmed label, then non-unknown suggestion.
                    chosen_label = str(a.get("user_label") or b.get("user_label") or "").strip() or None
                    candidates = [
                        str(a.get("suggestion_type") or "").strip(),
                        str(b.get("suggestion_type") or "").strip(),
                    ]
                    chosen_suggestion = next((c for c in candidates if c and c != "unknown"), "unknown")

                    first_seen = self._iso_min(str(a.get("first_seen") or now), str(b.get("first_seen") or now))
                    last_seen = self._iso_max(str(a.get("last_seen") or now), str(b.get("last_seen") or now))
                    first_seen, last_seen = self._normalize_seen_bounds(
                        first_seen=first_seen,
                        last_seen=last_seen,
                        fallback_start=first_seen,
                        fallback_end=last_seen,
                    )

                    self._patterns_conn.execute(
                        """
                        UPDATE learned_patterns
                        SET updated_at = ?,
                            first_seen = ?,
                            last_seen = ?,
                            seen_count = ?,
                            avg_power_w = ?,
                            peak_power_w = ?,
                            duration_s = ?,
                            energy_wh = ?,
                            avg_active_phases = ?,
                            quality_score_avg = ?,
                            suggestion_type = ?,
                            user_label = ?
                        WHERE id = ?
                        """,
                        (
                            now,
                            first_seen,
                            last_seen,
                            total_seen,
                            avg_power,
                            peak_power,
                            duration,
                            energy,
                            avg_phases,
                            quality_avg,
                            chosen_suggestion,
                            chosen_label,
                            a_id,
                        ),
                    )
                    self._patterns_conn.execute("DELETE FROM learned_patterns WHERE id = ?", (b_id,))
                    merged += 1

            return {
                "ok": True,
                "merged": merged,
                "pairs_considered": len(pairs),
                "patterns_considered": len(active),
            }
        except Exception as e:
            logger.error(f"Nightly learning pass failed: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _normalize_pattern_name(name: str) -> str:
        text = str(name or "").strip().lower()
        if not text:
            return "unbekannt"
        if text.endswith("_like"):
            text = text[:-5]
        return text.replace("_", " ")

    @staticmethod
    def _frequency_per_day(seen_count: int, first_seen_iso: str, last_seen_iso: str) -> float:
        try:
            first_dt = datetime.fromisoformat(str(first_seen_iso))
            last_dt = datetime.fromisoformat(str(last_seen_iso))
            span_days = max((last_dt - first_dt).total_seconds() / 86400.0, 1.0 / 24.0)
            return max(float(seen_count), 0.0) / span_days
        except Exception:
            return 0.0

    @staticmethod
    def _refine_label_by_frequency(base_label: str, avg_power_w: float, frequency_per_day: float) -> tuple[str, str]:
        label = str(base_label or "unknown").strip() or "unknown"
        if frequency_per_day > 50.0:
            if avg_power_w <= 350.0:
                return ("fridge", "frequency_gt_50_low_power")
            return ("pump", "frequency_gt_50")
        if frequency_per_day < 5.0 and label == "unknown":
            return ("manual_device", "frequency_lt_5_unknown")
        return (label, "frequency_rule_not_applied")

    def list_patterns(self, limit: int = 100) -> List[Dict]:
        if not self._patterns_conn:
            return []
        if not self._table_exists(self._patterns_conn, "learned_patterns"):
            logger.info("Pattern list unavailable: table learned_patterns is missing")
            return []
        try:
            cur = self._patterns_conn.execute(
                """
                SELECT id, created_at, updated_at, first_seen, last_seen, seen_count,
                       avg_power_w, peak_power_w, duration_s, energy_wh,
                      suggestion_type, user_label, status,
                      COALESCE(avg_active_phases, 1.0), COALESCE(phase_mode, 'unknown'), COALESCE(phase, 'L1'),
                      COALESCE(power_variance, 0.0), COALESCE(duty_cycle, 0.0),
                      COALESCE(peak_to_avg_ratio, 1.0),
                      COALESCE(operating_modes, '[]'), COALESCE(has_multiple_modes, 0),
                      COALESCE(typical_interval_s, 0.0), COALESCE(avg_hour_of_day, 12.0),
                      COALESCE(last_intervals_json, '[]'), COALESCE(hour_distribution_json, '{}'),
                      COALESCE(rise_rate_w_per_s, 0.0), COALESCE(fall_rate_w_per_s, 0.0),
                                                COALESCE(num_substates, 0), COALESCE(step_count, 0),
                                                COALESCE(has_heating_pattern, 0), COALESCE(has_motor_pattern, 0),
                                                COALESCE(profile_points_json, '[]'), COALESCE(quality_score_avg, 0.5),
                                                COALESCE(device_id, 0), COALESCE(confidence_score, 0.0),
                                                COALESCE(frequency_per_day, 0.0), COALESCE(candidate_name, ''),
                                                COALESCE(is_confirmed, 0), COALESCE(shape_vector_json, '[]'),
                                                COALESCE(prototype_hash, ''),
                                                baseline_before_w_avg, baseline_after_w_avg,
                                                delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                                                COALESCE(delta_profile_points_json, '[]'),
                                                COALESCE(delta_shape_vector_json, '[]'),
                                                COALESCE(plateau_count, 0),
                                                COALESCE(curve_hash, ''),
                                                COALESCE(shape_signature, ''),
                                                COALESCE(avg_delta_power_w, delta_avg_power_w),
                                                COALESCE(avg_duration_s, duration_s),
                                                COALESCE(avg_peak_power_w, peak_power_w),
                                                COALESCE(avg_inrush_duration_s, 0.0),
                                                COALESCE(occurrence_count, seen_count),
                                                COALESCE(device_group_id, ''),
                                                COALESCE(mode_key, '')
                FROM learned_patterns
                ORDER BY seen_count DESC, last_seen DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
            out: List[Dict] = []
            for row in rows:
                seen_count = int(row[5])
                
                # Parse datetimes and normalize to naive (remove local timezone if present)
                try:
                    created_ts = datetime.fromisoformat(row[1]) if row[1] else datetime.now()
                    if created_ts.tzinfo:
                        created_ts = created_ts.replace(tzinfo=None)
                except (ValueError, TypeError):
                    created_ts = datetime.now()
                
                try:
                    last_seen_ts = datetime.fromisoformat(row[4]) if row[4] else created_ts
                    if last_seen_ts.tzinfo:
                        last_seen_ts = last_seen_ts.replace(tzinfo=None)
                except (ValueError, TypeError):
                    last_seen_ts = created_ts
                
                # Berechne Stabilität (Varianz normiert)
                avg_power = float(row[6])
                power_variance = float(row[16] or 0.0)
                if avg_power > 10:
                    # Normalize by mean power squared so variance in W^2 does not
                    # collapse almost all patterns to 0% stability.
                    normalized_variance = power_variance / max(avg_power * avg_power, 1.0)
                    stability_score = max(0, min(100, 100 - (normalized_variance * 100)))
                else:
                    stability_score = 50
                
                # Berechne Spitzenwert/Durchschnitt Verhältnis
                peak_to_avg = float(row[18] or 1.0)
                
                # Berechne Häufigkeitsmuster
                days_since_created = max(1, (last_seen_ts - created_ts).days)
                frequency_per_day = seen_count / max(1, days_since_created) if days_since_created > 0 else 0
                
                # Bestimme Häufigkeits-Label
                if frequency_per_day >= 1.5:
                    frequency_label = f">1x tägl. (~{int(frequency_per_day)}x)"
                elif frequency_per_day >= 0.5:
                    frequency_label = "1x tägl."
                elif frequency_per_day >= 0.2:
                    frequency_label = "1-2x/Woche"
                elif frequency_per_day >= 0.05:
                    frequency_label = "1-2x/Mon."
                else:
                    frequency_label = "selten"
                
                # Parse operating modes (multi-mode learning!)
                operating_modes = []
                try:
                    modes_json = str(row[19] or "[]")
                    operating_modes = json.loads(modes_json) if modes_json else []
                except Exception:
                    operating_modes = []
                
                has_multiple_modes = bool(int(row[20] or 0))
                profile_points = []
                try:
                    profile_points = self._normalize_profile_points(json.loads(str(row[31] or "[]")))
                except Exception:
                    profile_points = []
                quality_score_avg = max(0.0, min(1.0, float(row[32] or 0.5)))
                # Confidence combines quality with pattern maturity (seen_count saturation).
                maturity = 1.0 - math.exp(-max(seen_count, 0) / 8.0)
                confidence_score = max(0.0, min(100.0, ((quality_score_avg * 0.7) + (maturity * 0.3)) * 100.0))
                raw_phase_mode = str(row[14] or "unknown")
                phase_label = str(row[15] or "L1")
                avg_active_phases = float(row[13] or 1.0)
                effective_phase_mode = raw_phase_mode
                if phase_label in {"L1", "L2", "L3"} and avg_active_phases <= 1.5:
                    effective_phase_mode = "single_phase"
                
                out.append(
                    {
                        "id": int(row[0]),
                        "created_at": row[1],
                        "updated_at": row[2],
                        "first_seen": row[3],
                        "last_seen": row[4],
                        "seen_count": seen_count,
                        "avg_power_w": float(row[6]),
                        "peak_power_w": float(row[7]),
                        "duration_s": float(row[8]),
                        "energy_wh": float(row[9]),
                        "suggestion_type": row[10],
                        "user_label": row[11],
                        "status": row[12],
                        "avg_active_phases": avg_active_phases,
                        "phase_mode": effective_phase_mode,
                        "phase": phase_label,
                        "power_variance": power_variance,
                        "duty_cycle": float(row[17] or 0.0),
                        "peak_to_avg_ratio": peak_to_avg,
                        "stability_score": int(stability_score),
                        "frequency_label": frequency_label,
                        "frequency_per_day": round(frequency_per_day, 2),
                        "operating_modes": operating_modes,  # Multi-mode learning!
                        "has_multiple_modes": has_multiple_modes,
                        "typical_interval_s": float(row[21] or 0.0),
                        "avg_hour_of_day": float(row[22] or 12.0),
                        "last_intervals_json": row[23] or "[]",
                        "hour_distribution_json": row[24] or "{}",
                        "rise_rate_w_per_s": float(row[25] or 0.0),
                        "fall_rate_w_per_s": float(row[26] or 0.0),
                        "num_substates": int(row[27] or 0),
                        "step_count": int(row[28] or 0),
                        "has_heating_pattern": int(row[29] or 0),
                        "has_motor_pattern": int(row[30] or 0),
                        "profile_points": profile_points,
                        "quality_score_avg": quality_score_avg,
                        "confidence_score": round(confidence_score, 1),
                        "device_id": int(row[33] or 0),
                        "confidence_score_db": float(row[34] or 0.0),
                        "frequency_per_day_db": float(row[35] or 0.0),
                        "candidate_name": str(row[36] or self._normalize_pattern_name(row[11] or row[10])),
                        "is_confirmed": bool(int(row[37] or 0)) or bool(str(row[11] or "").strip()),
                        "shape_vector_json": str(row[38] or "[]"),
                        "prototype_hash": str(row[39] or ""),
                        "baseline_before_w_avg": float(row[40] or 0.0),
                        "baseline_after_w_avg": float(row[41] or 0.0),
                        "delta_avg_power_w": float(row[42] or 0.0),
                        "delta_peak_power_w": float(row[43] or 0.0),
                        "delta_energy_wh": float(row[44] or 0.0),
                        "delta_profile_points": self._normalize_profile_points(json.loads(str(row[45] or "[]"))) if str(row[45] or "").strip() else [],
                        "delta_shape_vector_json": str(row[46] or "[]"),
                        "plateau_count": int(row[47] or 0),
                        "curve_hash": str(row[48] or ""),
                        "shape_signature": str(row[49] or ""),
                        "avg_delta_power_w": float(row[50] or 0.0),
                        "avg_duration_s": float(row[51] or 0.0),
                        "avg_peak_power_w": float(row[52] or 0.0),
                        "avg_inrush_duration_s": float(row[53] or 0.0),
                        "occurrence_count": int(row[54] or seen_count),
                        "device_group_id": str(row[55] or ""),
                        "mode_key": str(row[56] or ""),
                    }
                )

            # Build device groups: multiple patterns/modes that likely belong to one device label.
            group_meta: Dict[str, Dict[str, int]] = {}
            for item in out:
                key = self._device_group_key(item)
                item["device_group_key"] = key
                group_info = group_meta.setdefault(key, {"size": 0})
                group_info["size"] += 1

            for item in out:
                key = str(item.get("device_group_key") or "unbekannt")
                item["device_group_label"] = key
                item["device_group_size"] = int(group_meta.get(key, {}).get("size", 1))

            return out
        except Exception as e:
            logger.error(f"Failed to list learned patterns: {e}", exc_info=True)
            return []

    def learn_cycle_pattern(self, cycle: Dict, suggestion_type: str, tolerance: float = 0.38) -> Dict:
        """Upsert one cycle into learned_patterns and return the matched/created pattern."""
        if not self._patterns_conn:
            return {"matched": False, "pattern": None}
        if not self.online_learning_enabled:
            return {
                "matched": False,
                "pattern": None,
                "skipped": True,
                "reason": "online_learning_disabled",
            }

        prepared = prepare_cycle_for_learning(
            cycle=cycle,
            suggestion_type=suggestion_type,
            quality_min_accept=float(self.LEARNING_PARAMS["quality_min_accept"]),
            quality_fn=self._learning_quality_score,
            augment_fn=self._augment_cycle_baseline_delta,
            infer_unknown_fn=self._infer_unknown_subclass,
            shape_signature_fn=self._shape_signature_from_cycle,
            curve_hash_fn=self._curve_hash_from_cycle,
            mode_key_fn=self._mode_key_from_cycle,
            group_id_fn=self._device_group_id,
        )
        quality_score = float(prepared.quality_score)
        cycle = dict(prepared.cycle)
        suggestion_seed = str(prepared.suggestion_seed)

        if prepared.skipped_reason == "low_quality_cycle":
            return {
                "matched": False,
                "pattern": None,
                "skipped": True,
                "reason": "low_quality_cycle",
                "quality_score": quality_score,
            }

        if prepared.skipped_reason == "baseline_unstable":
            return {
                "matched": False,
                "pattern": None,
                "skipped": True,
                "reason": "baseline_unstable",
                "quality_score": quality_score,
                "baseline_quality_score": float(cycle.get("baseline_quality_score", 0.0) or 0.0),
            }

        if self._is_session_duplicate(cycle, suggestion_seed):
            self.log_training_decision(
                event_id=None,
                accepted=False,
                reason="session_duplicate_cycle",
                label=suggestion_seed,
                dedup_result="session_skip",
                matched_pattern_id=None,
                similarity_score=1.0,
                dedup_reason="same_cycle_already_seen_in_runtime_session",
            )
            return {
                "matched": False,
                "pattern": None,
                "skipped": True,
                "reason": "session_duplicate_cycle",
                "dedup": {
                    "result": "session_skip",
                    "matched_pattern_id": None,
                    "similarity_score": 1.0,
                    "reason": "same_cycle_already_seen_in_runtime_session",
                },
            }

        now = datetime.now().isoformat()
        patterns = self.list_patterns(limit=500)

        # Get phase from cycle (default to L1 if not specified)
        cycle_phase = str(cycle.get("phase", "L1"))

        match_result = find_best_pattern_match(
            patterns=patterns,
            cycle=cycle,
            phase=cycle_phase,
            similarity_fn=self._dedup_similarity,
        )
        best = match_result.best
        best_distance = float(match_result.best_distance)
        best_similarity = float(match_result.best_similarity)

        dedup_decision = decide_dedup_action(
            best=best,
            cycle=cycle,
            suggestion_seed=suggestion_seed,
            best_similarity=best_similarity,
            dedup_update_similarity=float(self.LEARNING_PARAMS["dedup_update_similarity"]),
            dedup_merge_similarity=float(self.LEARNING_PARAMS["dedup_merge_similarity"]),
            mode_key_fn=self._mode_key_from_cycle,
            group_id_fn=self._device_group_id,
        )
        dedup_result = dedup_decision.result
        dedup_reason = dedup_decision.reason
        force_match = bool(dedup_decision.force_match)
        logger.debug(
            "learn_cycle_pattern dedup decision: result=%s reason=%s similarity=%.4f best_id=%s",
            dedup_result,
            dedup_reason,
            best_similarity,
            int(best.get("id", 0) or 0) if best else None,
        )

        try:
            best_tolerance = tolerance
            if best:
                seen = max(int(best.get("seen_count", 1)), 1)
                best_tolerance = max(0.22, tolerance - min((seen - 1) * 0.005, 0.14))

            if best and force_match:
                seen_count = int(best["seen_count"]) + 1
                alpha = 1.0 / seen_count

                avg_power = float(best["avg_power_w"]) * (1.0 - alpha) + float(cycle["avg_power_w"]) * alpha
                peak_power = float(best["peak_power_w"]) * (1.0 - alpha) + float(cycle["peak_power_w"]) * alpha
                duration = float(best["duration_s"]) * (1.0 - alpha) + float(cycle["duration_s"]) * alpha
                energy = float(best["energy_wh"]) * (1.0 - alpha) + float(cycle["energy_wh"]) * alpha
                avg_active_phases = float(best.get("avg_active_phases", 1.0)) * (1.0 - alpha) + float(cycle.get("active_phase_count", 1.0)) * alpha
                phase_mode = str(cycle.get("phase_mode") or best.get("phase_mode") or "unknown")
                phase = str(cycle.get("phase") or best.get("phase") or "L1")
                power_variance = float(best.get("power_variance", 0.0)) * (1.0 - alpha) + float(cycle.get("power_variance", 0.0)) * alpha
                rise_rate = float(best.get("rise_rate_w_per_s", 0.0)) * (1.0 - alpha) + float(cycle.get("rise_rate_w_per_s", 0.0)) * alpha
                fall_rate = float(best.get("fall_rate_w_per_s", 0.0)) * (1.0 - alpha) + float(cycle.get("fall_rate_w_per_s", 0.0)) * alpha
                duty_cycle = float(best.get("duty_cycle", 0.0)) * (1.0 - alpha) + float(cycle.get("duty_cycle", 0.0)) * alpha
                peak_to_avg = float(best.get("peak_to_avg_ratio", 1.0)) * (1.0 - alpha) + float(cycle.get("peak_to_avg_ratio", 1.0)) * alpha
                num_substates = int(round(float(best.get("num_substates", 0)) * (1.0 - alpha) + float(cycle.get("num_substates", 0)) * alpha))
                step_count = int(round(float(best.get("step_count", 0)) * (1.0 - alpha) + float(cycle.get("step_count", 0)) * alpha))
                has_heating = 1 if (bool(best.get("has_heating_pattern", 0)) or bool(cycle.get("has_heating_pattern", False))) else 0
                has_motor = 1 if (bool(best.get("has_motor_pattern", 0)) or bool(cycle.get("has_motor_pattern", False))) else 0
                profile_points = self._normalize_profile_points(cycle.get("profile_points", []))
                delta_profile_points = self._normalize_profile_points(cycle.get("delta_profile_points", []))
                if not profile_points:
                    profile_points = self._normalize_profile_points(best.get("profile_points", []))
                profile_points_json = json.dumps(profile_points)
                shape_vector_json = json.dumps(self._resample_profile_points(profile_points, sample_count=32))
                delta_profile_points_json = json.dumps(delta_profile_points)
                delta_shape_vector_json = json.dumps(cycle.get("delta_shape_vector", []))
                prototype_hash = self._prototype_hash_from_cycle(cycle)
                baseline_before_w_avg = float(best.get("baseline_before_w_avg", cycle.get("baseline_before_w", 0.0)) or 0.0) * (1.0 - alpha) + float(cycle.get("baseline_before_w", 0.0) or 0.0) * alpha
                baseline_after_w_avg = float(best.get("baseline_after_w_avg", cycle.get("baseline_after_w", 0.0)) or 0.0) * (1.0 - alpha) + float(cycle.get("baseline_after_w", 0.0) or 0.0) * alpha
                delta_avg_power_w = float(best.get("delta_avg_power_w", 0.0) or 0.0) * (1.0 - alpha) + float(cycle.get("delta_avg_power_w", 0.0) or 0.0) * alpha
                delta_peak_power_w = float(best.get("delta_peak_power_w", 0.0) or 0.0) * (1.0 - alpha) + float(cycle.get("delta_peak_power_w", 0.0) or 0.0) * alpha
                delta_energy_wh = float(best.get("delta_energy_wh", 0.0) or 0.0) * (1.0 - alpha) + float(cycle.get("delta_energy_wh", 0.0) or 0.0) * alpha
                plateau_count = int(round(float(best.get("plateau_count", 0) or 0.0) * (1.0 - alpha) + float(cycle.get("plateau_count", 0) or 0.0) * alpha))
                avg_delta_power_w = float(best.get("avg_delta_power_w", best.get("delta_avg_power_w", 0.0)) or 0.0) * (1.0 - alpha) + float(cycle.get("delta_avg_power_w", 0.0) or 0.0) * alpha
                avg_duration_s = float(best.get("avg_duration_s", best.get("duration_s", 0.0)) or 0.0) * (1.0 - alpha) + float(cycle.get("duration_s", 0.0) or 0.0) * alpha
                avg_peak_power_w = float(best.get("avg_peak_power_w", best.get("peak_power_w", 0.0)) or 0.0) * (1.0 - alpha) + float(cycle.get("peak_power_w", 0.0) or 0.0) * alpha
                avg_inrush_duration_s = float(best.get("avg_inrush_duration_s", 0.0) or 0.0) * (1.0 - alpha) + float(cycle.get("settling_time_s", 0.0) or 0.0) * alpha
                occurrence_count = int(best.get("occurrence_count", seen_count - 1) or (seen_count - 1)) + 1
                curve_hash = str(cycle.get("curve_hash") or self._curve_hash_from_cycle(cycle))
                shape_signature = str(cycle.get("shape_signature") or self._shape_signature_from_cycle(cycle))
                mode_key = str(cycle.get("mode_key") or self._mode_key_from_cycle(cycle))
                quality_score_avg = float(best.get("quality_score_avg", 0.5)) * (1.0 - alpha) + quality_score * alpha
                candidate_mode = self._build_mode_signature(cycle, str(cycle.get("end_ts", now)))
                merged_modes = self._merge_operating_modes(
                    self._parse_operating_modes(best.get("operating_modes", [])),
                    candidate_mode,
                )
                operating_modes_json = json.dumps(merged_modes)
                has_multiple_modes = 1 if len(merged_modes) >= 2 else 0
                
                # Temporal pattern tracking - calculate interval since last occurrence
                last_seen_str = best.get("last_seen", cycle["end_ts"])
                try:
                    last_seen_dt = datetime.fromisoformat(last_seen_str)
                    cycle_end_dt = datetime.fromisoformat(cycle["end_ts"])
                    interval_s = (cycle_end_dt - last_seen_dt).total_seconds()
                    
                    # Update last_intervals history (keep last 10)
                    last_intervals = json.loads(best.get("last_intervals_json", "[]"))
                    if interval_s > 0:
                        last_intervals.append(interval_s)
                    if len(last_intervals) > 10:
                        last_intervals = last_intervals[-10:]
                    last_intervals_json = json.dumps(last_intervals)
                    
                    # Calculate typical interval (median of last intervals)
                    if len(last_intervals) >= 2:
                        sorted_intervals = sorted(last_intervals)
                        median_idx = len(sorted_intervals) // 2
                        typical_interval_s = sorted_intervals[median_idx]
                    else:
                        typical_interval_s = interval_s if interval_s > 0 else float(best.get("typical_interval_s", 0.0))
                    
                    # Update hour distribution
                    cycle_hour = cycle_end_dt.hour + cycle_end_dt.minute / 60.0
                    hour_dist = json.loads(best.get("hour_distribution_json", "{}"))
                    hour_bucket = str(cycle_end_dt.hour)  # Bucket by hour
                    hour_dist[hour_bucket] = hour_dist.get(hour_bucket, 0) + 1
                    hour_distribution_json = json.dumps(hour_dist)
                    
                    # Calculate weighted average hour of day
                    total_count = sum(hour_dist.values())
                    weighted_hour = sum(int(h) * c for h, c in hour_dist.items()) / total_count
                    avg_hour_of_day = weighted_hour
                    
                except (ValueError, TypeError) as e:
                    logger.debug(f"Failed to calculate temporal patterns: {e}")
                    typical_interval_s = best.get("typical_interval_s", 0.0)
                    avg_hour_of_day = best.get("avg_hour_of_day", 12.0)
                    last_intervals_json = best.get("last_intervals_json", "[]")
                    hour_distribution_json = best.get("hour_distribution_json", "{}")

                first_seen_norm, last_seen_norm = self._normalize_seen_bounds(
                    first_seen=self._iso_min(str(best.get("first_seen") or ""), str(cycle.get("start_ts") or now)),
                    last_seen=self._iso_max(str(best.get("last_seen") or ""), str(cycle.get("end_ts") or now)),
                    fallback_start=str(cycle.get("start_ts") or now),
                    fallback_end=str(cycle.get("end_ts") or now),
                )

                base_label = str(best.get("suggestion_type") or suggestion_type or "unknown")
                frequency_per_day = self._frequency_per_day(
                    seen_count=seen_count,
                    first_seen_iso=first_seen_norm,
                    last_seen_iso=last_seen_norm,
                )
                auto_label, freq_rule = self._refine_label_by_frequency(base_label, avg_power, frequency_per_day)
                confirmed_label = str(best.get("user_label") or "").strip()
                final_label = confirmed_label or auto_label
                if confirmed_label:
                    freq_rule = "user_confirmed_locked"
                stored_suggestion = base_label if confirmed_label else auto_label
                confidence_score_norm = max(0.0, min(1.0, (quality_score_avg * 0.7) + ((1.0 - math.exp(-seen_count / 8.0)) * 0.3)))
                candidate_name = self._normalize_pattern_name(final_label)
                device_id = self._get_or_create_device(
                    label=final_label,
                    phase=phase,
                    confidence=confidence_score_norm,
                    confirmed=bool(confirmed_label),
                )
                device_subclass = self._derive_device_subclass(final_label, cycle)
                device_group_id = str(cycle.get("device_group_id") or self._device_group_id(final_label, cycle))

                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE learned_patterns
                        SET updated_at = ?, first_seen = ?, last_seen = ?, seen_count = ?,
                            avg_power_w = ?, peak_power_w = ?, duration_s = ?, energy_wh = ?,
                            avg_active_phases = ?, phase_mode = ?, phase = ?,
                            power_variance = ?, rise_rate_w_per_s = ?, fall_rate_w_per_s = ?,
                            duty_cycle = ?, peak_to_avg_ratio = ?, num_substates = ?, step_count = ?,
                            has_heating_pattern = ?, has_motor_pattern = ?,
                            profile_points_json = ?,
                            baseline_before_w_avg = ?, baseline_after_w_avg = ?,
                            delta_avg_power_w = ?, delta_peak_power_w = ?, delta_energy_wh = ?,
                            delta_profile_points_json = ?, delta_shape_vector_json = ?, plateau_count = ?,
                            curve_hash = ?, shape_signature = ?,
                            avg_delta_power_w = ?, avg_duration_s = ?, avg_peak_power_w = ?, avg_inrush_duration_s = ?,
                            occurrence_count = ?, device_group_id = ?, mode_key = ?,
                            quality_score_avg = ?,
                            suggestion_type = ?,
                            device_id = ?,
                            confidence_score = ?,
                            frequency_per_day = ?,
                            candidate_name = ?,
                            is_confirmed = ?,
                            shape_vector_json = ?,
                            prototype_hash = ?,
                            operating_modes = ?,
                            has_multiple_modes = ?,
                            typical_interval_s = ?, avg_hour_of_day = ?,
                            last_intervals_json = ?, hour_distribution_json = ?
                        WHERE id = ?
                        """,
                        (
                            now,
                            first_seen_norm,
                            last_seen_norm,
                            seen_count,
                            avg_power,
                            peak_power,
                            duration,
                            energy,
                            avg_active_phases,
                            phase_mode,
                            phase,
                            power_variance,
                            rise_rate,
                            fall_rate,
                            duty_cycle,
                            peak_to_avg,
                            num_substates,
                            step_count,
                            has_heating,
                            has_motor,
                            profile_points_json,
                            baseline_before_w_avg,
                            baseline_after_w_avg,
                            delta_avg_power_w,
                            delta_peak_power_w,
                            delta_energy_wh,
                            delta_profile_points_json,
                            delta_shape_vector_json,
                            plateau_count,
                            curve_hash,
                            shape_signature,
                            avg_delta_power_w,
                            avg_duration_s,
                            avg_peak_power_w,
                            avg_inrush_duration_s,
                            occurrence_count,
                            device_group_id,
                            mode_key,
                            quality_score_avg,
                            stored_suggestion,
                            int(device_id) if device_id else None,
                            confidence_score_norm,
                            frequency_per_day,
                            candidate_name,
                            1 if bool(confirmed_label) else int(best.get("is_confirmed", 0) or 0),
                            shape_vector_json,
                            prototype_hash,
                            operating_modes_json,
                            has_multiple_modes,
                            typical_interval_s,
                            avg_hour_of_day,
                            last_intervals_json,
                            hour_distribution_json,
                            int(best["id"]),
                        ),
                    )
                    if device_id:
                        self._patterns_conn.execute(
                            """
                            UPDATE devices
                            SET device_subclass = ?,
                                baseline_range_min_w = CASE WHEN baseline_range_min_w IS NULL THEN ? ELSE MIN(baseline_range_min_w, ?) END,
                                baseline_range_max_w = CASE WHEN baseline_range_max_w IS NULL THEN ? ELSE MAX(baseline_range_max_w, ?) END,
                                updated_at = ?
                            WHERE device_id = ?
                            """,
                            (
                                device_subclass,
                                float(cycle.get("baseline_before_w", 0.0) or 0.0),
                                float(cycle.get("baseline_before_w", 0.0) or 0.0),
                                float(cycle.get("baseline_after_w", cycle.get("baseline_before_w", 0.0)) or 0.0),
                                float(cycle.get("baseline_after_w", cycle.get("baseline_before_w", 0.0)) or 0.0),
                                now,
                                int(device_id),
                            ),
                        )

                logger.info(
                    "Pattern classify/update: id=%s label=%s freq_per_day=%.2f rule=%s features[var=%.2f substates=%s steps=%s rise=%.2f fall=%.2f]",
                    int(best["id"]),
                    final_label,
                    frequency_per_day,
                    freq_rule,
                    power_variance,
                    num_substates,
                    step_count,
                    rise_rate,
                    fall_rate,
                )

                best.update(
                    {
                        "updated_at": now,
                        "first_seen": first_seen_norm,
                        "last_seen": last_seen_norm,
                        "seen_count": seen_count,
                        "avg_power_w": avg_power,
                        "peak_power_w": peak_power,
                        "duration_s": duration,
                        "energy_wh": energy,
                        "avg_active_phases": avg_active_phases,
                        "phase_mode": phase_mode,
                        "phase": phase,
                        "power_variance": power_variance,
                        "rise_rate_w_per_s": rise_rate,
                        "fall_rate_w_per_s": fall_rate,
                        "duty_cycle": duty_cycle,
                        "peak_to_avg_ratio": peak_to_avg,
                        "num_substates": num_substates,
                        "step_count": step_count,
                        "has_heating_pattern": has_heating,
                        "has_motor_pattern": has_motor,
                        "profile_points": profile_points,
                        "baseline_before_w_avg": baseline_before_w_avg,
                        "baseline_after_w_avg": baseline_after_w_avg,
                        "delta_avg_power_w": delta_avg_power_w,
                        "delta_peak_power_w": delta_peak_power_w,
                        "delta_energy_wh": delta_energy_wh,
                        "delta_profile_points": delta_profile_points,
                        "delta_shape_vector_json": delta_shape_vector_json,
                        "plateau_count": plateau_count,
                        "curve_hash": curve_hash,
                        "shape_signature": shape_signature,
                        "avg_delta_power_w": avg_delta_power_w,
                        "avg_duration_s": avg_duration_s,
                        "avg_peak_power_w": avg_peak_power_w,
                        "avg_inrush_duration_s": avg_inrush_duration_s,
                        "occurrence_count": occurrence_count,
                        "device_group_id": device_group_id,
                        "mode_key": mode_key,
                        "quality_score_avg": quality_score_avg,
                        "suggestion_type": stored_suggestion,
                        "device_id": int(device_id) if device_id else int(best.get("device_id", 0) or 0),
                        "confidence_score_db": confidence_score_norm,
                        "frequency_per_day_db": frequency_per_day,
                        "candidate_name": candidate_name,
                        "is_confirmed": bool(best.get("user_label")) or bool(best.get("is_confirmed", False)),
                        "shape_vector_json": shape_vector_json,
                        "prototype_hash": prototype_hash,
                        "operating_modes": merged_modes,
                        "has_multiple_modes": bool(has_multiple_modes),
                    }
                )
                self._record_pattern_features(int(best["id"]), cycle)
                self._record_pattern_history_snapshot(best)
                self._upsert_patterns_mirror(best)
                event_id = self._record_cycle_event(
                    cycle=cycle,
                    assigned_pattern_id=int(best["id"]),
                    assigned_device_id=int(device_id) if device_id else None,
                    final_label=final_label,
                    final_confidence=float(self._last_hybrid_decision.get("confidence", 0.0) or 0.0),
                    dedup_result=dedup_result,
                    matched_pattern_id=int(best["id"]),
                    similarity_score=best_similarity,
                    dedup_reason=dedup_reason,
                )
                self.log_training_decision(
                    event_id=event_id,
                    accepted=True,
                    reason="dedup_update_existing",
                    label=final_label,
                    dedup_result=dedup_result,
                    matched_pattern_id=int(best["id"]),
                    similarity_score=best_similarity,
                    dedup_reason=dedup_reason,
                )
                self._record_classification_log(
                    event_id=event_id,
                    pattern_id=int(best["id"]),
                    device_id=int(device_id) if device_id else None,
                    final_label=final_label,
                    final_confidence=float(self._last_hybrid_decision.get("confidence", 0.0) or 0.0),
                    decision_source=str(self._last_hybrid_decision.get("source", "pattern_update")),
                )
                return {
                    "matched": True,
                    "distance": best_distance,
                    "similarity": best_similarity,
                    "dedup": {
                        "result": dedup_result,
                        "matched_pattern_id": int(best["id"]),
                        "similarity_score": best_similarity,
                        "reason": dedup_reason,
                    },
                    "pattern": best,
                }

            with self._patterns_conn:
                # Extract advanced features if available
                power_variance = float(cycle.get("power_variance", 0.0))
                rise_rate = float(cycle.get("rise_rate_w_per_s", 0.0))
                fall_rate = float(cycle.get("fall_rate_w_per_s", 0.0))
                duty_cycle = float(cycle.get("duty_cycle", 0.0))
                peak_to_avg = float(cycle.get("peak_to_avg_ratio", 1.0))
                num_substates = int(cycle.get("num_substates", 0))
                step_count = int(cycle.get("step_count", 0))
                has_heating = 1 if cycle.get("has_heating_pattern", False) else 0
                has_motor = 1 if cycle.get("has_motor_pattern", False) else 0
                profile_points = self._normalize_profile_points(cycle.get("profile_points", []))
                delta_profile_points = self._normalize_profile_points(cycle.get("delta_profile_points", []))
                profile_points_json = json.dumps(profile_points)
                shape_vector_json = json.dumps(self._resample_profile_points(profile_points, sample_count=32))
                delta_profile_points_json = json.dumps(delta_profile_points)
                delta_shape_vector_json = json.dumps(cycle.get("delta_shape_vector", []))
                prototype_hash = self._prototype_hash_from_cycle(cycle)
                curve_hash = str(cycle.get("curve_hash") or self._curve_hash_from_cycle(cycle))
                shape_signature = str(cycle.get("shape_signature") or self._shape_signature_from_cycle(cycle))
                baseline_before_w_avg = float(cycle.get("baseline_before_w", 0.0) or 0.0)
                baseline_after_w_avg = float(cycle.get("baseline_after_w", 0.0) or 0.0)
                delta_avg_power_w = float(cycle.get("delta_avg_power_w", 0.0) or 0.0)
                delta_peak_power_w = float(cycle.get("delta_peak_power_w", 0.0) or 0.0)
                delta_energy_wh = float(cycle.get("delta_energy_wh", 0.0) or 0.0)
                plateau_count = int(cycle.get("plateau_count", 0) or 0)
                avg_delta_power_w = delta_avg_power_w
                avg_duration_s = float(cycle.get("duration_s", 0.0) or 0.0)
                avg_peak_power_w = float(cycle.get("peak_power_w", 0.0) or 0.0)
                avg_inrush_duration_s = float(cycle.get("settling_time_s", 0.0) or 0.0)
                occurrence_count = 1
                mode_key = str(cycle.get("mode_key") or self._mode_key_from_cycle(cycle))
                
                # Multi-mode learning
                initial_mode = self._build_mode_signature(cycle, str(cycle.get("end_ts", now)))
                seed_modes = self._parse_operating_modes(cycle.get("operating_modes", []))
                merged_seed_modes = self._merge_operating_modes(seed_modes, initial_mode)
                operating_modes_json = json.dumps(merged_seed_modes)
                has_multiple_modes = 1 if len(merged_seed_modes) >= 2 else 0
                
                # Temporal pattern tracking - initialize for new pattern
                try:
                    cycle_end_dt = datetime.fromisoformat(cycle["end_ts"])
                    initial_hour_of_day = cycle_end_dt.hour + cycle_end_dt.minute / 60.0
                    initial_hour_bucket = str(cycle_end_dt.hour)
                    initial_hour_dist_json = json.dumps({initial_hour_bucket: 1})
                except (ValueError, TypeError):
                    initial_hour_of_day = 12.0
                    initial_hour_dist_json = "{}"

                confidence_score_norm = max(0.0, min(1.0, quality_score))
                frequency_per_day_seed = self._frequency_per_day(
                    seen_count=1,
                    first_seen_iso=str(cycle.get("start_ts") or now),
                    last_seen_iso=str(cycle.get("end_ts") or now),
                )
                candidate_name = self._normalize_pattern_name(suggestion_seed)
                device_group_id = str(cycle.get("device_group_id") or self._device_group_id(suggestion_seed, cycle))
                device_id = self._get_or_create_device(
                    label=suggestion_seed,
                    phase=str(cycle.get("phase", "L1")),
                    confidence=confidence_score_norm,
                    confirmed=False,
                )
                device_subclass = self._derive_device_subclass(suggestion_seed, cycle)
                
                cur = self._patterns_conn.execute(
                    """
                    INSERT INTO learned_patterns (
                        created_at, updated_at, first_seen, last_seen, seen_count,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        suggestion_type, user_label, status,
                        avg_active_phases, phase_mode, phase,
                        power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                        duty_cycle, peak_to_avg_ratio, num_substates, step_count,
                        has_heating_pattern, has_motor_pattern,
                        profile_points_json,
                        baseline_before_w_avg, baseline_after_w_avg,
                        delta_avg_power_w, delta_peak_power_w, delta_energy_wh,
                        delta_profile_points_json, delta_shape_vector_json, plateau_count,
                        curve_hash, shape_signature,
                        avg_delta_power_w, avg_duration_s, avg_peak_power_w, avg_inrush_duration_s,
                        occurrence_count, device_group_id, mode_key,
                        quality_score_avg,
                        device_id, confidence_score, frequency_per_day,
                        candidate_name, is_confirmed, shape_vector_json, prototype_hash,
                        operating_modes, has_multiple_modes,
                        typical_interval_s, avg_hour_of_day, last_intervals_json, hour_distribution_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        now,
                        cycle["start_ts"],
                        cycle["end_ts"],
                        1,
                        float(cycle["avg_power_w"]),
                        float(cycle["peak_power_w"]),
                        float(cycle["duration_s"]),
                        float(cycle["energy_wh"]),
                        suggestion_seed,
                        None,
                        "active",
                        float(cycle.get("active_phase_count", 1.0)),
                        str(cycle.get("phase_mode", "unknown")),
                        str(cycle.get("phase", "L1")),  # Explicit phase
                        power_variance,
                        rise_rate,
                        fall_rate,
                        duty_cycle,
                        peak_to_avg,
                        num_substates,
                        step_count,
                        has_heating,
                        has_motor,
                        profile_points_json,
                        baseline_before_w_avg,
                        baseline_after_w_avg,
                        delta_avg_power_w,
                        delta_peak_power_w,
                        delta_energy_wh,
                        delta_profile_points_json,
                        delta_shape_vector_json,
                        plateau_count,
                        curve_hash,
                        shape_signature,
                        avg_delta_power_w,
                        avg_duration_s,
                        avg_peak_power_w,
                        avg_inrush_duration_s,
                        occurrence_count,
                        device_group_id,
                        mode_key,
                        quality_score,
                        int(device_id) if device_id else None,
                        confidence_score_norm,
                        frequency_per_day_seed,
                        candidate_name,
                        0,
                        shape_vector_json,
                        prototype_hash,
                        operating_modes_json,
                        has_multiple_modes,
                        0.0,  # typical_interval_s - no interval yet for new pattern
                        initial_hour_of_day,  # avg_hour_of_day
                        "[]",  # last_intervals_json - empty for new pattern
                        initial_hour_dist_json,  # hour_distribution_json
                    ),
                )
                row_id = cur.lastrowid if cur.lastrowid is not None else 0
                new_id = int(row_id)
                if device_id:
                    self._patterns_conn.execute(
                        """
                        UPDATE devices
                        SET device_subclass = ?, baseline_range_min_w = ?, baseline_range_max_w = ?, updated_at = ?
                        WHERE device_id = ?
                        """,
                        (
                            device_subclass,
                            baseline_before_w_avg,
                            baseline_after_w_avg,
                            now,
                            int(device_id),
                        ),
                    )

            created = {
                "id": new_id,
                "created_at": now,
                "updated_at": now,
                "first_seen": cycle["start_ts"],
                "last_seen": cycle["end_ts"],
                "seen_count": 1,
                "avg_power_w": float(cycle["avg_power_w"]),
                "peak_power_w": float(cycle["peak_power_w"]),
                "duration_s": float(cycle["duration_s"]),
                "energy_wh": float(cycle["energy_wh"]),
                "suggestion_type": suggestion_seed,
                "user_label": None,
                "status": "active",
                "avg_active_phases": float(cycle.get("active_phase_count", 1.0)),
                "phase_mode": str(cycle.get("phase_mode", "unknown")),
                "phase": str(cycle.get("phase", "L1")),
                "power_variance": float(cycle.get("power_variance", 0.0)),
                "rise_rate_w_per_s": float(cycle.get("rise_rate_w_per_s", 0.0)),
                "fall_rate_w_per_s": float(cycle.get("fall_rate_w_per_s", 0.0)),
                "duty_cycle": float(cycle.get("duty_cycle", 0.0)),
                "peak_to_avg_ratio": float(cycle.get("peak_to_avg_ratio", 1.0)),
                "num_substates": int(cycle.get("num_substates", 0)),
                "step_count": int(cycle.get("step_count", 0)),
                "has_heating_pattern": 1 if cycle.get("has_heating_pattern", False) else 0,
                "has_motor_pattern": 1 if cycle.get("has_motor_pattern", False) else 0,
                "profile_points": self._normalize_profile_points(cycle.get("profile_points", [])),
                "baseline_before_w_avg": baseline_before_w_avg,
                "baseline_after_w_avg": baseline_after_w_avg,
                "delta_avg_power_w": delta_avg_power_w,
                "delta_peak_power_w": delta_peak_power_w,
                "delta_energy_wh": delta_energy_wh,
                "delta_profile_points": delta_profile_points,
                "delta_shape_vector_json": delta_shape_vector_json,
                "plateau_count": plateau_count,
                "curve_hash": curve_hash,
                "shape_signature": shape_signature,
                "avg_delta_power_w": avg_delta_power_w,
                "avg_duration_s": avg_duration_s,
                "avg_peak_power_w": avg_peak_power_w,
                "avg_inrush_duration_s": avg_inrush_duration_s,
                "occurrence_count": occurrence_count,
                "device_group_id": device_group_id,
                "mode_key": mode_key,
                "quality_score_avg": quality_score,
                "device_id": int(device_id) if device_id else 0,
                "confidence_score_db": confidence_score_norm,
                "frequency_per_day_db": frequency_per_day_seed,
                "candidate_name": candidate_name,
                "is_confirmed": False,
                "shape_vector_json": shape_vector_json,
                "prototype_hash": prototype_hash,
            }
            logger.info(
                "Pattern classify/create: id=%s label=%s rule=%s features[var=%.2f substates=%s steps=%s rise=%.2f fall=%.2f]",
                new_id,
                suggestion_seed,
                "initial_cycle_label",
                power_variance,
                num_substates,
                step_count,
                rise_rate,
                fall_rate,
            )
            self._record_pattern_features(new_id, cycle)
            self._record_pattern_history_snapshot(created)
            self._upsert_patterns_mirror(created)
            event_id = self._record_cycle_event(
                cycle=cycle,
                assigned_pattern_id=new_id,
                assigned_device_id=int(device_id) if device_id else None,
                final_label=suggestion_seed,
                final_confidence=float(self._last_hybrid_decision.get("confidence", 0.0) or 0.0),
                dedup_result="create_new",
                matched_pattern_id=int(best.get("id", 0) or 0) if best else None,
                similarity_score=best_similarity if best else 0.0,
                dedup_reason=dedup_reason,
            )
            self.log_training_decision(
                event_id=event_id,
                accepted=True,
                reason="dedup_create_new",
                label=suggestion_seed,
                dedup_result="create_new",
                matched_pattern_id=int(best.get("id", 0) or 0) if best else None,
                similarity_score=best_similarity if best else 0.0,
                dedup_reason=dedup_reason,
            )
            self._record_classification_log(
                event_id=event_id,
                pattern_id=new_id,
                device_id=int(device_id) if device_id else None,
                final_label=suggestion_seed,
                final_confidence=float(self._last_hybrid_decision.get("confidence", 0.0) or 0.0),
                decision_source=str(self._last_hybrid_decision.get("source", "pattern_create")),
            )
            return {
                "matched": False,
                "distance": None,
                "similarity": best_similarity if best else 0.0,
                "dedup": {
                    "result": "create_new",
                    "matched_pattern_id": int(best.get("id", 0) or 0) if best else None,
                    "similarity_score": best_similarity if best else 0.0,
                    "reason": dedup_reason,
                },
                "pattern": created,
            }
        except Exception as e:
            logger.error(f"Failed to learn cycle pattern: {e}", exc_info=True)
            return {"matched": False, "pattern": None}

    def label_pattern(self, pattern_id: int, user_label: str) -> bool:
        if not self._patterns_conn:
            return False
        try:
            clean_label = str(user_label).strip()
            if not clean_label:
                return False
            old_row = self._patterns_conn.execute(
                "SELECT user_label, suggestion_type, phase FROM learned_patterns WHERE id = ?",
                (int(pattern_id),),
            ).fetchone()
            old_label = ""
            phase = "L1"
            if old_row:
                old_label = str(old_row[0] or old_row[1] or "")
                phase = str(old_row[2] or "L1")
            device_id = self._get_or_create_device(
                label=clean_label,
                phase=phase,
                confidence=1.0,
                confirmed=True,
            )
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    UPDATE learned_patterns
                    SET user_label = ?,
                        candidate_name = ?,
                        is_confirmed = 1,
                        device_id = COALESCE(?, device_id),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_label,
                        self._normalize_pattern_name(clean_label),
                        int(device_id) if device_id else None,
                        datetime.now().isoformat(),
                        int(pattern_id),
                    ),
                )
            self._record_user_label_change(
                pattern_id=int(pattern_id),
                device_id=int(device_id) if device_id else None,
                old_label=old_label,
                new_label=clean_label,
                comment="label_pattern API",
            )
            updated = self._patterns_conn.execute(
                "SELECT * FROM learned_patterns WHERE id = ?",
                (int(pattern_id),),
            ).fetchone()
            if updated:
                patterns = self.list_patterns(limit=2000)
                for p in patterns:
                    if int(p.get("id", 0) or 0) == int(pattern_id):
                        self._upsert_patterns_mirror(p)
                        break
            return True
        except Exception as e:
            logger.error(f"Failed to label pattern {pattern_id}: {e}", exc_info=True)
            return False

    def get_label_phase_locks(self) -> Dict[str, str]:
        """Return explicit label->phase locks (normalized label keys)."""
        if not self._patterns_conn or not self._table_exists(self._patterns_conn, "label_phase_locks"):
            return {}
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT label_key, phase
                FROM label_phase_locks
                """
            ).fetchall()
            out: Dict[str, str] = {}
            for row in rows:
                key = self._normalize_pattern_name(row[0] or "")
                phase = str(row[1] or "").upper()
                if not key:
                    continue
                if phase in {"L1", "L2", "L3"}:
                    out[key] = phase
            return out
        except Exception as e:
            logger.warning("Failed to list label phase locks: %s", e)
            return {}

    def set_label_phase_lock(self, label: str, phase: str, source: str = "manual") -> bool:
        """Persist an explicit phase lock for a label and align existing patterns/devices."""
        if not self._patterns_conn:
            return False
        label_key = self._normalize_pattern_name(label)
        target_phase = str(phase or "").upper()
        if not label_key or target_phase not in {"L1", "L2", "L3"}:
            return False

        try:
            now = datetime.now().isoformat()
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO label_phase_locks (label_key, phase, updated_at, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(label_key) DO UPDATE SET
                        phase = excluded.phase,
                        updated_at = excluded.updated_at,
                        source = excluded.source
                    """,
                    (label_key, target_phase, now, str(source or "manual")),
                )

                self._patterns_conn.execute(
                    """
                    UPDATE learned_patterns
                    SET phase = ?, updated_at = ?
                    WHERE LOWER(REPLACE(COALESCE(user_label, suggestion_type, ''), ' ', '_')) = ?
                       OR LOWER(REPLACE(COALESCE(candidate_name, ''), ' ', '_')) = ?
                    """,
                    (target_phase, now, label_key, label_key),
                )

                if self._table_exists(self._patterns_conn, "devices"):
                    self._patterns_conn.execute(
                        """
                        UPDATE devices
                        SET phase = ?, updated_at = ?, confirmed = 1
                        WHERE LOWER(REPLACE(COALESCE(final_label, ''), ' ', '_')) = ?
                           OR LOWER(REPLACE(COALESCE(user_label, ''), ' ', '_')) = ?
                           OR LOWER(REPLACE(COALESCE(predicted_label, ''), ' ', '_')) = ?
                        """,
                        (target_phase, now, label_key, label_key, label_key),
                    )

            return True
        except Exception as e:
            logger.error("Failed to set phase lock for label %s: %s", label, e, exc_info=True)
            return False

    def set_pattern_phase_lock(self, pattern_id: int, phase: str) -> bool:
        """Set label phase lock using the label resolved from a pattern ID."""
        if not self._patterns_conn:
            return False
        try:
            row = self._patterns_conn.execute(
                """
                SELECT user_label, candidate_name, suggestion_type
                FROM learned_patterns
                WHERE id = ?
                """,
                (int(pattern_id),),
            ).fetchone()
            if not row:
                return False

            label = str(row[0] or row[1] or row[2] or "").strip()
            if not label:
                return False
            return self.set_label_phase_lock(label=label, phase=phase, source=f"pattern:{int(pattern_id)}")
        except Exception as e:
            logger.error("Failed to set pattern phase lock for pattern %s: %s", pattern_id, e, exc_info=True)
            return False

    def delete_pattern(self, pattern_id: int) -> bool:
        """Delete a single learned pattern by ID."""
        if not self._patterns_conn:
            return False
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    "DELETE FROM learned_patterns WHERE id = ?",
                    (int(pattern_id),)
                )
            logger.info(f"Deleted pattern {pattern_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete pattern {pattern_id}: {e}", exc_info=True)
            return False

    def log_training_decision(
        self,
        event_id=None,
        accepted: bool = False,
        reason: Optional[str] = None,
        label: Optional[str] = None,
        dedup_result: Optional[str] = None,
        matched_pattern_id: Optional[int] = None,
        similarity_score: Optional[float] = None,
        dedup_reason: Optional[str] = None,
        prototype_score: Optional[float] = None,
        shape_score: Optional[float] = None,
        ml_score: Optional[float] = None,
        final_score: Optional[float] = None,
        decision_reason: Optional[str] = None,
        agreement_flag: Optional[int] = None,
    ) -> None:
        """Record a training-filter accept/reject decision in the training_log table."""
        if not self._patterns_conn:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            explain = dict(self._last_hybrid_decision.get("explain") or {})
            fusion = dict(explain.get("fusion") or {})
            score_prototype = float(prototype_score) if prototype_score is not None else float(explain.get("prototype_confidence", 0.0) or 0.0)
            score_shape = float(shape_score) if shape_score is not None else float(explain.get("shape_confidence", 0.0) or 0.0)
            score_ml = float(ml_score) if ml_score is not None else float((dict(explain.get("ml") or {}).get("confidence", 0.0)) or 0.0)
            score_final = float(final_score) if final_score is not None else float(fusion.get("final_score", self._last_hybrid_decision.get("confidence", 0.0)) or 0.0)
            decision = str(decision_reason) if decision_reason else str(explain.get("decision_reason") or "")
            agreed = int(agreement_flag) if agreement_flag is not None else (1 if decision == "boosting_and_shape_agree" else 0)
            with self._patterns_conn:
                self._patterns_conn.execute(
                    """
                    INSERT INTO training_log (
                        created_at, event_id, accepted, rejected, reason, label,
                        dedup_result, matched_pattern_id, similarity_score, dedup_reason,
                        prototype_score, shape_score, ml_score, final_score, decision_reason, agreement_flag
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        int(event_id) if event_id is not None else None,
                        1 if accepted else 0,
                        0 if accepted else 1,
                        str(reason) if reason else None,
                        str(label) if label else None,
                        str(dedup_result) if dedup_result else None,
                        int(matched_pattern_id) if matched_pattern_id else None,
                        float(similarity_score) if similarity_score is not None else None,
                        str(dedup_reason) if dedup_reason else None,
                        score_prototype,
                        score_shape,
                        score_ml,
                        score_final,
                        decision,
                        agreed,
                    ),
                )
        except Exception as e:
            logger.warning("log_training_decision failed: %s", e)

    def get_training_log(self, limit: int = 200) -> list:
        """Return recent training-filter decisions, newest first."""
        if not self._patterns_conn:
            return []
        try:
            rows = self._patterns_conn.execute(
                """
                SELECT id, created_at, event_id, accepted, rejected, reason, label,
                      dedup_result, matched_pattern_id, similarity_score, dedup_reason,
                      prototype_score, shape_score, ml_score, final_score, decision_reason, agreement_flag
                FROM training_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [
                {
                    "id": row[0],
                    "created_at": row[1],
                    "event_id": row[2],
                    "accepted": bool(row[3]),
                    "rejected": bool(row[4]),
                    "reason": row[5],
                    "label": row[6],
                    "dedup_result": row[7],
                    "matched_pattern_id": row[8],
                    "similarity_score": float(row[9] or 0.0),
                    "dedup_reason": row[10],
                    "prototype_score": float(row[11] or 0.0),
                    "shape_score": float(row[12] or 0.0),
                    "ml_score": float(row[13] or 0.0),
                    "final_score": float(row[14] or 0.0),
                    "decision_reason": row[15],
                    "agreement_flag": int(row[16] or 0),
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("get_training_log failed: %s", e)
            return []

    def clear_readings_only(self) -> dict:
        """Clear only live power readings and detections, keep learned patterns."""
        if not self._conn:
            return {"ok": False, "error": "storage not connected"}
        try:
            with self._conn:
                self._conn.execute("DELETE FROM power_readings")
                self._conn.execute("DELETE FROM detections")
            logger.info("Cleared live readings and detections (patterns preserved)")
            return {"ok": True, "cleared": "readings"}
        except Exception as e:
            logger.error(f"Failed to clear readings: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    def clear_patterns_only(self) -> Dict:
        """Clear only learned patterns, keep live readings."""
        if not self._patterns_conn:
            return {"ok": False, "error": "patterns storage not connected"}
        try:
            with self._patterns_conn:
                self._patterns_conn.execute("DELETE FROM learned_patterns")
            logger.info("Cleared learned patterns (live readings preserved)")
            return {"ok": True, "cleared": "patterns"}
        except Exception as e:
            logger.error(f"Failed to clear patterns: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    def create_pattern_from_range(self, start_time: str, end_time: str, user_label: str) -> Dict:
        """Create a learned pattern from a manually selected time range in the UI."""
        if not self._conn or not self._patterns_conn:
            return {"ok": False, "error": "database not connected"}
        
        try:
            # Import hier um zirkuläre Abhängigkeiten zu vermeiden
            from app.learning.features import CycleFeatures
            from app.models import PowerReading
            
            # Hole Messwerte im Zeitbereich
            rows = self._conn.execute(
                """
                SELECT ts, power_w, phase, metadata
                FROM power_readings
                WHERE ts >= ? AND ts <= ?
                ORDER BY ts ASC
                """,
                (start_time, end_time)
            ).fetchall()
            
            if not rows or len(rows) < 3:
                return {"ok": False, "error": "not enough data points in selected range"}
            
            # Konvertiere zu PowerReading Objekten für Feature-Extraction
            power_readings = []
            phase_energy_from_metadata: Dict[str, float] = {}
            for row in rows:
                try:
                    ts = datetime.fromisoformat(row[0])
                    # Normalize to naive UTC for consistent arithmetic.
                    if ts.tzinfo is not None:
                        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                    power_w = float(row[1])
                    phase_raw = str(row[2] if len(row) > 2 else "").upper()
                    metadata_raw = row[3] if len(row) > 3 else None

                    metadata = {}
                    if isinstance(metadata_raw, str) and metadata_raw.strip():
                        try:
                            metadata = json.loads(metadata_raw)
                        except Exception:
                            metadata = {}

                    point_phase = phase_raw if phase_raw in {"L1", "L2", "L3"} else ""
                    phase_powers = metadata.get("phase_powers_w", {}) if isinstance(metadata, dict) else {}
                    if isinstance(phase_powers, dict):
                        local_candidates: List[Tuple[str, float]] = []
                        for phase_name, phase_power in phase_powers.items():
                            phase_clean = str(phase_name).upper()
                            if phase_clean not in {"L1", "L2", "L3"}:
                                continue
                            try:
                                phase_value = float(phase_power)
                            except (TypeError, ValueError):
                                continue
                            phase_energy_from_metadata[phase_clean] = phase_energy_from_metadata.get(phase_clean, 0.0) + max(phase_value, 0.0)
                            local_candidates.append((phase_clean, phase_value))

                        # For TOTAL rows prefer dominant phase from embedded phase powers.
                        if not point_phase and local_candidates:
                            point_phase = max(local_candidates, key=lambda item: item[1])[0]

                    if not point_phase:
                        point_phase = "L1"

                    power_readings.append(PowerReading(timestamp=ts, power_w=power_w, phase=point_phase, metadata=metadata))
                except Exception:
                    continue
            
            if len(power_readings) < 3:
                return {"ok": False, "error": "failed to parse power readings"}
            
            # Berechne Basis-Statistiken
            powers = [float(r.power_w) for r in power_readings]
            avg_power = sum(powers) / len(powers)
            peak_power = max(powers)
            
            # Berechne Dauer
            start_dt = power_readings[0].timestamp
            end_dt = power_readings[-1].timestamp
            duration_s = (end_dt - start_dt).total_seconds()
            if duration_s <= 0:
                duration_s = len(power_readings) * 5.0
            
            # Energie berechnen
            energy_ws = 0.0
            for idx in range(1, len(power_readings)):
                prev = power_readings[idx - 1]
                curr = power_readings[idx]
                dt = max((curr.timestamp - prev.timestamp).total_seconds(), 0.0)
                energy_ws += (float(prev.power_w) + float(curr.power_w)) * 0.5 * dt
            energy_wh = energy_ws / 3600.0
            
            # Extrahiere erweiterte Features
            features = CycleFeatures.extract(power_readings)
            
            # Erkennung Phasen-Modus
            phases_set = set(r.phase for r in power_readings if r.phase)
            phase_mode = "multi_phase" if len(phases_set) > 1 else "single_phase"
            phase_energy: Dict[str, float] = {}
            for reading in power_readings:
                phase_name = str(reading.phase or "L1")
                phase_energy[phase_name] = phase_energy.get(phase_name, 0.0) + float(reading.power_w)
            # Prefer dominant phase derived from per-phase metadata when available.
            if phase_energy_from_metadata:
                dominant_phase = max(phase_energy_from_metadata.items(), key=lambda item: item[1])[0]
                phase_mode = "single_phase"
            else:
                dominant_phase = max(phase_energy.items(), key=lambda item: item[1])[0] if phase_energy else "L1"
            
            # Werte für DB vorbereiten
            power_variance = features.power_variance if features else 0.0
            rise_rate = features.rise_rate_w_per_s if features else 0.0
            fall_rate = features.fall_rate_w_per_s if features else 0.0
            duty_cycle_val = features.duty_cycle if features else 0.0
            peak_to_avg = features.peak_to_avg_ratio if features else 1.0
            num_substates = features.num_substates if features else 0
            step_count_val = features.step_count if features else 0
            has_heating = 1 if (features and features.has_heating_pattern) else 0
            has_motor = 1 if (features and features.has_motor_pattern) else 0
            total_s = max(duration_s, 1.0)
            raw_profile_points = []
            for reading in power_readings:
                t_rel = max((reading.timestamp - start_dt).total_seconds(), 0.0)
                raw_profile_points.append(
                    {
                        "t_s": t_rel,
                        "power_w": float(reading.power_w),
                        "t_norm": t_rel / total_s,
                    }
                )
            profile_points = self._normalize_profile_points(raw_profile_points)
            profile_points_json = json.dumps(profile_points)
            
            # Erstelle neues Muster mit erweiterten Features
            now = datetime.now().isoformat()
            pattern_id = None
            with self._patterns_conn:
                cursor = self._patterns_conn.execute(
                    """
                    INSERT INTO learned_patterns (
                        avg_power_w, peak_power_w, duration_s, energy_wh, phase_mode, phase,
                        user_label, seen_count, suggestion_type, status,
                        first_seen, last_seen, created_at, updated_at,
                        power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                        duty_cycle, peak_to_avg_ratio, num_substates, step_count,
                        has_heating_pattern, has_motor_pattern,
                        profile_points_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        avg_power, peak_power, duration_s, energy_wh, phase_mode, dominant_phase,
                        user_label.strip(), 1, "user_defined", "active",
                        start_time, end_time, now, now,
                        power_variance, rise_rate, fall_rate,
                        duty_cycle_val, peak_to_avg, num_substates, step_count_val,
                        has_heating, has_motor,
                        profile_points_json,
                    )
                )
                pattern_id = cursor.lastrowid
            logger.info(
                f"Created pattern {pattern_id} from range: {len(power_readings)} points, "
                f"avg={avg_power:.1f}W, peak={peak_power:.1f}W, duration={duration_s:.1f}s, "
                f"label={user_label}, substates={num_substates}, steps={step_count_val}, "
                f"heating={bool(has_heating)}, motor={bool(has_motor)}"
            )
            
            return {
                "ok": True,
                "pattern_id": pattern_id,
                "data_points": len(power_readings),
                "avg_power_w": avg_power,
                "peak_power_w": peak_power,
                "duration_s": duration_s,
                "num_substates": num_substates,
                "step_count": step_count_val,
            }
        except Exception as e:
            logger.error(f"Failed to create pattern from range: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}
