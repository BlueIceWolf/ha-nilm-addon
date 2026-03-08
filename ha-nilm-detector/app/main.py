"""Entry point wiring together the modular NILM detection stack."""
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List

from app.collector.source import Collector, HARestPowerSource
from app.config import Config, load_options_from_file
from app.confidence.confidence import ConfidenceEvaluator
from app.detectors import AdaptiveLoadDetector, FridgeDetector, InverterDeviceDetector
from app.ha_client import HomeAssistantAPIClient
from app.learning import PatternLearner
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

        setup_logging(debug=self.config.debug, name="NILM", log_level=self.config.log_level)
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

        self.processing_pipeline = ProcessingPipeline(
            smoothing_window=self.config.processing_smoothing_window,
            noise_threshold=self.config.processing_noise_threshold,
            adaptive_correction=self.config.processing_adaptive_correction,
        )

        self.pattern_learner: PatternLearner | None = None
        if self.config.learning_enabled and self.storage:
            self.pattern_learner = PatternLearner(
                on_threshold_w=self.config.learning_on_threshold_w,
                off_threshold_w=self.config.learning_off_threshold_w,
                min_cycle_seconds=self.config.learning_min_cycle_seconds,
            )

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
                flush_debug_data=self._flush_debug_db,
                run_learning_now=self._run_learning_now,
                create_pattern_from_range=self._create_pattern_from_range,
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

        history = self.storage.get_recent_power_values(
            minutes=self.config.learning_warmup_minutes,
            limit=300,
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

    def _build_summary_payload(self) -> Dict:
        if not self.storage:
            return {
                "reading_count": 0,
                "avg_power_w": 0.0,
                "min_power_w": 0.0,
                "max_power_w": 0.0,
            }
        return self.storage.get_summary(hours=24)

    def _build_series_payload(self, limit: int) -> List[Dict]:
        if not self.storage:
            return []
        return self.storage.get_power_series(limit=limit)

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

    def _flush_debug_db(self, reset_patterns: bool = True) -> Dict:
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        return self.storage.flush_debug_data(reset_patterns=reset_patterns)

    def _run_learning_now(self) -> Dict:
        """Manual trigger for testing the nightly learning pass from Web UI."""
        if not self.storage:
            return {"ok": False, "error": "storage not enabled"}
        if not self.config.learning_enabled:
            return {"ok": False, "error": "learning is disabled"}

        result = self.storage.run_nightly_learning_pass(
            merge_tolerance=0.20,
            max_patterns=800,
        )
        if result.get("ok"):
            self.last_nightly_learning_date = datetime.now().date()
        return result

    def _maybe_run_nightly_learning(self, now: datetime) -> None:
        """Run lightweight learning maintenance once per night (off-peak window)."""
        if not self.storage or not self.config.learning_enabled:
            return

        # Run once per calendar day in an off-peak window.
        if now.hour < 2 or now.hour > 5:
            return
        if self.last_nightly_learning_date == now.date():
            return

        result = self.storage.run_nightly_learning_pass(
            merge_tolerance=0.20,
            max_patterns=800,
        )
        self.last_nightly_learning_date = now.date()
        logger.info(
            "Nightly learning pass completed: "
            f"ok={result.get('ok')} merged={result.get('merged', 0)} "
            f"patterns={result.get('patterns_considered', 0)}"
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

                if self.pattern_learner and self.storage:
                    cycle = self.pattern_learner.ingest(processed)
                    if cycle:
                        cycle_payload = {
                            "start_ts": cycle.start_ts.isoformat(),
                            "end_ts": cycle.end_ts.isoformat(),
                            "duration_s": cycle.duration_s,
                            "avg_power_w": cycle.avg_power_w,
                            "peak_power_w": cycle.peak_power_w,
                            "energy_wh": cycle.energy_wh,
                            "operating_modes": cycle.operating_modes,  # Multi-mode learning!
                            "has_multiple_modes": cycle.has_multiple_modes,
                            "active_phase_count": int(processed.metadata.get("phase_active_count", 1)),
                            "phase_mode": str(processed.metadata.get("phase_mode", "single_phase")),
                        }
                        heuristic_suggestion = self.pattern_learner.suggest_device_type(cycle)
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
                                "Pattern learned/updated: "
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

                time.sleep(self.config.update_interval_seconds)
            except Exception as e:
                logger.error(f"Main loop failure: {e}", exc_info=True)
                time.sleep(self.config.update_interval_seconds)

    def _signal_handler(self, sig, frame) -> None:
        logger.info(f"Signal {sig} received, shutting down")
        self.stop()

    def stop(self) -> None:
        self.running = False
        self.collector.disconnect()
        if self.publisher:
            self.publisher.disconnect()
        if self.web_server:
            self.web_server.stop()
        if self.storage:
            self.storage.close()
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
