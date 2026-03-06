# HA NILM Detector – Detaillierte Dokumentation

Vollständige technische Dokumentation für Entwickler und fortgeschrittene Benutzer.

## Inhaltsverzeichnis

1. [Systemarchitektur](#systemarchitektur)
2. [Modul-Referenz](#modul-referenz)
3. [Datenmodelle](#datenmodelle)
4. [Erweiterung für neue Geräte](#erweiterung-für-neue-geräte)
5. [MQTT Protokoll](#mqtt-protokoll)
6. [Entwicklung & Testing](#entwicklung--testing)

---

## Systemarchitektur

### Komponenten-Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                      NILMDetectionSystem                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         │
│  │  Collector   │───→   Detectors  │───→ StateEngine │         │
│  │  (Source)    │   (FridgeDetect) │   (State Mgmt) │         │
│  └──────────────┘   └──────────────┘   └──────────────┘         │
│         │                    │                 │                │
│         │                    │                 ▼                │
│         │                    │           ┌──────────────────┐   │
│         │                    │           │ MQTTPublisher    │   │
│         │                    │           │ (Home Assistant) │   │
│         │                    │           └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
    ┌────────┐          ┌──────────┐
    │ Power  │          │ Detection│
    │ Source │          │ Results  │
    └────────┘          └──────────┘
         │                    │
         ▼                    ▼
    Home Assis-          MQTT Broker
    tant/Daten-          (HA MQTT)
    quelle
```

### Datenfluss

1. **Erfassung (Collector)**
   - Liest kontinuierlich Leistungswerte
   - Puffert Lesevorgänge für Analyse
   
2. **Erkennung (Detectors)**
   - Analysiert Lesevorgänge
   - Liefert Erkennungsergebnisse: State + Power
   
3. **Zustandsverwaltung (StateEngine)**
   - Wendet Zustandsmaschine mit Hysterese an
   - Verwaltet Timer und tägliche Zähler
   
4. **Veröffentlichung (MQTTPublisher)**
   - Sendet Status an Home Assistant
   - Publiziert MQTT Discovery Messages beim Start

---

## Modul-Referenz

### 1. `app/models.py` – Datenklassen

```python
class PowerReading:
    """Raw power measurement."""
    timestamp: datetime          # When was this measured
    power_w: float              # Power in watts
    phase: str                  # Phase (L1, L2, L3)
    metadata: Dict[str, Any]    # Additional info

class DeviceState(Enum):
    """Device operational states."""
    OFF = "off"                 # Device is off
    STARTING = "starting"       # Startup phase is being detected
    ON = "on"                   # Device is running
    STOPPING = "stopping"       # Device is stopping

class DeviceConfig:
    """Device detector configuration."""
    name: str                   # Device name
    enabled: bool               # Is detector active?
    power_min_w: float         # Turn-on threshold
    power_max_w: float         # Maximum allowed power
    min_runtime_seconds: int   # Minimum on-time per cycle
    min_pause_seconds: int     # Minimum off-time between cycles
    startup_spike_w: float     # Expected startup spike (reserved)
    startup_duration_seconds: int  # Startup phase duration
    duty_cycle_threshold: float    # Reserved for future use

class DeviceState_:
    """Current device state information."""
    device_name: str           # Which device
    state: DeviceState         # Current state
    power_w: float            # Current power
    last_start: Optional[datetime]  # When did current cycle start?
    runtime_seconds: float     # Duration of last cycle
    daily_cycles: int         # How many cycles today?
    daily_runtime_seconds: float    # Total runtime today
    last_update: Optional[datetime] # When was this last updated?

class DetectionResult:
    """Result from detector."""
    device_name: str           # Which device
    timestamp: datetime        # When was this detected
    state: DeviceState        # Detected state
    power_w: float            # Detected power
    confidence: float         # Confidence (0–1)
    details: Dict[str, Any]   # Additional detection details
```

### 2. `app/config.py` – Konfigurationsverwaltung

```python
class Config:
    """Application configuration wrapper."""
    
    # Global settings
    debug: bool                    # Enable debug logging
    update_interval_seconds: int   # Polling interval
    mqtt_broker: str              # MQTT broker address
    mqtt_port: int                # MQTT port
    mqtt_username: Optional[str]  # MQTT auth
    mqtt_password: Optional[str]
    mqtt_topic_prefix: str        # Base topic for state publishing
    mqtt_discovery_prefix: str    # MQTT Discovery prefix
    enable_mqtt_discovery: bool   # Enable/disable discovery
    ha_entity_id_prefix: str      # Entity ID prefix in HA
    storage_path: str             # Data storage path
    devices: Dict[str, DeviceConfig]  # Device configurations
    
    def load(config_path: str) -> None:
        """Load from JSON file or dict."""
    def get_device_config(name: str) -> DeviceConfig:
        """Get specific device config."""
    def ensure_storage_path() -> None:
        """Ensure storage directory exists."""
```

### 3. `app/state_engine.py` – Zustandsverwaltung

```python
class StateEngine:
    """Manages device states with state machine logic."""
    
    def register_device(name: str, config: DeviceConfig) -> None:
        """Register a new device for tracking."""
    
    def update_device_state(
        device_name: str,
        state: DeviceState,
        power_w: float,
        detection_result: Optional[Dict] = None
    ) -> DeviceState_:
        """Update device state with hysteresis logic."""
    
    def get_device_state(name: str) -> Optional[DeviceState_]:
        """Get current state of device."""
    
    def reset_daily_counters(name: str) -> None:
        """Reset daily cycles/runtime for device."""
```

**Zustandsübergänge:**

```
OFF ──[Power > min_w]──→ STARTING
              │
              └──[Power > min_w, duration > startup_duration]──→ ON
                   (oder bei zu kurzer Anschaltung → OFF)

ON ──[Power < min_w]──→ OFF (if runtime >= min_runtime)
   │
   └──[Power < min_w, runtime < min_runtime]──→ ON (hysteresis)

STARTING ──[Power drops immediately]──→ OFF
       │
       └──[Timeout or power stays]──→ ON
```

### 4. `app/collector/source.py` – Datenquellenabstraktion

```python
class PowerSource(ABC):
    """Abstract base for power data sources."""
    def connect() -> bool:
        """Connect to power source."""
    def disconnect() -> None:
        """Disconnect."""
    def read_power() -> Optional[PowerReading]:
        """Read single power value."""

class MockPowerSource(PowerSource):
    """Simulated power source for testing."""
    def set_power(power_w: float) -> None:
        """Set simulated power (for testing)."""

class HARestPowerSource(PowerSource):
    """Read from Home Assistant REST API."""
    # (Planned for later implementation)

class Collector:
    """Buffered reading collection."""
    def read() -> Optional[PowerReading]:
        """Read and buffer power data."""
    def get_readings_since(minutes: int) -> List[PowerReading]:
        """Get readings from last N minutes."""
```

### 5. `app/detectors/fridge.py` – Kühlschrank-Detektor

```python
class FridgeDetector:
    """Pattern-based refrigerator detector."""
    
    def detect(reading: PowerReading) -> Optional[DeviceState]:
        """Detect fridge state from power reading."""
        # Returns one of: OFF, STARTING, ON, None (uncertain)
    
    def get_power_stats(window_seconds: int = 60) -> Dict:
        """Get min/max/avg/variance of power in time window."""
    
    def get_cycle_info() -> Dict:
        """Get current cycle information."""
```

**Erkennungslogik:**

1. **OFF → STARTING**: `power > power_min_w` (Einschaltung erkannt)
2. **STARTING → ON**: `duration > startup_duration_seconds` (stabilisiert)
3. **ON → OFF**: `power < power_min_w AND runtime >= min_runtime` (Ausschaltung)
4. **ON → ON** (hysteresis): Wenn runtime zu kurz, bleibe ON

### 6. `app/publishers/mqtt.py` – MQTT Publisher

```python
class MQTTPublisher:
    """MQTT state publisher with MQTT Discovery support."""
    
    def connect() -> bool:
        """Connect to MQTT broker."""
    
    def disconnect() -> None:
        """Disconnect."""
    
    def publish_state(device_state: DeviceState_) -> None:
        """Publish device state to MQTT."""
        # Publishes to:
        # - Binary sensor (state)
        # - Power sensor
        # - Daily runtime / cycles
        # - Last start timestamp
    
    def is_connected() -> bool:
        """Check connection status."""
```

**Publizierte Topics:**

```
ha-nilm/{device_name}/state          # "ON" oder "OFF"
ha-nilm/{device_name}/power          # Power in Watt
ha-nilm/{device_name}/daily_runtime  # Runtime in Sekunden
ha-nilm/{device_name}/daily_cycles   # Anzahl Zyklen
ha-nilm/{device_name}/last_start     # ISO-8601 Timestamp

# MQTT Discovery (auf startup)
homeassistant/binary_sensor/nilm_{device}_state/config
homeassistant/sensor/nilm_{device}_power/config
homeassistant/sensor/nilm_{device}_daily_runtime/config
homeassistant/sensor/nilm_{device}_daily_cycles/config
```

### 7. `app/main.py` – Hauptanwendung

```python
class NILMDetectionSystem:
    """Main application orchestrator."""
    
    def __init__(config_path: str = "/data/options.json"):
        # Initialize all components
    
    def start() -> None:
        # Start main loop
    
    def stop() -> None:
        # Graceful shutdown
    
    def _main_loop() -> None:
        # Read → Detect → Update State → Publish
```

---

## Datenmodelle

### Konfigurationsbasis-Format

```json
{
  "debug": false,
  "update_interval_seconds": 5,
  "mqtt": {
    "broker": "homeassistant.local",
    "port": 1883,
    "username": "mqtt_user",
    "password": "mqtt_pass",
    "topic_prefix": "ha-nilm/",
    "discovery_prefix": "homeassistant",
    "discovery_enabled": true
  },
  "home_assistant": {
    "entity_id_prefix": "nilm"
  },
  "devices": {
    "kitchen_fridge": {
      "enabled": true,
      "power_min_w": 10,
      "power_max_w": 500,
      "min_runtime_seconds": 30,
      "min_pause_seconds": 60,
      "startup_duration_seconds": 5
    }
  }
}
```

---

## Erweiterung für neue Geräte

### Schritt 1: Neuen Detektor erstellen

Erstelle eine neue Datei `app/detectors/waschmaschine.py`:

```python
from app.models import DeviceState, PowerReading, DeviceConfig
from app.utils.logging import get_logger

logger = get_logger(__name__)

class WashingMachineDetector:
    """Detects washing machine operation."""
    
    def __init__(self, config: DeviceConfig):
        self.config = config
        self.name = config.name
        self.current_state = DeviceState.OFF
        # Your detection logic here
    
    def detect(self, reading: PowerReading) -> Optional[DeviceState]:
        """Detect washing machine state."""
        power_w = reading.power_w
        
        # Implement your detection logic
        # Return: DeviceState.OFF, .STARTING, .ON, or None
        
        return self.current_state
```

### Schritt 2: Detektor in main.py registrieren

In `app/main.py`, änder die `_setup_detectors()` Methode:

```python
def _setup_detectors(self) -> None:
    """Setup device detectors."""
    for device_name, device_config in self.config.devices.items():
        if not device_config.enabled:
            continue
        
        logger.info(f"Setting up device: {device_name}")
        self.state_engine.register_device(device_name, device_config)
        
        # Hier: Weitere Geräte hinzufügen
        if "fridge" in device_name.lower():
            self.detectors[device_name] = FridgeDetector(device_config)
        elif "washing" in device_name.lower():
            from app.detectors.waschmaschine import WashingMachineDetector
            self.detectors[device_name] = WashingMachineDetector(device_config)
        else:
            logger.warning(f"Unknown device type for {device_name}")
```

### Schritt 3: Konfiguration in config.yaml ergänzen

```yaml
devices:
  kitchen_fridge:
    # ... existing config
  laundry_washing_machine:
    enabled: true
    power_min_w: 50
    power_max_w: 5000
    min_runtime_seconds: 600    # 10 minutes minimum
    min_pause_seconds: 600      # 10 minutes pause minimum
    startup_duration_seconds: 3
```

### Best Practices für neue Detektoren

1. **Regeln dokumentieren**: Erkläre die Erkennungsmuster deutlich in Kommentaren
2. **Konfig-Optionen nutzen**: Verwende `self.config` Properties, nicht fest verdrahtete Werte
3. **Hysterese**: Verwende `min_runtime` und `min_pause` um Flackern zu vermeiden
4. **Logging**: Strukturiertes Logging für Debugging
5. **Statistiken**: Implementiere `get_power_stats()` oder ähnliche Methoden

---

## MQTT Protokoll

### Verbindung

- **Client ID**: `ha-nilm-detector`
- **Keep-Alive**: 60 Sekunden
- **Willkill Topic**: `ha-nilm/status` mit Payload `offline`

### State Publishing (regelmäßig)

**Beispiel für Kühlschrank `kitchen_fridge`:**

```
Topic: ha-nilm/kitchen_fridge/state
Payload: ON
Retain: true

Topic: ha-nilm/kitchen_fridge/power
Payload: 245.5
Retain: true

Topic: ha-nilm/kitchen_fridge/daily_runtime
Payload: 7200.0
Retain: true

Topic: ha-nilm/kitchen_fridge/daily_cycles
Payload: 12
Retain: true

Topic: ha-nilm/kitchen_fridge/last_start
Payload: 2024-01-15T14:32:10.123456
Retain: true
```

### MQTT Discovery (beim Start)

**Beispiel für Binary Sensor:**

```
Topic: homeassistant/binary_sensor/nilm_kitchen_fridge_state/config
Payload: {
  "name": "kitchen_fridge State",
  "unique_id": "nilm_kitchen_fridge_state",
  "state_topic": "ha-nilm/kitchen_fridge/state",
  "payload_on": "ON",
  "payload_off": "OFF",
  "device_class": "power",
  "device": {
    "identifiers": ["nilm_kitchen_fridge"],
    "name": "kitchen_fridge",
    "manufacturer": "HA-NILM",
    "model": "NILM Detector"
  }
}
Retain: true
```

Die Discovery ermöglicht es Home Assistant, automatisch Entitäten zu erstellen.

---

## Entwicklung & Testing

### Local Development Setup

```bash
# Clone repo
git clone <repo-url> ha-nilm-addon
cd ha-nilm-addon

# Virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run directly
python app/main.py
```

### Testing mit Mock-Daten

```python
# In Python REPL oder Test-Script
from app.collector.source import MockPowerSource, Collector
from app.config import Config

# Create mock source
source = MockPowerSource(initial_power_w=100)
collector = Collector(source)

# Connect
collector.connect()

# Simulate power readings
source.set_power(150)
reading = collector.read()
print(reading)  # PowerReading(timestamp=..., power_w=150, ...)
```

### Unit Tests (Beispiel)

```python
import unittest
from app.detectors.fridge import FridgeDetector
from app.models import DeviceConfig, PowerReading, DeviceState
from datetime import datetime

class TestFridgeDetector(unittest.TestCase):
    def setUp(self):
        config = DeviceConfig(
            name="test_fridge",
            power_min_w=10,
            power_max_w=500,
            min_runtime_seconds=30
        )
        self.detector = FridgeDetector(config)
    
    def test_startup_detection(self):
        """Test fridge startup detection."""
        reading = PowerReading(
            timestamp=datetime.now(),
            power_w=200  # Above min_w threshold
        )
        state = self.detector.detect(reading)
        self.assertEqual(state, DeviceState.STARTING)
    
    def test_off_to_on_transition(self):
        """Test OFF → STARTING → ON transition."""
        # Startup pulse
        self.detector.detect(PowerReading(datetime.now(), 150))
        # Stable phase
        # ... simulate 5+ seconds ...
        # Should transition to ON

if __name__ == '__main__':
    unittest.main()
```

### Docker Build & Run lokal

```bash
# Build image
docker build --build-arg BUILD_FROM=python:3.11-alpine -t ha-nilm-local .

# Run container
docker run -it \
  -v $(pwd)/app:/app/app \
  -e PYTHONUNBUFFERED=1 \
  ha-nilm-local

# With mock MQTT locally
docker run -it \
  -v $(pwd)/data:/data \
  -e MQTT_BROKER=host.docker.internal \
  ha-nilm-local
```

---

## Fehlersuche

### Häufige Probleme

| Problem | Debug-Schritt | Lösung |
|---------|--------------|--------|
| MQTT `connection refused` | Broker läuft? | `mqtt_broker` und `mqtt_port` überprüfen |
| Gerät wird nicht erkannt | Schwellwerte prüfen | `power_min_w` / `power_max_w` anpassen |
| Zu häufige On/Off-Übergänge | Kurze Laufzeiten | `min_runtime_seconds` erhöhen |
| Discovery nicht in HA | MQTT Discovery aktiviert? | `discovery_enabled: true` in Config |

### Debug-Logging aktivieren

```yaml
debug: true  # In config.yaml oder options
```

Logs zeigen dann:

```
[2024-01-15 14:32:10] DEBUG - app.detectors.fridge - kitchen_fridge: Detected startup (power=245.3W)
[2024-01-15 14:32:15] DEBUG - app.detectors.fridge - kitchen_fridge: Entered running phase (power=240.1W)
[2024-01-15 14:42:20] DEBUG - app.detectors.fridge - kitchen_fridge: Cycle complete (runtime=600.1s, daily_cycles=12)
```

---

## Performance & Limits

- **Speichernutzung**: ~50 MB für Collector Puffer (1000 Lesevorgänge)
- **Update-Frequenz**: Konfigurierbar (MVP: 5 Sekunden)
- **Gleichzeitige Geräte**: 10+ (abhängig von Rechenleistung)
- **MQTT Topics**: ~5 pro Gerät (OK für Standard-Broker)

---

## Roadmap & TODOs

- [ ] Home Assistant REST API als Datenquelle
- [ ] Lernmodus mit automatischer Kalibrierung
- [ ] JSON/SQLite Profilspeicherung
- [ ] InfluxDB Export
- [ ] Waschmaschinen-Detektor
- [ ] Geschirrspüler-Detektor
- [ ] Kaffeemaschinen-Detektor
- [ ] Optional NILMTK Backend
- [ ] Web Dashboard
- [ ] Gesamtlast-Erkennung (statt einzelner Phase)

