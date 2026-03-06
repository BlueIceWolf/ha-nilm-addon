"""
MQTT publisher for Home Assistant integration with MQTT Discovery.
"""
import json
from typing import Optional, Dict, Any
import paho.mqtt.client as mqtt
from app.models import DeviceState
from app.utils.logging import get_logger


logger = get_logger(__name__)


class MQTTPublisher:
    """Publishes device states to MQTT with Home Assistant Discovery support."""
    
    def __init__(
        self,
        broker: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: str = "ha-nilm/",
        discovery_prefix: str = "homeassistant",
        enable_discovery: bool = True,
        entity_id_prefix: str = "nilm"
    ):
        """
        Initialize MQTT publisher.
        
        Args:
            broker: MQTT broker address
            port: MQTT broker port
            username: MQTT username (optional)
            password: MQTT password (optional)
            topic_prefix: Base topic prefix for state publishing
            discovery_prefix: MQTT Discovery prefix
            enable_discovery: Enable MQTT Discovery
            entity_id_prefix: Home Assistant entity ID prefix
        """
        self.broker = broker
        self.port = port
        self.topic_prefix = topic_prefix
        self.discovery_prefix = discovery_prefix
        self.enable_discovery = enable_discovery
        self.entity_id_prefix = entity_id_prefix
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self.client.username_pw_set(username, password) if username else None
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        self._connected = False
        self._published_devices: set = set()
    
    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            logger.info(f"Connecting to MQTT broker {self.broker}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Disconnected from MQTT broker")
        except Exception as e:
            logger.error(f"Error disconnecting from MQTT broker: {e}")
    
    def publish_state(self, device_state: DeviceState) -> None:
        """
        Publish device state and related metrics.
        
        Args:
            device_state: Device state to publish
        """
        if not self._connected:
            logger.warning(f"Not connected to MQTT, cannot publish {device_state.device_name}")
            return
        
        device_name = device_state.device_name
        
        # Publish discovery if first time
        if self.enable_discovery and device_name not in self._published_devices:
            self._publish_discovery(device_name, device_state)
            self._published_devices.add(device_name)
        
        # Publish binary sensor (on/off state)
        state_topic = f"{self.topic_prefix}{device_name}/state"
        state_payload = "ON" if device_state.state == DeviceState.ON else "OFF"
        self.client.publish(state_topic, state_payload, retain=True)
        
        # Publish power
        power_topic = f"{self.topic_prefix}{device_name}/power"
        power_payload = f"{device_state.power_w:.1f}"
        self.client.publish(power_topic, power_payload, retain=True)
        
        # Publish last start
        if device_state.last_start:
            start_topic = f"{self.topic_prefix}{device_name}/last_start"
            self.client.publish(start_topic, device_state.last_start.isoformat(), retain=True)
        
        # Publish runtime
        runtime_topic = f"{self.topic_prefix}{device_name}/runtime"
        runtime_payload = f"{device_state.runtime_seconds:.1f}"
        self.client.publish(runtime_topic, runtime_payload, retain=True)
        
        # Publish daily statistics
        daily_runtime_topic = f"{self.topic_prefix}{device_name}/daily_runtime"
        daily_runtime_payload = f"{device_state.daily_runtime_seconds:.1f}"
        self.client.publish(daily_runtime_topic, daily_runtime_payload, retain=True)
        
        daily_cycles_topic = f"{self.topic_prefix}{device_name}/daily_cycles"
        daily_cycles_payload = str(device_state.daily_cycles)
        self.client.publish(daily_cycles_topic, daily_cycles_payload, retain=True)
        
        logger.debug(f"Published state for {device_name}: {state_payload}")
    
    def _publish_discovery(self, device_name: str, device_state: DeviceState) -> None:
        """
        Publish MQTT Discovery configuration for Home Assistant.
        
        Args:
            device_name: Device name
            device_state: Device state (for discovery payload)
        """
        # Binary Sensor - On/Off state
        discovery_topic = f"{self.discovery_prefix}/binary_sensor/{self.entity_id_prefix}_{device_name}_state/config"
        discovery_payload = {
            "name": f"{device_name} State",
            "unique_id": f"{self.entity_id_prefix}_{device_name}_state",
            "state_topic": f"{self.topic_prefix}{device_name}/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "power",
            "device": {
                "identifiers": [f"{self.entity_id_prefix}_{device_name}"],
                "name": device_name,
                "manufacturer": "HA-NILM",
                "model": "NILM Detector"
            }
        }
        self.client.publish(
            discovery_topic,
            json.dumps(discovery_payload),
            retain=True
        )
        
        # Sensor - Power
        power_discovery_topic = f"{self.discovery_prefix}/sensor/{self.entity_id_prefix}_{device_name}_power/config"
        power_payload = {
            "name": f"{device_name} Power",
            "unique_id": f"{self.entity_id_prefix}_{device_name}_power",
            "state_topic": f"{self.topic_prefix}{device_name}/power",
            "unit_of_measurement": "W",
            "device_class": "power",
            "device": {
                "identifiers": [f"{self.entity_id_prefix}_{device_name}"],
                "name": device_name
            }
        }
        self.client.publish(
            power_discovery_topic,
            json.dumps(power_payload),
            retain=True
        )
        
        # Sensor - Daily Runtime
        runtime_discovery_topic = f"{self.discovery_prefix}/sensor/{self.entity_id_prefix}_{device_name}_daily_runtime/config"
        runtime_payload = {
            "name": f"{device_name} Daily Runtime",
            "unique_id": f"{self.entity_id_prefix}_{device_name}_daily_runtime",
            "state_topic": f"{self.topic_prefix}{device_name}/daily_runtime",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "device": {
                "identifiers": [f"{self.entity_id_prefix}_{device_name}"],
                "name": device_name
            }
        }
        self.client.publish(
            runtime_discovery_topic,
            json.dumps(runtime_payload),
            retain=True
        )
        
        # Sensor - Daily Cycles
        cycles_discovery_topic = f"{self.discovery_prefix}/sensor/{self.entity_id_prefix}_{device_name}_daily_cycles/config"
        cycles_payload = {
            "name": f"{device_name} Daily Cycles",
            "unique_id": f"{self.entity_id_prefix}_{device_name}_daily_cycles",
            "state_topic": f"{self.topic_prefix}{device_name}/daily_cycles",
            "device_class": "frequency",
            "device": {
                "identifiers": [f"{self.entity_id_prefix}_{device_name}"],
                "name": device_name
            }
        }
        self.client.publish(
            cycles_discovery_topic,
            json.dumps(cycles_payload),
            retain=True
        )
        
        logger.info(f"Published MQTT Discovery for {device_name}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback."""
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected successfully")
        else:
            logger.error(f"MQTT connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback."""
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection with code {rc}")
    
    def _on_message(self, client, userdata, msg):
        """MQTT message callback."""
        logger.debug(f"MQTT message received on {msg.topic}: {msg.payload}")
    
    def is_connected(self) -> bool:
        """Check if connected to MQTT broker."""
        return self._connected
