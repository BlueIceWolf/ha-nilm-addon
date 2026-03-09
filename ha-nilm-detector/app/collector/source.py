"""
Power data collector - reads from various sources.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import requests
from app.models import PowerReading
from app.utils.logging import get_logger


logger = get_logger(__name__)


class PowerSource(ABC):
    """Abstract base class for power data sources."""
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to the power data source."""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the power data source."""
        pass
    
    @abstractmethod
    def read_power(self) -> Optional[PowerReading]:
        """Read current power value."""
        pass


class MockPowerSource(PowerSource):
    """Mock power source for testing and simulation."""
    
    def __init__(self, initial_power_w: float = 0.0, phase: str = "L1"):
        """
        Initialize mock power source.
        
        Args:
            initial_power_w: Initial power value
            phase: Phase identifier (L1, L2, L3)
        """
        self.power_w = initial_power_w
        self.phase = phase
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to mock source."""
        self.connected = True
        logger.info(f"Mock power source connected ({self.phase})")
        return True
    
    def disconnect(self) -> None:
        """Disconnect mock source."""
        self.connected = False
        logger.info("Mock power source disconnected")
    
    def read_power(self) -> Optional[PowerReading]:
        """Read simulated power value."""
        if not self.connected:
            return None
        
        return PowerReading(
            timestamp=datetime.now(),
            power_w=self.power_w,
            phase=self.phase
        )
    
    def set_power(self, power_w: float) -> None:
        """Set simulated power value (for testing)."""
        self.power_w = power_w


class HARestPowerSource(PowerSource):
    """Read power from Home Assistant via REST API."""
    
    def __init__(
        self,
        ha_url: str,
        entity_id: str,
        token: str = "",
        phase: str = "L1",
        preferred_name: str = "",
        phase_entity_ids: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize Home Assistant REST power source.
        
        Args:
            ha_url: Home Assistant URL (e.g., http://homeassistant.local:8123)
            entity_id: Entity ID to read from
            token: Long-lived access token
        """
        self.ha_url = ha_url
        self.entity_id = entity_id
        self.token = token
        self.phase = phase
        self.preferred_name = preferred_name.strip().lower()
        self.phase_entity_ids: Dict[str, str] = {
            str(k).upper(): str(v).strip()
            for k, v in (phase_entity_ids or {}).items()
            if str(v).strip()
        }
        if not self.phase_entity_ids and entity_id:
            self.phase_entity_ids = {str(phase or 'L1').upper(): str(entity_id).strip()}
        self.connected = False
        self._timeout_seconds = 10
        self._active_phase_threshold_w = 20.0

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        token = str(self.token or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _build_state_url(self, entity_id: str) -> str:
        return f"{self.ha_url.rstrip('/')}/states/{entity_id}"

    def _build_states_url(self) -> str:
        return f"{self.ha_url.rstrip('/')}/states"

    @staticmethod
    def _parse_power_value(value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip().lower()
        if text in {"unknown", "unavailable", "none", "null", ""}:
            return None

        cleaned = text.replace("w", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _to_watts(power_value: float, unit: str) -> float:
        normalized = str(unit or "W").strip().lower()
        if normalized == "kw":
            return power_value * 1000.0
        return power_value

    def _extract_power_value_from_payload(self, payload: dict) -> Optional[float]:
        attrs = payload.get("attributes", {}) if isinstance(payload, dict) else {}
        unit = attrs.get("unit_of_measurement", "W")

        state_value = self._parse_power_value(payload.get("state"))
        if state_value is not None:
            return self._to_watts(state_value, unit)

        for key in ["power", "power_w", "value"]:
            parsed = self._parse_power_value(attrs.get(key))
            if parsed is not None:
                return self._to_watts(parsed, unit)
        return None

    def _discover_power_entity(self) -> Optional[str]:
        """Try to find a usable power sensor entity automatically."""
        try:
            response = requests.get(
                self._build_states_url(),
                headers=self._build_headers(),
                timeout=self._timeout_seconds,
            )
            if response.status_code != 200:
                logger.warning(f"HA REST auto-discovery failed: HTTP {response.status_code}")
                return None

            states = response.json()
            if not isinstance(states, list):
                return None

            candidates: List[str] = []
            scored: List[tuple[int, str]] = []

            for item in states:
                if not isinstance(item, dict):
                    continue
                entity_id = str(item.get("entity_id", ""))
                if not entity_id.startswith("sensor."):
                    continue

                attrs = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
                unit = str(attrs.get("unit_of_measurement", "")).lower()
                device_class = str(attrs.get("device_class", "")).lower()
                friendly_name = str(attrs.get("friendly_name", "")).lower()

                power_value = self._extract_power_value_from_payload(item)
                if power_value is None:
                    continue

                # Prefer explicit power-class sensors and common "total power" names.
                score = 0
                if device_class == "power" or unit in {"w", "kw"}:
                    score += 2
                if any(tag in entity_id for tag in ["total", "house", "home", "main", "grid", "power"]):
                    score += 1

                if self.preferred_name:
                    if self.preferred_name == entity_id.lower() or self.preferred_name == friendly_name:
                        score += 8
                    elif self.preferred_name in entity_id.lower() or self.preferred_name in friendly_name:
                        score += 4

                candidates.append(entity_id)
                scored.append((score, entity_id))

            if not scored:
                return None

            scored.sort(key=lambda entry: entry[0], reverse=True)
            selected = scored[0][1]
            logger.info(
                f"Auto-discovered power entity '{selected}' from {len(candidates)} candidate(s)"
            )
            return selected
        except Exception as e:
            logger.error(f"HA REST power entity auto-discovery failed: {e}", exc_info=True)
            return None
    
    def connect(self) -> bool:
        """Connect to Home Assistant."""
        try:
            if not self.phase_entity_ids and not self.entity_id:
                self.entity_id = self._discover_power_entity() or ""
                if self.entity_id:
                    self.phase_entity_ids = {str(self.phase or 'L1').upper(): self.entity_id}

            if not self.phase_entity_ids:
                logger.error("HA REST connect failed: no power entity configured or auto-discovered")
                return False

            reachable = 0
            for phase_name, phase_entity in self.phase_entity_ids.items():
                url = self._build_state_url(phase_entity)
                response = requests.get(
                    url,
                    headers=self._build_headers(),
                    timeout=self._timeout_seconds,
                )
                if response.status_code == 200:
                    reachable += 1
                    continue

                if response.status_code == 401:
                    logger.error(
                        "HA REST auth failed (401). Check homeassistant_api permission, "
                        "SUPERVISOR_TOKEN availability, or set home_assistant.token manually."
                    )
                    return False

                logger.warning(
                    f"HA REST connect check failed for {phase_name}:{phase_entity}: HTTP {response.status_code}"
                )

            if reachable <= 0:
                logger.error("HA REST connect failed: none of the configured phase entities are reachable")
                return False

            self.connected = True
            logger.info(
                "HA REST source connected with phase entities: "
                f"{', '.join(f'{k}={v}' for k, v in self.phase_entity_ids.items())}"
            )
            return True
        except Exception as e:
            logger.error(f"HA REST connect check failed: {e}", exc_info=True)
            return False
    
    def disconnect(self) -> None:
        """Disconnect from Home Assistant."""
        self.connected = False
        logger.info("HA REST source disconnected")
    
    def read_power(self) -> Optional[PowerReading]:
        """Read power from Home Assistant entity."""
        if not self.connected:
            return None

        try:
            phase_powers_w: Dict[str, float] = {}
            phase_entities: Dict[str, str] = {}

            for phase_name, phase_entity in self.phase_entity_ids.items():
                state_value, payload = self._read_entity_power(phase_entity)
                if state_value is None:
                    continue
                phase_powers_w[phase_name] = float(state_value)
                phase_entities[phase_name] = phase_entity

            if not phase_powers_w:
                logger.debug("No numeric power value available for configured phase entities")
                return None

            total_power_w = float(sum(phase_powers_w.values()))
            
            # Classify as multi_phase only if power is balanced across all 3 phases
            # (indicates a true 3-phase device, not multiple single-phase devices on different phases)
            if total_power_w < self._active_phase_threshold_w:
                phase_mode = "idle"
            else:
                # Check if power distribution is balanced across phases
                # For true 3-phase: each phase contributes roughly equally
                # For single-phase on different phases: one phase dominates
                phase_percentages = {
                    name: (value / total_power_w) if total_power_w > 0 else 0
                    for name, value in phase_powers_w.items()
                }
                
                # A true 3-phase device has no single phase dominating (max < 60% of total)
                # and all phases contributing meaningfully (min > 15% of total)
                max_percentage = max(phase_percentages.values()) if phase_percentages else 0
                min_percentage = min(phase_percentages.values()) if phase_percentages else 0
                
                num_active_phases = sum(1 for v in phase_powers_w.values() if v >= self._active_phase_threshold_w)
                
                # Multi-phase only if: all 3 phases active AND power is balanced
                if (num_active_phases == 3 and 
                    max_percentage < 0.60 and 
                    min_percentage > 0.15):
                    phase_mode = "multi_phase"
                elif num_active_phases == 0:
                    phase_mode = "idle"
                else:
                    phase_mode = "single_phase"
            
            phase_active_count = num_active_phases

            return PowerReading(
                timestamp=datetime.now(),
                power_w=total_power_w,
                phase="+".join(phase_powers_w.keys()),
                metadata={
                    "entity_id": self.entity_id,
                    "phase_entities": phase_entities,
                    "phase_powers_w": phase_powers_w,
                    "phase_active_count": phase_active_count,
                    "phase_mode": phase_mode,
                    "active_phases": active_phases,
                    "unit": "W",
                },
            )
        except Exception as e:
            logger.error("Error reading power from HA REST phase entities: %s", e, exc_info=True)
            return None

    def _read_entity_power(self, entity_id: str) -> Tuple[Optional[float], Optional[dict]]:
        """Read one entity and return watts + payload."""
        url = self._build_state_url(entity_id)
        response = requests.get(
            url,
            headers=self._build_headers(),
            timeout=self._timeout_seconds,
        )
        if response.status_code != 200:
            logger.warning(f"Failed to read {entity_id} from HA REST: HTTP {response.status_code}")
            return None, None

        payload = response.json()
        state_value = self._extract_power_value_from_payload(payload)
        if state_value is None:
            logger.debug(f"Entity {entity_id} has no numeric power value")
            return None, payload
        return state_value, payload


class Collector:
    """Collects power readings from a source."""
    
    def __init__(self, source: PowerSource, phases: Optional[List[str]] = None):
        """
        Initialize collector.
        
        Args:
            source: Power data source
            phases: List of phases to track (e.g., ["L1", "L2", "L3"])
        """
        self.source = source
        self.phases = phases or ["L1"]
        self.readings: List[PowerReading] = []
        self._connected = False
    
    def connect(self) -> bool:
        """Connect collector to source."""
        if self.source.connect():
            self._connected = True
            logger.info("Collector connected")
            return True
        return False
    
    def disconnect(self) -> None:
        """Disconnect collector from source."""
        self.source.disconnect()
        self._connected = False
        logger.info("Collector disconnected")
    
    def is_connected(self) -> bool:
        """Check if collector is connected."""
        return self._connected
    
    def read(self) -> Optional[PowerReading]:
        """
        Read power data.
        
        Returns:
            Latest power reading or None
        """
        if not self._connected:
            return None
        
        reading = self.source.read_power()
        if reading:
            self.readings.append(reading)
            # Keep only last 1000 readings in memory
            if len(self.readings) > 1000:
                self.readings = self.readings[-1000:]
        
        return reading
    
    def get_latest(self) -> Optional[PowerReading]:
        """Get latest power reading."""
        return self.readings[-1] if self.readings else None
    
    def get_readings_since(self, minutes: int) -> List[PowerReading]:
        """Get readings from the last N minutes."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [r for r in self.readings if r.timestamp >= cutoff]
