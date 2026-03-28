"""Entry point wiring together the modular NILM detection stack."""
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.collector.source import Collector, HARestPowerSource
from app.config import Config, load_options_from_file
from app.confidence.confidence import ConfidenceEvaluator
from app.detectors import AdaptiveLoadDetector, FridgeDetector, InverterDeviceDetector
from app.ha_client import HomeAssistantAPIClient
from app.learning import PatternLearner
from app.models import PowerReading
from app.processing.pipeline import ProcessingPipeline
from app.publishers.mqtt import MQTTPublisher
from app.state_engine import StateEngine
from app.storage import SQLiteStore
from app.utils.logging import get_logger, setup_logging
from app.web import StatsWebServer

logger = get_logger(__name__)


DEFAULT_ENTITIES = [
    "sensor.sph_10k_tl3_battery_soc",
    "sensor.spa_ac_power_to_grid_total",
    "sensor.miner_d2cf16_miner_consumption",
]


class NILMDetectionSystem:
    """Coordinates collectors, detectors, confidence takers and publishers."""

    def __init__(self, config_path: str = "/data/options.json"):
        # Bootstrap logging so configuration-load failures are visible in addon logs.
        setup_logging(debug=False, name="NILM", log_level="info")
        options = load_options_from_file(config_path)
        self.config = Config()
        self.config.load(options)

        # Reconfigure logging with final settings including log file rotation
        setup_logging(
            debug=self.config.debug, 
            name="NILM", 
            log_level=self.config.log_level,
            log_file=self.config.log_file,
            max_backups=self.config.max_log_backups
        )
        logger.info("Starting NILM Detection System...")
        logger.info(
            "Runtime configuration loaded: "
            f"log_level={self.config.log_level}, "
            f"update_interval_seconds={self.config.update_interval_seconds}, "
            f"devices={len(self.config.devices)}, "
            f"mqtt={self.config.mqtt_broker}:{self.config.mqtt_port}, "
            f"power_source={self.config.power_source}"
        )

        self.config.ensure_storage_path()

        self.state_engine = StateEngine()
        selected_phases = list(self.config.get_selected_phase_entities().keys())
        self.collector = Collector(
            self._build_power_source(),
            phases=selected_phases or ['L1'],
        )

        self.storage = None
        if self.config.storage_enabled:
            self.storage = SQLiteStore(
                db_path=self.config.storage_db_path,
                patterns_db_path=self.config.storage_patterns_db_path,
                retention_days=self.config.storage_retention_days,
            )
            if not self.storage.connect():
                logger.warning("SQLite storage initialization failed; continuing without persistence")
                self.storage = None
            elif self.storage:
                self.storage.configure_hybrid_ai(
                    ai_enabled=self.config.ai_enabled,
                    ml_enabled=self.config.ml_enabled,
                    shape_matching_enabled=self.config.shape_matching_enabled,
                    online_learning_enabled=self.config.online_learning_enabled,
                    pattern_match_threshold=self.config.pattern_match_threshold,
                    ml_confidence_threshold=self.config.ml_confidence_threshold,
                )
                try:
                    patterns_loaded = len(self.storage.list_patterns(limit=1000))
                    summary = self.storage.get_summary(hours=24)
                    logger.info(
                        "Startup storage state: patterns_loaded=%s readings_24h=%s",
                        patterns_loaded,
                        int(summary.get("reading_count", 0) or 0),
                    )
                except Exception as startup_diag_error:
                    logger.warning("Startup storage state diagnostics failed: %s", startup_diag_error)

        self.processing_pipeline = ProcessingPipeline(
            smoothing_window=self.config.processing_smoothing_window,
            noise_threshold=self.config.processing_noise_threshold,
            adaptive_correction=self.config.processing_adaptive_correction,
        )

        # Phase-based pattern learning: separate tracker per phase
        self.phase_learners: Dict[str, PatternLearner] = {}
        if self.config.learning_enabled and self.storage:
            phase_entities = self.config.get_selected_phase_entities()
            for phase_name, entity_id in phase_entities.items():
                if entity_id and entity_id.strip():  # Only create learner if phase is configured
                    self.phase_learners[phase_name] = PatternLearner(
                        on_threshold_w=self.config.learning_on_threshold_w,
                        off_threshold_w=self.config.learning_off_threshold_w,
                        min_cycle_seconds=self.config.learning_min_cycle_seconds,
                        adaptive_on_offset_w=self.config.learning_delta_on_w,
                        adaptive_off_offset_w=self.config.learning_delta_off_w,
                        max_gap_s=self.config.learning_max_gap_s,
                    )
                    logger.info(f"Pattern learner initialized for phase {phase_name}")
            
            if not self.phase_learners:
                logger.warning("No phase learners initialized - no phase entities configured")

        # Legacy: keep reference for backwards compatibility (uses first available learner)
        self.pattern_learner: PatternLearner | None = None
        if self.phase_learners:
            self.pattern_learner = next(iter(self.phase_learners.values()))

        self.confidence_evaluator = ConfidenceEvaluator(
            min_confidence=self.config.confidence_threshold
        )

        self.detectors: Dict[str, List] = {}
        self._setup_detectors()
        self._warm_start_detectors()

        self.publisher: MQTTPublisher | None = None
        if self.config.mqtt_enabled:
            self.publisher = MQTTPublisher(
                broker=self.config.mqtt_broker,
                port=self.config.mqtt_port,
                username=self.config.mqtt_username,
                password=self.config.mqtt_password,
                topic_prefix=self.config.mqtt_topic_prefix,
                discovery_prefix=self.config.mqtt_discovery_prefix,
                enable_discovery=self.config.enable_mqtt_discovery,
                entity_id_prefix=self.config.ha_entity_id_prefix,
            )

        self.running = False
        self.last_daily_reset = datetime.now()
        self.last_nightly_learning_date = None
        self.last_periodic_learning_run: Optional[datetime] = None
        self.web_server: StatsWebServer | None = None

        if self.config.web_enabled:
            self.web_server = StatsWebServer(
                host="0.0.0.0",
                port=self.config.web_port,
                get_live_data=self._build_live_payload,
                get_summary_data=self._build_summary_payload,
                get_series_data=self._build_series_payload,
                get_patterns_data=self._build_patterns_payload,
                set_pattern_label=self._set_pattern_label,
                delete_pattern=self._delete_pattern,
                flush_debug_data=self._flush_debug_db,
                clear_readings_only=self._clear_readings_only,
                clear_patterns_only=self._clear_patterns_only,
                run_learning_now=self._run_learning_now,
                import_history_from_ha=self._import_history_from_ha,
                create_pattern_from_range=self._create_pattern_from_range,
                language=self.config.language,
                storage=self.storage,
            )

    def _build_power_source(self):
        token = str(self.config.ha_token or "").strip()
        if not token:
            token = str(os.getenv("SUPERVISOR_TOKEN", "")).strip()
        if not token:
            # Legacy fallback used in some HA addon environments.
            token = str(os.getenv("HASSIO_TOKEN", "")).strip()

        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()

        phase_entities = self.config.get_selected_phase_entities()
        logger.info(
            "Using HA REST power source: "
            f"phases={phase_entities}, url={self.config.ha_url}, "
            f"token_present={bool(token)}"
        )
        return HARestPowerSource(
            ha_url=self.config.ha_url,
            entity_id="",
            token=token,
            phase_entity_ids=phase_entities,
        )

    def _warm_start_detectors(self) -> None:
        if not self.storage:
            return

        warmstart_result = self.storage.get_warmstart_power_values(
            minutes=self.config.learning_warmup_minutes,
            limit=300,
            fallback_limit=300,
        )
        diagnostics = warmstart_result.get("diagnostics", {}) if isinstance(warmstart_result, dict) else {}
        history = warmstart_result.get("values", []) if isinstance(warmstart_result, dict) else []
        logger.info(
            "Warmstart diagnostics: db_exists=%s size=%sB tables=%s power_rows=%s recent_rows=%s fallback_rows=%s source=%s reason=%s",
            bool((diagnostics.get("live_db") or {}).get("exists", False)),
            int((diagnostics.get("live_db") or {}).get("size_bytes", 0) or 0),
            ",".join(diagnostics.get("tables", []) or []) or "<none>",
            int(diagnostics.get("power_readings_rows", 0) or 0),
            int(diagnostics.get("recent_rows", 0) or 0),
            int(diagnostics.get("fallback_rows", 0) or 0),
            str(warmstart_result.get("source", "unknown") if isinstance(warmstart_result, dict) else "unknown"),
            str(diagnostics.get("reason", "")),
        )
        if not history:
            logger.info("No historical readings available for detector warm start")
            return

        warmed = 0
        for detector_group in self.detectors.values():
            for detector in detector_group:
                prime_fn = getattr(detector, "prime_with_history", None)
                if callable(prime_fn):
                    prime_fn(history)
                    warmed += 1

        logger.info(f"Warm-started {warmed} detector(s) from {len(history)} stored samples")

    def _setup_detectors(self) -> None:
        for device_name, device_config in self.config.devices.items():
            if not device_config.enabled:
                logger.info(f"Skipping disabled device: {device_name}")
                continue

            self.state_engine.register_device(device_name, device_config)
            detector_list = []
            detector_type = device_config.detector_type.lower()

            if detector_type == "inverter":
                detector_list.append(InverterDeviceDetector(device_config))
                detector_list.append(AdaptiveLoadDetector(device_config))
            elif detector_type == "adaptive":
                detector_list.append(AdaptiveLoadDetector(device_config))
            else:
                detector_list.append(FridgeDetector(device_config))
                detector_list.append(AdaptiveLoadDetector(device_config))

            self.detectors[device_name] = detector_list
            logger.info(f"Configured detectors for {device_name}: {[type(d).__name__ for d in detector_list]}")

    def _build_live_payload(self) -> Dict:
        latest = self.collector.get_latest()
        states = self.state_engine.get_all_states()
        device_payload = {}
        for name, state in states.items():
            phase_total_w = state.metadata.get("phase_total_w") if isinstance(state.metadata, dict) else None
            device_payload[name] = {
                "state": state.state.value,
                "power_w": float(state.power_w),
                "estimated_power_w": float(state.power_w),
                "phase_total_w": float(phase_total_w) if phase_total_w is not None else None,
                "confidence": float(state.confidence),
                "daily_cycles": int(state.daily_cycles),
                "daily_runtime_seconds": float(state.daily_runtime_seconds),
                "last_update": state.last_update.isoformat() if state.last_update else None,
            }

        learned_devices = self._build_learned_devices_payload(
            latest=latest,
            existing_names=set(device_payload.keys()),
        )
        device_payload.update(learned_devices)

        # Extract phase information from latest reading
        phase_powers = {}
        phase_entities = {}
        if latest and isinstance(latest.metadata, dict):
            phase_powers = latest.metadata.get("phase_powers_w", {})
            phase_entities = latest.metadata.get("phase_entities", {})
        
        phases_info = []
        for phase_name in ["L1", "L2", "L3"]:
            if phase_name in phase_powers:
                phases_info.append({
                    "name": phase_name,
                    "power_w": float(phase_powers[phase_name]),
                    "entity_id": phase_entities.get(phase_name, ""),
                })

        return {
            "current_power_w": float(latest.power_w) if latest else None,
            "timestamp": latest.timestamp.isoformat() if latest else None,
            "phases": phases_info,
            "devices": device_payload,
        }

    def _select_representative_patterns(self, limit: int = 100) -> List[Dict]:
        if not self.storage:
            return []

        try:
            patterns = self.storage.list_patterns(limit=limit)
        except Exception as pattern_error:
            logger.debug("Failed to load learned patterns for device view: %s", pattern_error)
            return []

        representatives: Dict[str, tuple] = {}
        for item in patterns:
            label = str(
                item.get("device_group_label")
                or item.get("user_label")
                or item.get("candidate_name")
                or item.get("suggestion_type")
                or ""
            ).strip()
            if not label:
                continue

            seen_count = max(int(item.get("seen_count", 0) or 0), 0)
            base_confidence = max(0.0, min(float(item.get("confidence_score", 0.0) or 0.0) / 100.0, 1.0))
            is_unknown = label.lower() in {"unknown", "unbekannt"}
            if seen_count < 2 and base_confidence < 0.45:
                continue
            if is_unknown and seen_count < 4 and base_confidence < 0.65:
                continue

            rank = (
                1 if item.get("is_confirmed") else 0,
                base_confidence,
                seen_count,
                float(item.get("avg_power_w", 0.0) or 0.0),
            )
            current = representatives.get(label)
            if current is None or rank > current[0]:
                representatives[label] = (rank, item)

        ranked = sorted(representatives.values(), key=lambda entry: entry[0], reverse=True)
        return [item for _, item in ranked]

    def _build_learned_devices_payload(self, latest, existing_names: set[str] | None = None) -> Dict[str, Dict]:
        existing_names = existing_names or set()
        patterns = self._select_representative_patterns(limit=100)
        if not patterns:
            return {}

        phase_powers: Dict[str, float] = {}
        if latest and isinstance(latest.metadata, dict):
            raw_phase_powers = latest.metadata.get("phase_powers_w", {})
            if isinstance(raw_phase_powers, dict):
                for phase_name, value in raw_phase_powers.items():
                    try:
                        phase_powers[str(phase_name).upper()] = float(value)
                    except (TypeError, ValueError):
                        continue

        total_power = float(latest.power_w) if latest else 0.0
        candidates_by_bucket: Dict[str, List[Dict]] = {}
        pattern_runtime_meta: List[Dict] = []

        for pattern in patterns:
            base_name = str(
                pattern.get("device_group_label")
                or pattern.get("user_label")
                or pattern.get("candidate_name")
                or pattern.get("suggestion_type")
                or "gelerntes geraet"
            ).strip()
            if not base_name:
                continue

            display_name = base_name if base_name not in existing_names else f"{base_name} (learned)"
            avg_power_w = max(float(pattern.get("avg_power_w", 0.0) or 0.0), 1.0)
            peak_power_w = max(float(pattern.get("peak_power_w", avg_power_w) or avg_power_w), avg_power_w)
            phase_name = str(pattern.get("phase") or "TOTAL").upper()
            bucket = phase_name if phase_name in phase_powers else "TOTAL"
            observed_power = float(phase_powers.get(bucket, total_power)) if bucket != "TOTAL" else total_power
            base_confidence = max(0.0, min(float(pattern.get("confidence_score", 0.0) or 0.0) / 100.0, 1.0))

            lower_bound = max(25.0, avg_power_w * 0.45)
            upper_bound = max(80.0, avg_power_w * 1.90, peak_power_w * 1.35)
            closeness = 0.0
            if observed_power >= lower_bound:
                delta_ratio = abs(observed_power - avg_power_w) / max(avg_power_w, 1.0)
                closeness = max(0.0, 1.0 - delta_ratio)
                if observed_power > upper_bound:
                    overload_ratio = min((observed_power - upper_bound) / max(upper_bound, 1.0), 1.0)
                    closeness *= (1.0 - overload_ratio)

            runtime_meta = {
                "name": display_name,
                "bucket": bucket,
                "phase": phase_name,
                "avg_power_w": avg_power_w,
                "observed_power": observed_power,
                "base_confidence": base_confidence,
                "live_match_score": base_confidence * closeness,
                "seen_count": int(pattern.get("seen_count", 0) or 0),
                "pattern": pattern,
            }
            pattern_runtime_meta.append(runtime_meta)
            if runtime_meta["live_match_score"] > 0.0:
                candidates_by_bucket.setdefault(bucket, []).append(runtime_meta)

        active_names: set[str] = set()
        for bucket, candidates in candidates_by_bucket.items():
            remaining_power = float(phase_powers.get(bucket, total_power)) if bucket != "TOTAL" else total_power
            ordered = sorted(
                candidates,
                key=lambda item: (item["live_match_score"], item["seen_count"], item["avg_power_w"]),
                reverse=True,
            )
            for candidate in ordered:
                if candidate["live_match_score"] < 0.33:
                    break
                expected = float(candidate["avg_power_w"])
                tolerance = max(25.0, expected * 0.35)
                if remaining_power + tolerance < expected:
                    continue
                active_names.add(str(candidate["name"]))
                remaining_power = max(0.0, remaining_power - min(remaining_power, expected))

        payload: Dict[str, Dict] = {}
        for item in pattern_runtime_meta:
            name = str(item["name"])
            pattern = item["pattern"]
            is_active = name in active_names
            match_score = float(item["live_match_score"])
            base_confidence = float(item["base_confidence"])
            display_confidence = max(0.0, min(0.99, (base_confidence * 0.55) + (match_score * 0.45))) if is_active else max(0.0, min(0.75, base_confidence * 0.40))
            payload[name] = {
                "state": "on" if is_active else "off",
                "power_w": float(item["observed_power"] if is_active else 0.0),
                "estimated_power_w": float(item["observed_power"] if is_active else 0.0),
                "phase_total_w": float(item["observed_power"]),
                "confidence": round(display_confidence, 2),
                "daily_cycles": None,
                "daily_runtime_seconds": None,
                "last_update": latest.timestamp.isoformat() if latest else None,
                "source": "learned_pattern",
                "phase": item["phase"],
                "pattern_id": pattern.get("id"),
                "pattern_seen_count": item["seen_count"],
                "pattern_label": pattern.get("user_label") or pattern.get("candidate_name") or pattern.get("suggestion_type"),
            }

        return payload

    def _build_summary_payload(self) -> Dict:
        if not self.storage:
            return {
                "reading_count": 0,
                "avg_power_w": 0.0,
                "min_power_w": 0.0,
                "max_power_w": 0.0,
            }
        return self.storage.get_summary(hours=24)

    def _build_series_payload(self, limit: int, offset: int = 0) -> List[Dict]:
        if not self.storage:
            return []
        return self.storage.get_power_series(limit=limit, offset=offset)

    def _build_patterns_payload(self) -> List[Dict]:
        if not self.storage:
            return []
        return self.storage.list_patterns(limit=100)

    def _set_pattern_label(self, pattern_id: int, label: str) -> bool:
        if not self.storage:
            return False
        return self.storage.label_pattern(pattern_id=pattern_id, user_label=label)

    def _create_pattern_from_range(self, start_time: str, end_time: str, label: str) -> Dict:
        """Create a new learned pattern from a manually selected time range."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        
        return self.storage.create_pattern_from_range(
            start_time=start_time,
            end_time=end_time,
            user_label=label
        )

    def _delete_pattern(self, pattern_id: int) -> bool:
        """Delete a single learned pattern."""
        if not self.storage:
            return False
        return self.storage.delete_pattern(pattern_id=pattern_id)

    def _clear_readings_only(self) -> Dict:
        """Clear only live readings, keep patterns."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        return self.storage.clear_readings_only()

    def _clear_patterns_only(self) -> Dict:
        """Clear only patterns, keep live readings."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        return self.storage.clear_patterns_only()

    def _flush_debug_db(self, reset_patterns: bool = True) -> Dict:
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        return self.storage.flush_debug_data(reset_patterns=reset_patterns)

    def _run_pipeline_now(self, source: str = "manual") -> Dict:
        """Run replay + merge pipeline to actively learn from newly stored readings."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        if not self.config.learning_enabled:
            return {"ok": False, "error": "learning is disabled"}

        replay_summary = {"cycles_detected": 0, "points_processed": 0}
        if self.pattern_learner:
            try:
                replay_hours = 48 if source == "manual_web" else 24
                replay_summary = self._replay_learning_from_storage(hours=replay_hours)
            except Exception as e:
                logger.error("Manual learning replay failed: %s", e, exc_info=True)
                replay_summary = {"cycles_detected": 0, "points_processed": 0, "error": str(e)}

        result = self.storage.run_nightly_learning_pass(
            merge_tolerance=0.20,
            max_patterns=800,
        )
        result["cycles_detected"] = int(replay_summary.get("cycles_detected", 0))
        result["points_processed"] = int(replay_summary.get("points_processed", 0))
        result["source"] = source
        if result.get("ok"):
            self.last_periodic_learning_run = datetime.now()
        return result

    def _run_learning_now(self) -> Dict:
        """Manual trigger for immediate pipeline execution from Web UI."""
        return self._run_pipeline_now(source="manual_web")

    def _replay_learning_from_storage(self, hours: int = 24) -> Dict:
        """Replay recent stored readings through PatternLearner to build cycles on demand."""
        if not self.storage:
            return {"cycles_detected": 0, "points_processed": 0}

        # Approximate sample count from configured polling interval.
        interval = max(int(self.config.update_interval_seconds), 1)
        approx_points = max(300, min(int((hours * 3600) / interval) + 120, 50000))
        points = self.storage.get_power_series(limit=approx_points, max_limit=50000)
        if not points:
            return {"cycles_detected": 0, "points_processed": 0}

        # Use fresh per-phase learners for replay to avoid cross-phase contamination.
        configured_phases = [str(p).upper() for p in self.config.get_selected_phase_entities().keys()]
        replay_phases = configured_phases if configured_phases else ["L1"]

        def _new_replay_learners() -> Dict[str, PatternLearner]:
            learners: Dict[str, PatternLearner] = {}
            for phase_name in replay_phases:
                learners[phase_name] = PatternLearner(
                    on_threshold_w=self.config.learning_on_threshold_w,
                    off_threshold_w=self.config.learning_off_threshold_w,
                    min_cycle_seconds=self.config.learning_min_cycle_seconds,
                    adaptive_on_offset_w=self.config.learning_delta_on_w,
                    adaptive_off_offset_w=self.config.learning_delta_off_w,
                    debounce_samples=1,
                    noise_filter_window=1,
                    max_gap_s=self.config.learning_max_gap_s,
                )
            return learners

        replay_learners: Dict[str, PatternLearner] = _new_replay_learners()

        # Prime adaptive baseline from initial samples so replay does not start in a false ON state.
        baseline_seed_count = min(60, len(points))
        baseline_by_phase: Dict[str, List[float]] = {phase_name: [] for phase_name in replay_phases}
        for point in points[:baseline_seed_count]:
            phases = point.get("phases") if isinstance(point.get("phases"), dict) else {}
            normalized_phases: Dict[str, float] = {}
            for phase_key, phase_val in phases.items():
                try:
                    normalized_phases[str(phase_key).upper()] = float(phase_val)
                except (TypeError, ValueError):
                    continue

            for phase_name in replay_phases:
                value = 0.0
                if phase_name in normalized_phases:
                    value = float(normalized_phases[phase_name])
                elif len(replay_phases) == 1:
                    try:
                        value = float(point.get("power_w") or 0.0)
                    except (TypeError, ValueError):
                        value = 0.0
                baseline_by_phase[phase_name].append(value)

        def _run_replay_pass(
            learners: Dict[str, PatternLearner],
            skip_seed_points: bool,
        ) -> Dict[str, object]:
            cycles_detected_local = 0
            cycles_by_phase_local: Dict[str, int] = {phase_name: 0 for phase_name in replay_phases}

            for idx, point in enumerate(points):
                try:
                    ts_raw = str(point.get("timestamp") or "").strip()
                    if not ts_raw:
                        continue

                    try:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    if ts.tzinfo is not None:
                        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)

                    phases = point.get("phases") if isinstance(point.get("phases"), dict) else {}
                    normalized_phases: Dict[str, float] = {}
                    for phase_key, phase_val in phases.items():
                        try:
                            normalized_phases[str(phase_key).upper()] = float(phase_val)
                        except (TypeError, ValueError):
                            continue

                    # Skip cycle detection during warmup points used for baseline seeding.
                    if skip_seed_points and idx < baseline_seed_count:
                        continue

                    for phase_name, learner in learners.items():
                        phase_power = 0.0
                        if phase_name in normalized_phases:
                            phase_power = float(normalized_phases[phase_name])
                        elif len(replay_phases) == 1:
                            try:
                                phase_power = float(point.get("power_w") or 0.0)
                            except (TypeError, ValueError):
                                phase_power = 0.0

                        phase_reading = PowerReading(
                            timestamp=ts,
                            power_w=phase_power,
                            phase=phase_name,
                            metadata={
                                "phase": phase_name,
                                "phase_powers_w": {phase_name: phase_power},
                                "replay_learning": True,
                            },
                        )

                        cycle = learner.ingest(phase_reading)
                        if not cycle:
                            continue

                        cycle_features = cycle.features
                        cycle_payload = {
                            "start_ts": cycle.start_ts.isoformat(),
                            "end_ts": cycle.end_ts.isoformat(),
                            "duration_s": cycle.duration_s,
                            "avg_power_w": cycle.avg_power_w,
                            "peak_power_w": cycle.peak_power_w,
                            "energy_wh": cycle.energy_wh,
                            "operating_modes": cycle.operating_modes,
                            "has_multiple_modes": cycle.has_multiple_modes,
                            "active_phase_count": 1,
                            "phase_mode": "single_phase",
                            "phase": phase_name,
                            "power_variance": float(cycle_features.power_variance) if cycle_features else 0.0,
                            "rise_rate_w_per_s": float(cycle_features.rise_rate_w_per_s) if cycle_features else 0.0,
                            "fall_rate_w_per_s": float(cycle_features.fall_rate_w_per_s) if cycle_features else 0.0,
                            "duty_cycle": float(cycle_features.duty_cycle) if cycle_features else 0.0,
                            "peak_to_avg_ratio": float(cycle_features.peak_to_avg_ratio) if cycle_features else 1.0,
                            "num_substates": int(cycle_features.num_substates) if cycle_features else 0,
                            "has_heating_pattern": bool(cycle_features.has_heating_pattern) if cycle_features else False,
                            "has_motor_pattern": bool(cycle_features.has_motor_pattern) if cycle_features else False,
                            "profile_points": list(cycle.profile_points or []),
                        }
                        heuristic_suggestion = learner.suggest_device_type(cycle)
                        model_suggestion = self.storage.suggest_cycle_label(cycle_payload, fallback=heuristic_suggestion)
                        suggestion = str(model_suggestion.get("label") or heuristic_suggestion)
                        self.storage.learn_cycle_pattern(cycle=cycle_payload, suggestion_type=suggestion)
                        cycles_detected_local += 1
                        cycles_by_phase_local[phase_name] = cycles_by_phase_local.get(phase_name, 0) + 1
                except Exception as point_error:
                    logger.debug("Skipping replay point due to error: %s", point_error)
                    continue

            return {
                "cycles_detected": cycles_detected_local,
                "cycles_by_phase": cycles_by_phase_local,
            }

        for phase_name, learner in replay_learners.items():
            learner.prime_baseline(baseline_by_phase.get(phase_name, []))

        pass_result = _run_replay_pass(replay_learners, skip_seed_points=True)
        cycles_detected = int(pass_result.get("cycles_detected", 0) or 0)
        cycles_by_phase = dict(pass_result.get("cycles_by_phase", {}))

        # Fallback: if adaptive baseline priming was too conservative, retry once unprimed.
        if cycles_detected == 0 and len(points) > 20:
            logger.info("Replay pass found no cycles; retrying replay without baseline priming")
            retry_learners = _new_replay_learners()
            retry_result = _run_replay_pass(retry_learners, skip_seed_points=False)
            cycles_detected = int(retry_result.get("cycles_detected", 0) or 0)
            cycles_by_phase = dict(retry_result.get("cycles_by_phase", {}))

        return {
            "cycles_detected": cycles_detected,
            "points_processed": len(points),
            "cycles_by_phase": cycles_by_phase,
        }

    def _import_history_from_ha(self, hours: int = 24) -> Dict:
        """Import historical phase sensor values from HA recorder into local storage."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}

        phase_entities = self.config.get_selected_phase_entities()
        if not phase_entities:
            return {"ok": False, "error": "no phase entities configured"}

        token = str(self.config.ha_token or "").strip() or str(os.getenv("SUPERVISOR_TOKEN", "")).strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()

        client = HomeAssistantAPIClient(
            base_url=self.config.ha_url,
            token=token,
            timeout_seconds=20,
        )

        now = datetime.now()
        start_time = now - timedelta(hours=max(1, min(int(hours), 168)))

        # Build chronological phase events and reconstruct totals with carry-forward
        # values per phase. This avoids artificial drops when only one phase updates.
        phase_events: List[tuple[datetime, str, float]] = []
        source_counts: Dict[str, int] = {}
        skipped_non_positive = 0

        try:
            for phase_name, entity_id in phase_entities.items():
                events = client.get_entity_history(entity_id, start_time=start_time, end_time=now)
                source_counts[phase_name] = len(events)
                for event in events:
                    ts_raw = event.get("last_changed") or event.get("last_updated")
                    state_raw = event.get("state")
                    if not ts_raw:
                        continue
                    try:
                        value = float(state_raw)
                    except (TypeError, ValueError):
                        continue

                    # Ignore non-positive values to avoid synthetic 0W noise in replay graphs.
                    if value <= 0.0:
                        skipped_non_positive += 1
                        continue

                    try:
                        ts_obj = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    if ts_obj.tzinfo is not None:
                        ts_obj = ts_obj.astimezone(timezone.utc).replace(tzinfo=None)

                    phase_events.append((ts_obj, phase_name, value))

            imported = 0
            if not phase_events:
                return {
                    "ok": True,
                    "imported": 0,
                    "sources": source_counts,
                    "skipped_non_positive": skipped_non_positive,
                    "hours": max(1, min(int(hours), 168)),
                }

            phase_events.sort(key=lambda item: item[0])
            last_phase_values: Dict[str, float] = {phase: 0.0 for phase in phase_entities.keys()}

            for ts_obj, phase_name, value in phase_events:
                last_phase_values[phase_name] = float(value)
                total_power = float(sum(last_phase_values.values()))
                if total_power <= 0.0:
                    continue

                metadata = {
                    "phase_powers_w": dict(last_phase_values),
                    "phase_entities": phase_entities,
                    "imported_from": "ha_history",
                }
                self.storage.store_reading(PowerReading(timestamp=ts_obj, power_w=total_power, phase="TOTAL", metadata=metadata))
                imported += 1

            return {
                "ok": True,
                "imported": imported,
                "sources": source_counts,
                "skipped_non_positive": skipped_non_positive,
                "hours": max(1, min(int(hours), 168)),
            }
        except Exception as e:
            logger.error("Failed to import HA history: %s", e, exc_info=True)
            return {"ok": False, "error": str(e)}
        finally:
            client.close()

    def _maybe_run_nightly_learning(self, now: datetime) -> None:
        """Run lightweight learning maintenance once per night (off-peak window)."""
        if not self.storage or not self.config.learning_enabled:
            return

        # Run once per calendar day in an off-peak window.
        if now.hour < 2 or now.hour > 5:
            return
        if self.last_nightly_learning_date == now.date():
            return

        result = self._run_pipeline_now(source="nightly")
        if result.get("ok"):
            self.last_nightly_learning_date = now.date()
        logger.info(
            "Nightly learning pass completed: "
            f"ok={result.get('ok')} merged={result.get('merged', 0)} "
            f"patterns={result.get('patterns_considered', 0)}"
        )

    def _maybe_run_periodic_learning(self, now: datetime) -> None:
        """Run automatic learning pipeline at a configured interval throughout the day."""
        if not self.storage or not self.config.learning_enabled:
            return
        if not self.config.learning_auto_pipeline_enabled:
            return

        interval_minutes = max(5, int(self.config.learning_auto_pipeline_interval_minutes))
        if self.last_periodic_learning_run is not None:
            elapsed = (now - self.last_periodic_learning_run).total_seconds()
            if elapsed < (interval_minutes * 60):
                return

        result = self._run_pipeline_now(source="auto_periodic")
        logger.info(
            "Periodic learning pass completed: "
            f"ok={result.get('ok')} cycles={result.get('cycles_detected', 0)} "
            f"merged={result.get('merged', 0)} patterns={result.get('patterns_considered', 0)}"
        )

    def start(self) -> None:
        if not self.collector.connect():
            logger.error("Collector failed to connect")
            return
        logger.info("Collector connected successfully")

        if self.publisher and not self.publisher.connect():
            logger.warning(
                "MQTT connect failed; continuing without publisher "
                f"(mqtt={self.config.mqtt_broker}:{self.config.mqtt_port})"
            )
            self.publisher = None
        elif self.publisher:
            logger.info("MQTT publisher connected")
        else:
            logger.info("MQTT output disabled by configuration (mqtt.enabled=false)")

        if self.web_server:
            if not self.web_server.start():
                logger.warning("Web UI server failed to start")

        self.running = True
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        logger.info("Detection system started")
        self._main_loop()

    def _main_loop(self) -> None:
        iteration = 0
        while self.running:
            iteration += 1
            try:
                reading = self.collector.read()
                if not reading:
                    if iteration % 50 == 0:
                        logger.warning("No power reading received from collector")
                    time.sleep(0.1)
                    continue

                processed = self.processing_pipeline.process(reading)
                if self.storage:
                    self.storage.store_reading(reading)

                # Phase-based pattern learning: process each phase separately
                if self.phase_learners and self.storage:
                    phase_powers_w = processed.metadata.get("phase_powers_w", {})
                    
                    for phase_name, learner in self.phase_learners.items():
                        # Get power for this specific phase
                        phase_power = phase_powers_w.get(phase_name, 0.0)
                        
                        # Create a reading for just this phase
                        phase_reading = PowerReading(
                            timestamp=processed.timestamp,
                            power_w=phase_power,
                            phase=phase_name,
                            metadata={
                                "phase": phase_name,
                                "original_total": processed.power_w,
                                "phase_powers_w": {phase_name: phase_power}
                            }
                        )
                        
                        # Ingest into phase-specific learner
                        cycle = learner.ingest(phase_reading)
                        if cycle:
                            cycle_payload = {
                                "start_ts": cycle.start_ts.isoformat(),
                                "end_ts": cycle.end_ts.isoformat(),
                                "duration_s": cycle.duration_s,
                                "avg_power_w": cycle.avg_power_w,
                                "peak_power_w": cycle.peak_power_w,
                                "energy_wh": cycle.energy_wh,
                                "operating_modes": cycle.operating_modes,
                                "has_multiple_modes": cycle.has_multiple_modes,
                                "active_phase_count": 1,  # Single phase per learner
                                "phase_mode": "single_phase",
                                "phase": phase_name,  # Explicit phase attribution
                                "power_variance": float(cycle.features.power_variance) if cycle.features else 0.0,
                                "rise_rate_w_per_s": float(cycle.features.rise_rate_w_per_s) if cycle.features else 0.0,
                                "fall_rate_w_per_s": float(cycle.features.fall_rate_w_per_s) if cycle.features else 0.0,
                                "duty_cycle": float(cycle.features.duty_cycle) if cycle.features else 0.0,
                                "peak_to_avg_ratio": float(cycle.features.peak_to_avg_ratio) if cycle.features else 1.0,
                                "num_substates": int(cycle.features.num_substates) if cycle.features else 0,
                                "has_heating_pattern": bool(cycle.features.has_heating_pattern) if cycle.features else False,
                                "has_motor_pattern": bool(cycle.features.has_motor_pattern) if cycle.features else False,
                                "profile_points": list(cycle.profile_points or []),
                            }
                            heuristic_suggestion = learner.suggest_device_type(cycle)
                            model_suggestion = self.storage.suggest_cycle_label(
                                cycle_payload,
                                fallback=heuristic_suggestion,
                            )
                            suggestion = str(model_suggestion.get("label") or heuristic_suggestion)
                            learn_result = self.storage.learn_cycle_pattern(
                                cycle=cycle_payload,
                                suggestion_type=suggestion,
                            )
                            pattern = learn_result.get("pattern") if isinstance(learn_result, dict) else None
                            if pattern:
                                candidate_name = pattern.get("candidate_name") or pattern.get("user_label") or pattern.get("suggestion_type")
                                is_confirmed = bool(pattern.get("is_confirmed") or pattern.get("user_label"))
                                guess_prefix = "bestaetigt" if is_confirmed else "evtl."
                                logger.info(
                                    f"[{phase_name}] Pattern learned/updated: "
                                    f"id={pattern.get('id')} suggestion={pattern.get('suggestion_type')} "
                                    f"label={pattern.get('user_label') or '-'} seen={pattern.get('seen_count')} "
                                    f"model_source={model_suggestion.get('source')} "
                                    f"model_conf={float(model_suggestion.get('confidence', 0.0)):.2f} "
                                    f"-> {guess_prefix} {candidate_name}"
                                )

                for device_name, detector_group in self.detectors.items():
                    detection_candidates = []
                    for detector in detector_group:
                        try:
                            result = detector.detect(processed)
                        except Exception as detector_error:
                            logger.error(
                                f"Detector failure for {device_name} ({type(detector).__name__}): {detector_error}",
                                exc_info=True,
                            )
                            continue

                        if result:
                            detection_candidates.append(result)

                    best = self.confidence_evaluator.evaluate(
                        detection_candidates,
                        self.config.devices[device_name],
                    )

                    if not best:
                        logger.debug(f"No confident detection for {device_name}")
                        continue

                    if self.storage:
                        self.storage.store_detection(best)

                    device_state = self.state_engine.update_device_state(best)
                    if device_state and self.publisher and self.publisher.is_connected():
                        try:
                            self.publisher.publish_state(device_state)
                        except Exception as publish_error:
                            logger.error(
                                f"Failed to publish MQTT state for {device_name}: {publish_error}",
                                exc_info=True,
                            )

                if iteration % 100 == 0:
                    logger.debug(f"Main loop alive (iteration {iteration})")

                now = datetime.now()
                if (now - self.last_daily_reset).days > 0 or now.date() != self.last_daily_reset.date():
                    self.state_engine.reset_all_daily_counters()
                    self.last_daily_reset = now

                if iteration % 120 == 0:
                    self._maybe_run_nightly_learning(now)

                if iteration % 60 == 0:
                    self._maybe_run_periodic_learning(now)

                time.sleep(self.config.update_interval_seconds)
            except Exception as e:
                logger.error(f"Main loop failure: {e}", exc_info=True)
                time.sleep(self.config.update_interval_seconds)

    def _signal_handler(self, sig, frame) -> None:
        logger.info(f"Signal {sig} received, shutting down")
        self.stop()

    def stop(self) -> None:
        self.running = False
        if self.storage:
            try:
                self.storage.flush_pending_buffers()
            except Exception as flush_error:
                logger.warning("Storage pre-shutdown flush failed: %s", flush_error)
            try:
                self.storage.close()
            except Exception as close_error:
                logger.warning("Storage close failed: %s", close_error)
        self.collector.disconnect()
        if self.publisher:
            self.publisher.disconnect()
        if self.web_server:
            self.web_server.stop()
        logger.info("Detection system stopped")
        sys.exit(0)


def main() -> None:
    try:
        setup_logging(debug=False, name="NILM", log_level="info")

        # Optional lightweight polling mode for direct HA entity reads.
        if _env_bool("HA_ENTITY_READER_MODE", default=False):
            run_entity_reader_loop()
            return

        system = NILMDetectionSystem()
        system.start()
    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=True)
        sys.exit(1)


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_entity_list_from_env() -> List[str]:
    """Load comma-separated entity IDs from HA_ENTITY_LIST."""
    raw = os.getenv("HA_ENTITY_LIST", "")
    if not raw.strip():
        return list(DEFAULT_ENTITIES)

    entities = [item.strip() for item in raw.split(",") if item.strip()]
    return entities or list(DEFAULT_ENTITIES)


def run_entity_reader_loop() -> None:
    """Continuously poll configured Home Assistant entities every 5 seconds."""
    poll_interval_seconds = int(os.getenv("HA_POLL_INTERVAL_SECONDS", "5"))
    entities = _load_entity_list_from_env()

    client = HomeAssistantAPIClient(
        base_url=os.getenv("HA_SUPERVISOR_API_URL", "http://supervisor/core/api/"),
        token=os.getenv("SUPERVISOR_TOKEN", ""),
        timeout_seconds=int(os.getenv("HA_API_TIMEOUT_SECONDS", "10")),
    )

    logger.info(
        "Starting HA entity reader mode: interval=%ss, entities=%s",
        poll_interval_seconds,
        entities,
    )

    try:
        while True:
            entity_data = client.get_multiple_entities(entities)
            for entity_id, item in entity_data.items():
                logger.info(
                    "Entity %s => state=%s attributes=%s",
                    entity_id,
                    item.get("state", ""),
                    item.get("attributes", {}),
                )
            time.sleep(poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("HA entity reader mode interrupted")
    except Exception as loop_error:
        logger.error("HA entity reader mode failed: %s", loop_error, exc_info=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
