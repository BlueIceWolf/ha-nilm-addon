"""SQLite storage for power readings and detection events."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import List

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

    def cleanup_old_data(self) -> None:
        if not self._conn:
            return

        try:
            cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
            with self._conn:
                self._conn.execute("DELETE FROM power_readings WHERE ts < ?", (cutoff,))
                self._conn.execute("DELETE FROM detections WHERE ts < ?", (cutoff,))
        except Exception as e:
            logger.error(f"Failed to clean old SQLite data: {e}", exc_info=True)
