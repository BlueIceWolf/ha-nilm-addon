"""
Main entry point for NILM detection system.
"""
import time
import signal
import sys
from datetime import datetime, timedelta
from app.utils.logging import setup_logging, get_logger
from app.config import Config, load_options_from_file
from app.state_engine import StateEngine
from app.collector.source import Collector, MockPowerSource
from app.detectors.fridge import FridgeDetector
from app.publishers.mqtt import MQTTPublisher


logger = get_logger(__name__)


class NILMDetectionSystem:
    """Main NILM detection system."""
    
    def __init__(self, config_path: str = "/data/options.json"):
        """
        Initialize NILM detection system.
        
        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        options = load_options_from_file(config_path)
        self.config = Config()
        self.config.load(options)
        
        # Setup logging
        setup_logging(debug=self.config.debug, name="NILM")
        logger.info("NILM Detection System starting...")
        logger.info(f"Debug mode: {self.config.debug}")
        
        # State engine
        self.state_engine = StateEngine()
        
        # Collector (using mock for MVP)
        # TODO: Replace with actual power source (HA REST, MQTT, etc.)
        mock_source = MockPowerSource()
        self.collector = Collector(mock_source)
        
        # Detectors
        self.detectors = {}
        self._setup_detectors()
        
        # Publisher
        self.publisher = MQTTPublisher(
            broker=self.config.mqtt_broker,
            port=self.config.mqtt_port,
            username=self.config.mqtt_username,
            password=self.config.mqtt_password,
            topic_prefix=self.config.mqtt_topic_prefix,
            discovery_prefix=self.config.mqtt_discovery_prefix,
            enable_discovery=self.config.enable_mqtt_discovery,
            entity_id_prefix=self.config.ha_entity_id_prefix
        )
        
        # State tracking
        self.last_daily_reset = datetime.now()
        self.running = False
    
    def _setup_detectors(self) -> None:
        """Setup device detectors."""
        for device_name, device_config in self.config.devices.items():
            if not device_config.enabled:
                logger.info(f"Skipping disabled device: {device_name}")
                continue
            
            logger.info(f"Setting up device: {device_name}")
            self.state_engine.register_device(device_name, device_config)
            
            # Create appropriate detector based on device type
            if "fridge" in device_name.lower():
                self.detectors[device_name] = FridgeDetector(device_config)
            else:
                logger.warning(f"Unknown device type for {device_name}")
    
    def start(self) -> None:
        """Start the detection system."""
        logger.info("Starting detection system...")
        
        # Connect collector
        if not self.collector.connect():
            logger.error("Failed to connect collector")
            return
        
        # Connect publisher
        if not self.publisher.connect():
            logger.warning("Failed to connect to MQTT (will retry)")
        
        self.running = True
        logger.info("Detection system running")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Main loop
        self._main_loop()
    
    def _main_loop(self) -> None:
        """Main detection loop."""
        iteration = 0
        
        while self.running:
            iteration += 1
            
            try:
                # Check for daily reset
                now = datetime.now()
                if (now - self.last_daily_reset).days > 0 or \
                   (now.date() != self.last_daily_reset.date()):
                    self._reset_daily_stats()
                    self.last_daily_reset = now
                
                # Read power data
                reading = self.collector.read()
                if not reading:
                    time.sleep(0.1)
                    continue
                
                # Run detectors
                for device_name, detector in self.detectors.items():
                    detected_state = detector.detect(reading)
                    
                    if detected_state:
                        # Update state engine
                        device_details = detector.get_cycle_info()
                        device_state = self.state_engine.update_device_state(
                            device_name,
                            detected_state,
                            reading.power_w,
                            device_details
                        )
                        
                        # Publish state
                        if device_state and self.publisher.is_connected():
                            self.publisher.publish_state(device_state)
                
                # Log periodically
                if iteration % 100 == 0:
                    logger.debug(f"Main loop iteration {iteration} - systems operational")
                
                time.sleep(self.config.update_interval_seconds)
            
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(self.config.update_interval_seconds)
    
    def _reset_daily_stats(self) -> None:
        """Reset daily statistics."""
        logger.info("Resetting daily statistics")
        self.state_engine.reset_all_daily_counters()
    
    def _signal_handler(self, sig, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {sig}, shutting down...")
        self.stop()
    
    def stop(self) -> None:
        """Stop the detection system."""
        logger.info("Stopping detection system...")
        self.running = False
        
        try:
            self.collector.disconnect()
            self.publisher.disconnect()
            logger.info("Detection system stopped")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error stopping system: {e}")
            sys.exit(1)


def main():
    """Entry point."""
    try:
        system = NILMDetectionSystem()
        system.start()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
