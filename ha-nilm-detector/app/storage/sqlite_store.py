"""SQLite storage for power readings and detection events."""

import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from app.models import DetectionResult, PowerReading
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SQLiteStore:
    """Persists readings/detections for diagnostics and future learning."""

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
            self._maybe_recover_patterns_from_legacy_files()
            self.cleanup_old_data()
            logger.info(
                "SQLite storage initialized: "
                f"live={self.db_path}, patterns={self.patterns_db_path}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SQLite storage: {e}", exc_info=True)
            return False

    def _maybe_migrate_patterns_from_live(self) -> None:
        """Migrate existing patterns from live DB into dedicated patterns DB once."""
        if not self._conn or not self._patterns_conn:
            return
        if self._patterns_conn is self._conn:
            return

        try:
            dst_count = int((self._patterns_conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone() or [0])[0])
            if dst_count > 0:
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
            logger.info(f"Migrated {len(src_rows)} pattern(s) into dedicated patterns DB")
        except Exception as e:
            logger.warning(f"Pattern migration to dedicated DB skipped: {e}")

    def _maybe_recover_patterns_from_legacy_files(self) -> None:
        """Recover patterns from legacy addon paths if current patterns DB is empty."""
        if not self._patterns_conn:
            return

        try:
            dst_count = int((self._patterns_conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone() or [0])[0])
            if dst_count > 0:
                return
        except Exception:
            return

        legacy_candidates = [
            "/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3",
            "/addon_configs/ha_nilm_detector/nilm_live.sqlite3",
            "/data/nilm_patterns.sqlite3",
            "/data/nilm_live.sqlite3",
        ]

        for legacy_path in legacy_candidates:
            try:
                legacy_abs = os.path.abspath(str(legacy_path))
                if legacy_abs == os.path.abspath(self.patterns_db_path):
                    continue
                if not os.path.exists(legacy_abs):
                    continue

                legacy_conn = sqlite3.connect(legacy_abs, timeout=5)
                try:
                    tables = legacy_conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='learned_patterns'"
                    ).fetchall()
                    if not tables:
                        continue

                    src_count = int((legacy_conn.execute("SELECT COUNT(*) FROM learned_patterns").fetchone() or [0])[0])
                    if src_count <= 0:
                        continue

                    rows = legacy_conn.execute(
                        """
                        SELECT created_at, updated_at, first_seen, last_seen, seen_count,
                               avg_power_w, peak_power_w, duration_s, energy_wh,
                               suggestion_type, user_label, status
                        FROM learned_patterns
                        """
                    ).fetchall()
                    if not rows:
                        continue

                    with self._patterns_conn:
                        self._patterns_conn.executemany(
                            """
                            INSERT INTO learned_patterns (
                                created_at, updated_at, first_seen, last_seen, seen_count,
                                avg_power_w, peak_power_w, duration_s, energy_wh,
                                suggestion_type, user_label, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            rows,
                        )

                    logger.warning(
                        "Recovered %s learned pattern(s) from legacy DB: %s",
                        len(rows),
                        legacy_abs,
                    )
                    return
                finally:
                    legacy_conn.close()
            except Exception as legacy_error:
                logger.warning("Legacy pattern recovery skipped for %s: %s", legacy_path, legacy_error)

    def close(self) -> None:
        # Flush any pending batches before closing connections
        self._flush_reading_batch()
        self._flush_detection_batch()
        
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
                # Flush WAL changes into main DB before shutdown.
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                logger.warning(f"SQLite checkpoint during close failed: {e}")
            finally:
                self._conn.close()
                self._conn = None

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

        if not self._patterns_conn:
            return

        with self._patterns_conn:
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
        existing_points = SQLiteStore._normalize_profile_points(existing.get("profile_points", []))
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

        return max(0.0, min(1.0, score))

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

        # Slightly relaxed threshold helps variable-load devices cluster better.
        if best_idx >= 0 and best_dist <= 0.30:
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
    def _device_group_key(item: Dict) -> str:
        """Build a stable group key so multiple patterns can belong to one device group."""
        raw = str(item.get("user_label") or item.get("suggestion_type") or "").strip()
        key = SQLiteStore._normalize_pattern_name(raw)
        return key or "unbekannt"

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
        """AI-like nearest-prototype vote based on learned patterns.

        This is not a heavy ML model, but a lightweight weighted similarity model
        using learned signatures as prototypes.
        """
        if not self._patterns_conn:
            return {"label": fallback, "confidence": 0.0, "source": "fallback"}

        patterns = self.list_patterns(limit=500)
        if not patterns:
            return {"label": fallback, "confidence": 0.0, "source": "fallback"}

        score_by_group: Dict[str, float] = {}
        group_display_label: Dict[str, str] = {}
        total_score = 0.0
        cycle_phase_mode = str(cycle.get("phase_mode") or "unknown")
        cycle_phase = str(cycle.get("phase") or "L1")
        best_distance_overall: float | None = None
        cycle_hour: float | None = None

        def rel(a: float, b: float) -> float:
            base = max(abs(a), abs(b), 1.0)
            return abs(a - b) / base

        try:
            cycle_end_dt = datetime.fromisoformat(str(cycle.get("end_ts") or ""))
            cycle_hour = float(cycle_end_dt.hour) + (float(cycle_end_dt.minute) / 60.0)
        except (TypeError, ValueError):
            cycle_hour = None

        for item in patterns:
            if item.get("status") != "active":
                continue

            item_phase_mode = str(item.get("phase_mode") or "unknown")
            item_phase = str(item.get("phase") or "L1")
            if cycle_phase_mode == "single_phase" and item_phase_mode == "single_phase" and item_phase != cycle_phase:
                continue

            label_raw = str(item.get("user_label") or item.get("suggestion_type") or "").strip()
            if not label_raw:
                continue
            group_key = self._device_group_key(item)
            if group_key not in group_display_label or str(item.get("user_label") or "").strip():
                # Prefer explicit user label for display, fallback to normalized key.
                display = str(item.get("user_label") or "").strip() or group_key
                group_display_label[group_key] = display

            distance = self._pattern_distance(item, cycle)
            if best_distance_overall is None or distance < best_distance_overall:
                best_distance_overall = distance
            similarity = math.exp(-4.0 * max(distance, 0.0))
            seen_weight = 1.0 + math.log1p(max(int(item.get("seen_count", 1)), 1))

            quality_weight = 0.6 + (max(0.0, min(1.0, float(item.get("quality_score_avg", 0.5)))) * 0.8)

            # Runtime consistency: prefer labels with similar typical cycle length.
            runtime_weight = 1.0
            try:
                runtime_dist = rel(float(item.get("duration_s", 0.0)), float(cycle.get("duration_s", 0.0)))
                runtime_weight = max(0.75, 1.0 - min(runtime_dist, 1.0) * 0.25)
            except (TypeError, ValueError):
                runtime_weight = 1.0

            # Spike consistency: compare peak-vs-average behavior.
            spike_weight = 1.0
            try:
                item_ratio = float(item.get("peak_to_avg_ratio", 1.0))
                cycle_ratio = float(cycle.get("peak_to_avg_ratio", 1.0))
                spike_dist = rel(item_ratio, cycle_ratio)
                spike_weight = max(0.75, 1.0 - min(spike_dist, 1.0) * 0.25)
            except (TypeError, ValueError):
                spike_weight = 1.0

            temporal_weight = 1.0
            if cycle_hour is not None:
                try:
                    expected_hour = float(item.get("avg_hour_of_day", 12.0))
                    hour_diff = abs(cycle_hour - expected_hour)
                    hour_diff = min(hour_diff, 24.0 - hour_diff)  # wrap-around distance on 24h clock
                    temporal_weight = max(0.75, 1.0 - ((hour_diff / 12.0) * 0.25))
                except (TypeError, ValueError):
                    temporal_weight = 1.0

            vote = similarity * seen_weight * quality_weight * temporal_weight * runtime_weight * spike_weight
            if vote <= 0.0:
                continue

            score_by_group[group_key] = score_by_group.get(group_key, 0.0) + vote
            total_score += vote

        if not score_by_group or total_score <= 0.0:
            return {"label": fallback, "confidence": 0.0, "source": "fallback"}

        best_group, best_score = max(score_by_group.items(), key=lambda pair: pair[1])
        best_label = group_display_label.get(best_group, best_group)
        confidence = float(best_score / total_score)

        # Guard against label collapse: if the nearest prototype is still too far,
        # trust the heuristic fallback even if relative vote confidence is high.
        if best_distance_overall is None or best_distance_overall > 0.38:
            return {
                "label": fallback,
                "confidence": confidence,
                "source": "fallback_distance_gate",
            }

        # Keep fallback if confidence is too low.
        if confidence < 0.45:
            return {"label": fallback, "confidence": confidence, "source": "fallback_low_confidence"}

        return {"label": best_label, "confidence": confidence, "source": "prototype_similarity"}

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

                    first_seen = min(str(a.get("first_seen") or now), str(b.get("first_seen") or now))
                    last_seen = max(str(a.get("last_seen") or now), str(b.get("last_seen") or now))

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

    def list_patterns(self, limit: int = 100) -> List[Dict]:
        if not self._patterns_conn:
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
                        COALESCE(num_substates, 0), COALESCE(has_heating_pattern, 0), COALESCE(has_motor_pattern, 0),
                                                COALESCE(profile_points_json, '[]'), COALESCE(quality_score_avg, 0.5)
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
                    profile_points = self._normalize_profile_points(json.loads(str(row[30] or "[]")))
                except Exception:
                    profile_points = []
                quality_score_avg = max(0.0, min(1.0, float(row[31] or 0.5)))
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
                        "has_heating_pattern": int(row[28] or 0),
                        "has_motor_pattern": int(row[29] or 0),
                        "profile_points": profile_points,
                        "quality_score_avg": quality_score_avg,
                        "confidence_score": round(confidence_score, 1),
                        "candidate_name": self._normalize_pattern_name(row[11] or row[10]),
                        "is_confirmed": bool(str(row[11] or "").strip()),
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

        quality_score = self._learning_quality_score(cycle)
        if quality_score < 0.28:
            return {
                "matched": False,
                "pattern": None,
                "skipped": True,
                "reason": "low_quality_cycle",
                "quality_score": quality_score,
            }

        now = datetime.now().isoformat()
        patterns = self.list_patterns(limit=500)

        # Get phase from cycle (default to L1 if not specified)
        cycle_phase = str(cycle.get("phase", "L1"))

        best = None
        best_distance = 999.0
        for item in patterns:
            if item.get("status") != "active":
                continue
            # Only match patterns on the same phase
            if item.get("phase", "L1") != cycle_phase:
                continue
            distance = self._pattern_distance(item, cycle)
            if distance < best_distance:
                best_distance = distance
                best = item

        try:
            best_tolerance = tolerance
            if best:
                seen = max(int(best.get("seen_count", 1)), 1)
                best_tolerance = max(0.22, tolerance - min((seen - 1) * 0.005, 0.14))

            if best and best_distance <= best_tolerance:
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
                has_heating = 1 if (bool(best.get("has_heating_pattern", 0)) or bool(cycle.get("has_heating_pattern", False))) else 0
                has_motor = 1 if (bool(best.get("has_motor_pattern", 0)) or bool(cycle.get("has_motor_pattern", False))) else 0
                profile_points = self._normalize_profile_points(cycle.get("profile_points", []))
                if not profile_points:
                    profile_points = self._normalize_profile_points(best.get("profile_points", []))
                profile_points_json = json.dumps(profile_points)
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

                with self._patterns_conn:
                    self._patterns_conn.execute(
                        """
                        UPDATE learned_patterns
                        SET updated_at = ?, last_seen = ?, seen_count = ?,
                            avg_power_w = ?, peak_power_w = ?, duration_s = ?, energy_wh = ?,
                            avg_active_phases = ?, phase_mode = ?, phase = ?,
                            power_variance = ?, rise_rate_w_per_s = ?, fall_rate_w_per_s = ?,
                            duty_cycle = ?, peak_to_avg_ratio = ?, num_substates = ?,
                            has_heating_pattern = ?, has_motor_pattern = ?,
                            profile_points_json = ?,
                            quality_score_avg = ?,
                            operating_modes = ?,
                            has_multiple_modes = ?,
                            typical_interval_s = ?, avg_hour_of_day = ?,
                            last_intervals_json = ?, hour_distribution_json = ?
                        WHERE id = ?
                        """,
                        (
                            now,
                            cycle["end_ts"],
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
                            has_heating,
                            has_motor,
                            profile_points_json,
                            quality_score_avg,
                            operating_modes_json,
                            has_multiple_modes,
                            typical_interval_s,
                            avg_hour_of_day,
                            last_intervals_json,
                            hour_distribution_json,
                            int(best["id"]),
                        ),
                    )

                best.update(
                    {
                        "updated_at": now,
                        "last_seen": cycle["end_ts"],
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
                        "has_heating_pattern": has_heating,
                        "has_motor_pattern": has_motor,
                        "profile_points": profile_points,
                        "quality_score_avg": quality_score_avg,
                        "operating_modes": merged_modes,
                        "has_multiple_modes": bool(has_multiple_modes),
                    }
                )
                return {
                    "matched": True,
                    "distance": best_distance,
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
                has_heating = 1 if cycle.get("has_heating_pattern", False) else 0
                has_motor = 1 if cycle.get("has_motor_pattern", False) else 0
                profile_points = self._normalize_profile_points(cycle.get("profile_points", []))
                profile_points_json = json.dumps(profile_points)
                
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
                
                cur = self._patterns_conn.execute(
                    """
                    INSERT INTO learned_patterns (
                        created_at, updated_at, first_seen, last_seen, seen_count,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        suggestion_type, user_label, status,
                        avg_active_phases, phase_mode, phase,
                        power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
                        duty_cycle, peak_to_avg_ratio, num_substates,
                        has_heating_pattern, has_motor_pattern,
                        profile_points_json,
                        quality_score_avg,
                        operating_modes, has_multiple_modes,
                        typical_interval_s, avg_hour_of_day, last_intervals_json, hour_distribution_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        suggestion_type,
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
                        has_heating,
                        has_motor,
                        profile_points_json,
                        quality_score,
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
                "suggestion_type": suggestion_type,
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
                "has_heating_pattern": 1 if cycle.get("has_heating_pattern", False) else 0,
                "has_motor_pattern": 1 if cycle.get("has_motor_pattern", False) else 0,
                "profile_points": self._normalize_profile_points(cycle.get("profile_points", [])),
                "quality_score_avg": quality_score,
                "candidate_name": self._normalize_pattern_name(suggestion_type),
                "is_confirmed": False,
            }
            return {"matched": False, "distance": None, "pattern": created}
        except Exception as e:
            logger.error(f"Failed to learn cycle pattern: {e}", exc_info=True)
            return {"matched": False, "pattern": None}

    def label_pattern(self, pattern_id: int, user_label: str) -> bool:
        if not self._patterns_conn:
            return False
        try:
            with self._patterns_conn:
                self._patterns_conn.execute(
                    "UPDATE learned_patterns SET user_label = ?, updated_at = ? WHERE id = ?",
                    (str(user_label).strip(), datetime.now().isoformat(), int(pattern_id)),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to label pattern {pattern_id}: {e}", exc_info=True)
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

    def clear_readings_only(self) -> Dict:
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
                        duty_cycle, peak_to_avg_ratio, num_substates,
                        has_heating_pattern, has_motor_pattern,
                        profile_points_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        avg_power, peak_power, duration_s, energy_wh, phase_mode, dominant_phase,
                        user_label.strip(), 1, "user_defined", "active",
                        start_time, end_time, now, now,
                        power_variance, rise_rate, fall_rate,
                        duty_cycle_val, peak_to_avg, num_substates,
                        has_heating, has_motor,
                        profile_points_json,
                    )
                )
                pattern_id = cursor.lastrowid
            logger.info(
                f"Created pattern {pattern_id} from range: {len(power_readings)} points, "
                f"avg={avg_power:.1f}W, peak={peak_power:.1f}W, duration={duration_s:.1f}s, "
                f"label={user_label}, substates={num_substates}, "
                f"heating={bool(has_heating)}, motor={bool(has_motor)}"
            )
            
            return {
                "ok": True,
                "pattern_id": pattern_id,
                "data_points": len(power_readings),
                "avg_power_w": avg_power,
                "peak_power_w": peak_power,
                "duration_s": duration_s,
                "num_substates": num_substates
            }
        except Exception as e:
            logger.error(f"Failed to create pattern from range: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}
