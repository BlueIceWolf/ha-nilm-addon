"""
Configuration management for NILM detection system.
"""
import json
import os
import shutil
from typing import Dict, Any, Optional, Union
from app.models import DeviceConfig
from app.utils.logging import get_logger


logger = get_logger(__name__)


PRIMARY_STORAGE_PATH = "/data/ha_nilm_detector"
LEGACY_STORAGE_PATHS = [
    "/addon_configs/ha_nilm_detector",
]
DEFAULT_STORAGE_BASE = PRIMARY_STORAGE_PATH
LEGACY_STORAGE_BASE = LEGACY_STORAGE_PATHS[0]


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
        self.language = "de"
        self.learning_enabled = True
        self.learning_on_threshold_w = 50.0
        self.learning_off_threshold_w = 25.0
        self.learning_min_cycle_seconds = 20
        self.learning_delta_on_w = 30.0
        self.learning_delta_off_w = 12.0
        self.learning_max_gap_s = 6.0
        self.learning_baseline_window_s = 5.0
        self.learning_end_hold_s = 6.0
        self.learning_derivative_threshold_w_per_s = 120.0
        self.learning_stabilization_grace_s = 12.0
        self.learning_pre_roll_s = 3.0
        self.learning_post_roll_s = 24.0
        self.learning_ring_buffer_s = 10.0
        self.learning_min_samples_for_learning = 4
        self.learning_min_waveform_score_for_provisional = 0.20
        self.learning_min_waveform_score_for_final = 0.45
        self.learning_merge_similarity_threshold = 0.86
        self.learning_start_slope_threshold_w_per_s = 90.0
        self.ai_enabled = True
        self.ml_enabled = True
        self.shape_matching_enabled = True
        self.online_learning_enabled = True
        self.pattern_match_threshold = 0.45
        self.ml_confidence_threshold = 0.60
        self.learning_segmentation_threshold = 0.40
        self.learning_stable_segmentation_threshold = 0.70
        self.learning_provisional_promotion_count = 3
        self.learning_starvation_window = 8
        self.learning_auto_pipeline_enabled = True
        self.learning_auto_pipeline_interval_minutes = 30
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
        self.storage_path = DEFAULT_STORAGE_BASE
        self.storage_enabled = True
        self.storage_db_path = f"{DEFAULT_STORAGE_BASE}/nilm_live.sqlite3"
        self.storage_patterns_db_path = f"{DEFAULT_STORAGE_BASE}/nilm_patterns.sqlite3"
        self.storage_retention_days = 30
        self.learning_warmup_minutes = 120
        self.processing_smoothing_window = 5
        self.processing_noise_threshold = 2.0
        self.processing_adaptive_correction = True
        self.confidence_threshold = 0.6
        self.log_file = f"{DEFAULT_STORAGE_BASE}/nilm.log"  # Log file path (rotated on startup)
        self.max_log_backups = 3  # Keep max 3 old log files (.log.1, .log.2, .log.3)
        
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
        self.log_file = str(config_dict.get('log_file', self.log_file))
        self.max_log_backups = int(config_dict.get('max_log_backups', self.max_log_backups))
        self.update_interval_seconds = config_dict.get('update_interval_seconds', 5)

        web_config = config_dict.get('web', {})
        self.web_enabled = bool(web_config.get('enabled', self.web_enabled))
        self.web_port = int(web_config.get('port', self.web_port))
        self.web_history_minutes = int(web_config.get('history_minutes', self.web_history_minutes))
        configured_language = str(config_dict.get('language', self.language)).strip().lower()
        self.language = configured_language if configured_language in ('de', 'en') else 'de'

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
        self.learning_delta_on_w = float(
            learning_config.get(
                'start_threshold_w',
                learning_config.get('delta_threshold', learning_config.get('delta_on_w', self.learning_delta_on_w)),
            )
        )
        self.learning_delta_off_w = float(
            learning_config.get('end_threshold_w', learning_config.get('delta_off_w', self.learning_delta_off_w))
        )
        self.learning_max_gap_s = float(
            learning_config.get('max_gap_s', self.learning_max_gap_s)
        )
        self.learning_baseline_window_s = float(
            learning_config.get('baseline_window_s', self.learning_baseline_window_s)
        )
        self.learning_end_hold_s = float(
            learning_config.get('hold_time_s', learning_config.get('end_hold_s', self.learning_end_hold_s))
        )
        self.learning_derivative_threshold_w_per_s = float(
            learning_config.get(
                'derivative_threshold_w_per_s',
                self.learning_derivative_threshold_w_per_s,
            )
        )
        self.learning_stabilization_grace_s = float(
            learning_config.get('stabilization_grace_s', self.learning_stabilization_grace_s)
        )
        self.learning_pre_roll_s = float(
            learning_config.get('pre_roll_s', self.learning_pre_roll_s)
        )
        self.learning_post_roll_s = float(
            learning_config.get('post_roll_s', self.learning_post_roll_s)
        )
        self.learning_ring_buffer_s = float(
            learning_config.get('ring_buffer_seconds', self.learning_ring_buffer_s)
        )
        self.learning_min_samples_for_learning = int(
            learning_config.get('min_samples_for_learning', self.learning_min_samples_for_learning)
        )
        self.learning_min_waveform_score_for_provisional = float(
            learning_config.get('min_waveform_score_for_provisional', self.learning_min_waveform_score_for_provisional)
        )
        self.learning_min_waveform_score_for_final = float(
            learning_config.get('min_waveform_score_for_final', self.learning_min_waveform_score_for_final)
        )
        self.learning_merge_similarity_threshold = float(
            learning_config.get('merge_similarity_threshold', self.learning_merge_similarity_threshold)
        )
        self.learning_start_slope_threshold_w_per_s = float(
            learning_config.get('slope_threshold', self.learning_start_slope_threshold_w_per_s)
        )
        self.ai_enabled = bool(learning_config.get('ai_enabled', self.ai_enabled))
        self.ml_enabled = bool(learning_config.get('ml_enabled', self.ml_enabled))
        self.shape_matching_enabled = bool(
            learning_config.get('shape_matching_enabled', self.shape_matching_enabled)
        )
        self.online_learning_enabled = bool(
            learning_config.get('online_learning_enabled', self.online_learning_enabled)
        )
        self.pattern_match_threshold = float(
            learning_config.get('pattern_match_threshold', self.pattern_match_threshold)
        )
        self.ml_confidence_threshold = float(
            learning_config.get('ml_confidence_threshold', self.ml_confidence_threshold)
        )
        self.learning_segmentation_threshold = float(
            learning_config.get('segmentation_threshold', self.learning_segmentation_threshold)
        )
        self.learning_stable_segmentation_threshold = float(
            learning_config.get('stable_segmentation_threshold', self.learning_stable_segmentation_threshold)
        )
        self.learning_provisional_promotion_count = int(
            learning_config.get('provisional_promotion_count', self.learning_provisional_promotion_count)
        )
        self.learning_starvation_window = int(
            learning_config.get('learning_starvation_window', self.learning_starvation_window)
        )
        self.learning_auto_pipeline_enabled = bool(
            learning_config.get('auto_pipeline_enabled', self.learning_auto_pipeline_enabled)
        )
        self.learning_auto_pipeline_interval_minutes = int(
            learning_config.get(
                'auto_pipeline_interval_minutes',
                self.learning_auto_pipeline_interval_minutes,
            )
        )
        if self.learning_auto_pipeline_interval_minutes < 5:
            self.learning_auto_pipeline_interval_minutes = 5
        self.learning_segmentation_threshold = max(0.10, min(self.learning_segmentation_threshold, 0.95))
        self.learning_stable_segmentation_threshold = max(
            self.learning_segmentation_threshold,
            min(self.learning_stable_segmentation_threshold, 0.99),
        )
        self.learning_min_waveform_score_for_provisional = max(0.05, min(self.learning_min_waveform_score_for_provisional, 0.95))
        self.learning_min_waveform_score_for_final = max(
            self.learning_min_waveform_score_for_provisional,
            min(self.learning_min_waveform_score_for_final, 0.99),
        )
        self.learning_provisional_promotion_count = max(2, min(self.learning_provisional_promotion_count, 10))
        self.learning_starvation_window = max(3, min(self.learning_starvation_window, 50))
        self.learning_ring_buffer_s = max(5.0, min(self.learning_ring_buffer_s, 30.0))
        self.learning_min_samples_for_learning = max(4, min(self.learning_min_samples_for_learning, 120))
        self.learning_merge_similarity_threshold = max(0.60, min(self.learning_merge_similarity_threshold, 0.99))
        self.learning_start_slope_threshold_w_per_s = max(5.0, min(self.learning_start_slope_threshold_w_per_s, 5000.0))

        self.power_source = "home_assistant_rest"
        self.storage_path = str(config_dict.get('storage_path', self.storage_path)).strip() or self.storage_path
        
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
        storage_base_path = str(
            storage_config.get('base_path', self.storage_path)
        ).strip()
        if storage_base_path:
            self.storage_path = storage_base_path

        default_live_db = os.path.join(self.storage_path, "nilm_live.sqlite3")
        default_patterns_db = os.path.join(self.storage_path, "nilm_patterns.sqlite3")
        self.storage_db_path = str(storage_config.get('db_path', default_live_db)).strip() or default_live_db
        self.storage_patterns_db_path = str(
            storage_config.get('patterns_db_path', default_patterns_db)
        ).strip() or default_patterns_db

        # Keep log file colocated with storage by default unless explicitly configured.
        configured_log_file = str(config_dict.get('log_file', '')).strip()
        if configured_log_file:
            self.log_file = configured_log_file
        else:
            self.log_file = os.path.join(self.storage_path, "nilm.log")
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
        """Ensure configured storage directories exist."""
        logger.info("Using primary storage path: %s", self.storage_path)
        logger.info("Checking legacy storage paths: %s", ", ".join(LEGACY_STORAGE_PATHS))
        os.makedirs(self.storage_path, exist_ok=True)
        # Compatibility: keep legacy addon config folder available for users/tools.
        for legacy_path in LEGACY_STORAGE_PATHS:
            try:
                os.makedirs(legacy_path, exist_ok=True)
            except Exception as legacy_dir_error:
                logger.debug("Legacy directory not available (%s): %s", legacy_path, legacy_dir_error)
        self._migrate_legacy_storage_files()
        for db_path in [self.storage_db_path, self.storage_patterns_db_path]:
            db_dir = os.path.dirname(str(db_path or "").strip())
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

    def _migrate_legacy_storage_files(self) -> None:
        """Migrate known previous storage locations into current target paths when needed."""
        storage_base_candidates = [
            "/data",
            LEGACY_STORAGE_BASE,
            DEFAULT_STORAGE_BASE,
        ]

        migration_sources = {
            self.storage_db_path: [
                "/data/nilm_live.sqlite3",
                f"{LEGACY_STORAGE_BASE}/nilm_live.sqlite3",
                f"{DEFAULT_STORAGE_BASE}/nilm_live.sqlite3",
            ],
            self.storage_patterns_db_path: [
                "/data/nilm_patterns.sqlite3",
                f"{LEGACY_STORAGE_BASE}/nilm_patterns.sqlite3",
                f"{DEFAULT_STORAGE_BASE}/nilm_patterns.sqlite3",
            ],
            self.log_file: [
                "/data/nilm.log",
                f"{LEGACY_STORAGE_BASE}/nilm.log",
                f"{DEFAULT_STORAGE_BASE}/nilm.log",
            ],
        }

        for base in storage_base_candidates:
            migration_sources[self.storage_db_path].append(f"{base}/ha_nilm_detector/nilm_live.sqlite3")
            migration_sources[self.storage_patterns_db_path].append(f"{base}/ha_nilm_detector/nilm_patterns.sqlite3")
            migration_sources[self.log_file].append(f"{base}/ha_nilm_detector/nilm.log")

        def _target_is_missing_or_empty(path: str) -> bool:
            if not os.path.exists(path):
                return True
            try:
                return os.path.getsize(path) <= 0
            except OSError:
                return False

        for target_path, source_candidates in migration_sources.items():
            target = str(target_path or "").strip()
            if not target or not _target_is_missing_or_empty(target):
                continue

            for source_path in source_candidates:
                source = str(source_path or "").strip()
                if not source:
                    continue
                if os.path.abspath(source) == os.path.abspath(target):
                    continue
                if not os.path.exists(source):
                    continue

                try:
                    target_dir = os.path.dirname(target)
                    if target_dir:
                        os.makedirs(target_dir, exist_ok=True)

                    shutil.copy2(source, target)
                    for suffix in ("-wal", "-shm"):
                        source_sidecar = f"{source}{suffix}"
                        target_sidecar = f"{target}{suffix}"
                        if os.path.exists(source_sidecar) and not os.path.exists(target_sidecar):
                            shutil.copy2(source_sidecar, target_sidecar)

                    logger.info(f"Migrated storage file: {source} -> {target}")
                    break
                except Exception as migration_error:
                    logger.warning(
                        "Storage migration failed for %s -> %s: %s",
                        source,
                        target,
                        migration_error,
                    )


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
