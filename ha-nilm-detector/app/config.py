"""
Configuration management for NILM detection system.
"""
import json
import os
from typing import Dict, Any, Optional
from app.models import DeviceConfig
from app.utils.logging import get_logger


logger = get_logger(__name__)


class Config:
    """Application configuration."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to configuration file (JSON or dict)
        """
        self.debug = False
        self.update_interval_seconds = 5
        self.mqtt_broker = "localhost"
        self.mqtt_port = 1883
        self.mqtt_username = None
        self.mqtt_password = None
        self.mqtt_topic_prefix = "ha-nilm/"
        self.mqtt_discovery_prefix = "homeassistant"
        self.enable_mqtt_discovery = True
        self.devices: Dict[str, DeviceConfig] = {}
        self.ha_entity_id_prefix = "nilm"
        self.storage_path = "/data"
        self.processing_smoothing_window = 5
        self.processing_noise_threshold = 2.0
        self.processing_adaptive_correction = True
        self.confidence_threshold = 0.6
        
        if config_path:
            self.load(config_path)
    
    def load(self, config_path: str) -> None:
        """
        Load configuration from file.
        
        Args:
            config_path: Path to configuration file (JSON)
        """
        try:
            if isinstance(config_path, str) and config_path.endswith('.json'):
                with open(config_path, 'r') as f:
                    config_dict = json.load(f)
            else:
                config_dict = config_path if isinstance(config_path, dict) else {}
            
            self._apply_config(config_dict)
            logger.info(f"Configuration loaded: {len(self.devices)} devices configured")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _apply_config(self, config_dict: Dict[str, Any]) -> None:
        """Apply configuration dictionary."""
        # Global settings
        self.debug = config_dict.get('debug', False)
        self.update_interval_seconds = config_dict.get('update_interval_seconds', 5)
        self.storage_path = config_dict.get('storage_path', '/data')
        
        # MQTT settings
        mqtt_config = config_dict.get('mqtt', {})
        self.mqtt_broker = mqtt_config.get('broker', 'localhost')
        self.mqtt_port = mqtt_config.get('port', 1883)
        self.mqtt_username = mqtt_config.get('username')
        self.mqtt_password = mqtt_config.get('password')
        self.mqtt_topic_prefix = mqtt_config.get('topic_prefix', 'ha-nilm/')
        self.mqtt_discovery_prefix = mqtt_config.get('discovery_prefix', 'homeassistant')
        self.enable_mqtt_discovery = mqtt_config.get('discovery_enabled', True)
        
        # HA settings
        ha_config = config_dict.get('home_assistant', {})
        self.ha_entity_id_prefix = ha_config.get('entity_id_prefix', 'nilm')
        
        # Device configurations
        devices_config = config_dict.get('devices', {})
        for device_name, device_settings in devices_config.items():
            self.devices[device_name] = self._create_device_config(device_name, device_settings)
    
        # Processing controls
        processing_options = config_dict.get('processing', {})
        self.processing_smoothing_window = processing_options.get('smoothing_window', self.processing_smoothing_window)
        self.processing_noise_threshold = processing_options.get('noise_threshold', self.processing_noise_threshold)
        self.processing_adaptive_correction = processing_options.get('adaptive_correction', self.processing_adaptive_correction)

        # Confidence tuning
        confidence_options = config_dict.get('confidence', {})
        self.confidence_threshold = confidence_options.get('min_confidence', self.confidence_threshold)

    def _create_device_config(self, name: str, settings: Dict[str, Any]) -> DeviceConfig:
        """Create a DeviceConfig from settings dictionary."""
        return DeviceConfig(
            name=name,
            enabled=settings.get('enabled', True),
            power_min_w=float(settings.get('power_min_w', 10.0)),
            power_max_w=float(settings.get('power_max_w', 5000.0)),
            min_runtime_seconds=int(settings.get('min_runtime_seconds', 30)),
            min_pause_seconds=int(settings.get('min_pause_seconds', 60)),
            startup_spike_w=float(settings.get('startup_spike_w', 0.0)),
            startup_duration_seconds=int(settings.get('startup_duration_seconds', 5)),
            duty_cycle_threshold=float(settings.get('duty_cycle_threshold', 0.3)),
            metadata=settings.get('metadata', {}),
            detector_type=settings.get('detector_type', 'fridge'),
            confidence_threshold=float(settings.get('confidence_threshold', self.confidence_threshold)),
        )
    
    def get_device_config(self, device_name: str) -> Optional[DeviceConfig]:
        """Get configuration for a specific device."""
        return self.devices.get(device_name)
    
    def ensure_storage_path(self) -> None:
        """Ensure storage path exists."""
        os.makedirs(self.storage_path, exist_ok=True)


def load_options_from_file(options_path: str = "/data/options.json") -> Dict[str, Any]:
    """
    Load options from Home Assistant options file.
    
    Args:
        options_path: Path to options.json file
    
    Returns:
        Options dictionary
    """
    try:
        if os.path.exists(options_path):
            with open(options_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load options from {options_path}: {e}")
    
    return {}
