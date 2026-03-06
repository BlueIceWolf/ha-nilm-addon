"""Entry point wiring together the modular NILM detection stack."""
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List

from app.collector.source import Collector, MockPowerSource
from app.config import Config, load_options_from_file
from app.confidence.confidence import ConfidenceEvaluator
from app.detectors import AdaptiveLoadDetector, FridgeDetector, InverterDeviceDetector
from app.processing.pipeline import ProcessingPipeline
from app.publishers.mqtt import MQTTPublisher
from app.state_engine import StateEngine
from app.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


class NILMDetectionSystem:
    """Coordinates collectors, detectors, confidence takers and publishers."""

    def __init__(self, config_path: str = "/data/options.json"):
        options = load_options_from_file(config_path)
        self.config = Config()
        self.config.load(options)

        setup_logging(debug=self.config.debug, name="NILM")
        logger.info("Starting NILM Detection System...")

        self.state_engine = StateEngine()
        self.collector = Collector(MockPowerSource())
        self.processing_pipeline = ProcessingPipeline(
            smoothing_window=self.config.processing_smoothing_window,
            noise_threshold=self.config.processing_noise_threshold,
            adaptive_correction=self.config.processing_adaptive_correction,
        )

        self.confidence_evaluator = ConfidenceEvaluator(
            min_confidence=self.config.confidence_threshold
        )

        self.detectors: Dict[str, List] = {}
        self._setup_detectors()

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

    def start(self) -> None:
        if not self.collector.connect():
            logger.error("Collector failed to connect")
            return

        if not self.publisher.connect():
            logger.warning("MQTT connect failed; continuing without publisher")

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
                    time.sleep(0.1)
                    continue

                processed = self.processing_pipeline.process(reading)
                for device_name, detector_group in self.detectors.items():
                    detection_candidates = []
                    for detector in detector_group:
                        result = detector.detect(processed)
                        if result:
                            detection_candidates.append(result)

                    best = self.confidence_evaluator.evaluate(
                        detection_candidates,
                        self.config.devices[device_name],
                    )

                    if not best:
                        continue

                    device_state = self.state_engine.update_device_state(best)
                    if device_state and self.publisher.is_connected():
                        self.publisher.publish_state(device_state)

                if iteration % 100 == 0:
                    logger.debug(f"Main loop alive (iteration {iteration})")

                now = datetime.now()
                if (now - self.last_daily_reset).days > 0 or now.date() != self.last_daily_reset.date():
                    self.state_engine.reset_all_daily_counters()
                    self.last_daily_reset = now

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
        self.publisher.disconnect()
        logger.info("Detection system stopped")
        sys.exit(0)


def main() -> None:
    try:
        system = NILMDetectionSystem()
        system.start()
    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
