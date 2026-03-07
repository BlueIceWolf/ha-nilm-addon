"""
Configuration management for NILM detection system.
"""
import json
import os
from typing import Dict, Any, Optional, Union
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
        self.log_level = "info"
        self.update_interval_seconds = 5
        self.web_enabled = True
        self.web_port = 8099
        self.web_history_minutes = 180
        self.learning_enabled = True
        self.learning_on_threshold_w = 50.0
        self.learning_off_threshold_w = 25.0
        self.learning_min_cycle_seconds = 20
        self.power_source = "home_assistant_rest"
        self.mqtt_enabled = False
        self.mqtt_broker = "localhost"
        self.mqtt_port = 1883
        self.mqtt_username = None
        self.mqtt_password = None
        self.mqtt_topic_prefix = "ha-nilm/"
        self.mqtt_discovery_prefix = "homeassistant"
        self.enable_mqtt_discovery = True
        self.devices: Dict[str, DeviceConfig] = {}
        self.ha_entity_id_prefix = "nilm"
        self.ha_url = "http://supervisor/core/api"
        self.ha_phase_entities: Dict[str, str] = {}
        self.ha_token = ""
        self.storage_path = "/data"
        self.storage_enabled = True
        self.storage_db_path = "/data/nilm.sqlite3"
        self.storage_retention_days = 30
        self.learning_warmup_minutes = 120
        self.processing_smoothing_window = 5
        self.processing_noise_threshold = 2.0
        self.processing_adaptive_correction = True
        self.confidence_threshold = 0.6
        
        if config_path:
            self.load(config_path)
    
    def load(self, config_path: Union[str, Dict[str, Any]]) -> None:
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
        self.log_level = str(config_dict.get('log_level', self.log_level)).lower()
        self.update_interval_seconds = config_dict.get('update_interval_seconds', 5)

        web_config = config_dict.get('web', {})
        self.web_enabled = bool(web_config.get('enabled', self.web_enabled))
        self.web_port = int(web_config.get('port', self.web_port))
        self.web_history_minutes = int(web_config.get('history_minutes', self.web_history_minutes))

        learning_config = config_dict.get('learning', {})
        self.learning_enabled = bool(learning_config.get('enabled', self.learning_enabled))
        self.learning_on_threshold_w = float(
            learning_config.get('on_threshold_w', self.learning_on_threshold_w)
        )
        self.learning_off_threshold_w = float(
            learning_config.get('off_threshold_w', self.learning_off_threshold_w)
        )
        self.learning_min_cycle_seconds = int(
            learning_config.get('min_cycle_seconds', self.learning_min_cycle_seconds)
        )

        self.power_source = "home_assistant_rest"
        self.storage_path = config_dict.get('storage_path', '/data')
        
        # MQTT settings
        mqtt_config = config_dict.get('mqtt', {})
        self.mqtt_enabled = bool(mqtt_config.get('enabled', self.mqtt_enabled))
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
        self.ha_url = ha_config.get('url', self.ha_url)

        # Configure phase entities (L1, L2, L3)
        phase_entities_cfg = ha_config.get('phase_entities', {})
        self.ha_phase_entities = {}
        if isinstance(phase_entities_cfg, dict):
            for phase in ('L1', 'L2', 'L3'):
                value = str(phase_entities_cfg.get(phase.lower(), phase_entities_cfg.get(phase, ''))).strip()
                if value:
                    self.ha_phase_entities[phase] = value
        self.ha_token = ha_config.get('token', self.ha_token)

        storage_config = config_dict.get('storage', {})
        self.storage_enabled = bool(storage_config.get('enabled', self.storage_enabled))
        self.storage_db_path = str(storage_config.get('db_path', self.storage_db_path))
        self.storage_retention_days = int(storage_config.get('retention_days', self.storage_retention_days))
        self.learning_warmup_minutes = int(storage_config.get('learning_warmup_minutes', self.learning_warmup_minutes))
        
        # Device configurations
        devices_config = config_dict.get('devices', {})
        devices_json = config_dict.get('devices_json')
        if isinstance(devices_json, str) and devices_json.strip():
            try:
                parsed_devices = json.loads(devices_json)
                if isinstance(parsed_devices, dict):
                    devices_config = parsed_devices
                else:
                    logger.warning("devices_json was provided but is not a JSON object; ignoring it")
            except Exception as e:
                logger.error(f"Invalid devices_json in options: {e}")

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

        self._validate_config()

    def _validate_config(self) -> None:
        """Validate configuration consistency and required fields."""
        if not self.get_selected_phase_entities():
            raise ValueError(
                "At least one phase entity must be configured "
                "(home_assistant.phase_entities.l1/l2/l3 or sensor_entity_id)."
            )

    def get_selected_phase_entities(self) -> Dict[str, str]:
        """Return configured phase entity mapping in stable L1/L2/L3 order."""
        return {
            phase: entity
            for phase in ('L1', 'L2', 'L3')
            for entity in [self.ha_phase_entities.get(phase, '').strip()]
            if entity
        }

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
