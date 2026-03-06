"""
Power data collector - reads from various sources.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List
import json
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
    
    def __init__(self, ha_url: str, entity_id: str, token: str = ""):
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
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to Home Assistant."""
        # TODO: Implement actual connection check
        self.connected = True
        logger.info(f"HA REST source connected to {self.entity_id}")
        return True
    
    def disconnect(self) -> None:
        """Disconnect from Home Assistant."""
        self.connected = False
        logger.info("HA REST source disconnected")
    
    def read_power(self) -> Optional[PowerReading]:
        """Read power from Home Assistant entity."""
        if not self.connected:
            return None
        
        # TODO: Implement actual REST call
        # Example:
        # url = f"{self.ha_url}/api/states/{self.entity_id}"
        # headers = {"Authorization": f"Bearer {self.token}"}
        # response = requests.get(url, headers=headers)
        # state = response.json()["state"]
        
        logger.debug(f"Read from {self.entity_id}")
        return None


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
