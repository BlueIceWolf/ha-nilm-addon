"""
Data models for NILM detection system.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class DeviceState(Enum):
    """Possible states of a device."""
    OFF = "off"
    STARTING = "starting"
    ON = "on"
    STOPPING = "stopping"


class DeviceType(Enum):
    """High-level device category used for pipeline routing and UI grouping."""
    ON_OFF = "on_off"          # Simple switch: kettle, toaster, lamp
    MOTOR = "motor"            # Compressor / pump with cycling behaviour
    HEATER = "heater"          # Resistive heating element (stable power)
    ELECTRONICS = "electronics"  # Low-power IT / entertainment gear
    INVERTER = "inverter"      # Variable-frequency drive: heat-pump, EV charger


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


@dataclass
class NILMEvent:
    """Debug-rich event object – one ON/OFF cycle with full provenance.

    Every field that influences learning or classification decisions is
    recorded here so that no-silent-failure is guaranteed: if something goes
    wrong the ``rejection_reason`` and ``classification_path`` fields explain
    exactly what happened and why.
    """

    # ── Timing ─────────────────────────────────────────────────────────────
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # ── Power ──────────────────────────────────────────────────────────────
    delta_power: float = 0.0       # Peak delta above baseline (W)
    avg_power: float = 0.0         # Average power during event (W)
    peak_power: float = 0.0        # Absolute peak power (W)
    phase: Optional[str] = None    # "L1" / "L2" / "L3"

    # ── Baseline ───────────────────────────────────────────────────────────
    baseline_before: float = 0.0   # Adaptive baseline just before event (W)
    baseline_after: float = 0.0    # Adaptive baseline just after event (W)

    # ── Diagnostics ────────────────────────────────────────────────────────
    start_reason: Optional[str] = None    # e.g. "above_on_threshold"
    end_reason: Optional[str] = None      # e.g. "below_off_threshold"
    rejection_reason: Optional[str] = None  # Set if event was filtered out
    quality_score: float = 0.0            # 0–1; low means noisy / unreliable

    # ── Merge / overlap ────────────────────────────────────────────────────
    merged_with: Optional[int] = None    # event_id of the sibling event
    overlap_score: float = 0.0           # 0–1; >0.3 → likely overlapping

    # ── Classification provenance ──────────────────────────────────────────
    classification_path: List[str] = field(default_factory=list)
    # e.g. ["heuristic:washing_machine", "pattern_match:confirmed", "ml:0.82"]

    # ── Device type ────────────────────────────────────────────────────────
    device_type: Optional[DeviceType] = None

    # ── Structured confidence breakdown ────────────────────────────────────
    confidence_shape: float = 0.0
    confidence_duration: float = 0.0
    confidence_repeatability: float = 0.0
    confidence_ml: float = 0.0

    @property
    def duration_s(self) -> float:
        if self.start_time is None or self.end_time is None:
            return 0.0
        return max((self.end_time - self.start_time).total_seconds(), 0.0)

    @property
    def total_confidence(self) -> float:
        weights = (0.35, 0.20, 0.25, 0.20)
        values = (
            self.confidence_shape,
            self.confidence_duration,
            self.confidence_repeatability,
            self.confidence_ml,
        )
        return min(sum(w * v for w, v in zip(weights, values)), 1.0)

    @property
    def is_valid(self) -> bool:
        return self.rejection_reason is None

    def reject(self, reason: str) -> None:
        """Mark this event as rejected with an explanatory reason."""
        self.rejection_reason = reason
        if reason not in self.classification_path:
            self.classification_path.append(f"rejected:{reason}")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_s": self.duration_s,
            "delta_power": self.delta_power,
            "avg_power": self.avg_power,
            "peak_power": self.peak_power,
            "phase": self.phase,
            "baseline_before": self.baseline_before,
            "baseline_after": self.baseline_after,
            "start_reason": self.start_reason,
            "end_reason": self.end_reason,
            "rejection_reason": self.rejection_reason,
            "quality_score": self.quality_score,
            "merged_with": self.merged_with,
            "overlap_score": self.overlap_score,
            "classification_path": self.classification_path,
            "device_type": self.device_type.value if self.device_type else None,
            "confidence": {
                "shape": self.confidence_shape,
                "duration": self.confidence_duration,
                "repeatability": self.confidence_repeatability,
                "ml": self.confidence_ml,
                "total": self.total_confidence,
            },
        }
