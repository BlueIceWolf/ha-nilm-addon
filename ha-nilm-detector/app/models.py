"""
Data models for NILM detection system.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class DeviceState(Enum):
    """Possible states of a device."""
    OFF = "off"
    STARTING = "starting"
    ON = "on"
    STOPPING = "stopping"


@dataclass
class PowerReading:
    """Raw power reading."""
    timestamp: datetime
    power_w: float
    phase: str = "L1"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceConfig:
    """Configuration for a device detector."""
    name: str
    enabled: bool = True
    power_min_w: float = 10.0
    power_max_w: float = 5000.0
    min_runtime_seconds: int = 30
    min_pause_seconds: int = 60
    startup_spike_w: float = 0.0
    startup_duration_seconds: int = 5
    duty_cycle_threshold: float = 0.3
    metadata: Dict[str, Any] = field(default_factory=dict)
    detector_type: str = "fridge"
    confidence_threshold: float = 0.6


@dataclass
class DetectionResult:
    """Result from device detection."""
    device_name: str
    timestamp: datetime
    state: DeviceState
    power_w: float
    confidence: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceState_:
    """Device state information."""
    device_name: str
    state: DeviceState
    power_w: float
    last_start: Optional[datetime] = None
    runtime_seconds: float = 0.0
    daily_cycles: int = 0
    daily_runtime_seconds: float = 0.0
    last_update: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
