"""SQLite storage for power readings and detection events."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

from app.models import DetectionResult, PowerReading
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SQLiteStore:
    """Persists readings/detections for diagnostics and future learning."""

    def __init__(self, db_path: str, retention_days: int = 30):
        self.db_path = db_path
        self.retention_days = max(int(retention_days), 1)
        self._conn: sqlite3.Connection | None = None

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
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
            self._conn = self._open_connection()
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
            self._conn = self._open_connection()

            if not self._check_integrity(self._conn):
                if not self._reinitialize_database():
                    return False

            self._create_tables()
            self.cleanup_old_data()
            logger.info(f"SQLite storage initialized at {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SQLite storage: {e}", exc_info=True)
            return False

    def close(self) -> None:
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
            self._conn.execute(
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
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learned_patterns_seen ON learned_patterns(last_seen)"
            )

    def store_reading(self, reading: PowerReading) -> None:
        if not self._conn:
            return
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO power_readings (ts, power_w, phase, metadata) VALUES (?, ?, ?, ?)",
                    (
                        reading.timestamp.isoformat(),
                        float(reading.power_w),
                        reading.phase,
                        json.dumps(reading.metadata or {}),
                    ),
                )
        except sqlite3.DatabaseError as db_error:
            logger.error(f"SQLite DB error while persisting reading: {db_error}", exc_info=True)
            if "malformed" in str(db_error).lower():
                self._reinitialize_database()
        except Exception as e:
            logger.error(f"Failed to persist power reading: {e}", exc_info=True)

    def store_detection(self, result: DetectionResult) -> None:
        if not self._conn:
            return
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO detections (ts, device_name, state, power_w, confidence, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.timestamp.isoformat(),
                        result.device_name,
                        result.state.value,
                        float(result.power_w),
                        float(result.confidence),
                        json.dumps(result.details or {}),
                    ),
                )
        except sqlite3.DatabaseError as db_error:
            logger.error(f"SQLite DB error while persisting detection: {db_error}", exc_info=True)
            if "malformed" in str(db_error).lower():
                self._reinitialize_database()
        except Exception as e:
            logger.error(f"Failed to persist detection result: {e}", exc_info=True)

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

    def get_power_series(self, limit: int = 300) -> List[Dict]:
        if not self._conn:
            return []

        try:
            cur = self._conn.execute(
                """
                SELECT ts, power_w FROM power_readings
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
            return [{"ts": row[0], "power_w": float(row[1])} for row in reversed(rows)]
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
                self._conn.execute("DELETE FROM learned_patterns WHERE last_seen < ?", (cutoff,))
        except Exception as e:
            logger.error(f"Failed to clean old SQLite data: {e}", exc_info=True)

    @staticmethod
    def _pattern_distance(existing: Dict, candidate: Dict) -> float:
        def rel(a: float, b: float) -> float:
            base = max(abs(a), 1.0)
            return abs(a - b) / base

        avg_dist = rel(float(existing["avg_power_w"]), float(candidate["avg_power_w"]))
        peak_dist = rel(float(existing["peak_power_w"]), float(candidate["peak_power_w"]))
        duration_dist = rel(float(existing["duration_s"]), float(candidate["duration_s"]))
        energy_dist = rel(float(existing["energy_wh"]), float(candidate["energy_wh"]))
        return (avg_dist * 0.35) + (peak_dist * 0.35) + (duration_dist * 0.2) + (energy_dist * 0.1)

    @staticmethod
    def _normalize_pattern_name(name: str) -> str:
        text = str(name or "").strip().lower()
        if not text:
            return "unbekannt"
        if text.endswith("_like"):
            text = text[:-5]
        return text.replace("_", " ")

    def list_patterns(self, limit: int = 100) -> List[Dict]:
        if not self._conn:
            return []
        try:
            cur = self._conn.execute(
                """
                SELECT id, created_at, updated_at, first_seen, last_seen, seen_count,
                       avg_power_w, peak_power_w, duration_s, energy_wh,
                       suggestion_type, user_label, status
                FROM learned_patterns
                ORDER BY seen_count DESC, last_seen DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
            out: List[Dict] = []
            for row in rows:
                out.append(
                    {
                        "id": int(row[0]),
                        "created_at": row[1],
                        "updated_at": row[2],
                        "first_seen": row[3],
                        "last_seen": row[4],
                        "seen_count": int(row[5]),
                        "avg_power_w": float(row[6]),
                        "peak_power_w": float(row[7]),
                        "duration_s": float(row[8]),
                        "energy_wh": float(row[9]),
                        "suggestion_type": row[10],
                        "user_label": row[11],
                        "status": row[12],
                        "candidate_name": self._normalize_pattern_name(row[11] or row[10]),
                        "is_confirmed": bool(str(row[11] or "").strip()),
                    }
                )
            return out
        except Exception as e:
            logger.error(f"Failed to list learned patterns: {e}", exc_info=True)
            return []

    def learn_cycle_pattern(self, cycle: Dict, suggestion_type: str, tolerance: float = 0.38) -> Dict:
        """Upsert one cycle into learned_patterns and return the matched/created pattern."""
        if not self._conn:
            return {"matched": False, "pattern": None}

        now = datetime.now().isoformat()
        patterns = self.list_patterns(limit=500)

        best = None
        best_distance = 999.0
        for item in patterns:
            if item.get("status") != "active":
                continue
            distance = self._pattern_distance(item, cycle)
            if distance < best_distance:
                best_distance = distance
                best = item

        try:
            if best and best_distance <= tolerance:
                seen_count = int(best["seen_count"]) + 1
                alpha = 1.0 / seen_count

                avg_power = float(best["avg_power_w"]) * (1.0 - alpha) + float(cycle["avg_power_w"]) * alpha
                peak_power = float(best["peak_power_w"]) * (1.0 - alpha) + float(cycle["peak_power_w"]) * alpha
                duration = float(best["duration_s"]) * (1.0 - alpha) + float(cycle["duration_s"]) * alpha
                energy = float(best["energy_wh"]) * (1.0 - alpha) + float(cycle["energy_wh"]) * alpha

                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE learned_patterns
                        SET updated_at = ?, last_seen = ?, seen_count = ?,
                            avg_power_w = ?, peak_power_w = ?, duration_s = ?, energy_wh = ?
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
                    }
                )
                return {
                    "matched": True,
                    "distance": best_distance,
                    "pattern": best,
                }

            with self._conn:
                cur = self._conn.execute(
                    """
                    INSERT INTO learned_patterns (
                        created_at, updated_at, first_seen, last_seen, seen_count,
                        avg_power_w, peak_power_w, duration_s, energy_wh,
                        suggestion_type, user_label, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            }
            return {"matched": False, "distance": None, "pattern": created}
        except Exception as e:
            logger.error(f"Failed to learn cycle pattern: {e}", exc_info=True)
            return {"matched": False, "pattern": None}

    def label_pattern(self, pattern_id: int, user_label: str) -> bool:
        if not self._conn:
            return False
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE learned_patterns SET user_label = ?, updated_at = ? WHERE id = ?",
                    (str(user_label).strip(), datetime.now().isoformat(), int(pattern_id)),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to label pattern {pattern_id}: {e}", exc_info=True)
            return False
