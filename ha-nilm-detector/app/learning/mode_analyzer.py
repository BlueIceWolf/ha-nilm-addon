"""Intelligent multi-mode learning for appliances with multiple operating states.

Detects and learns separate signatures for different operating modes:
- Oven: Standby (10W) -> Preheat (ramping) -> Baking (stable high)
- Washing machine: Idle -> Wash -> Rinse -> Spin (each different power profile)
- Fridge: Idle -> Compressor on (cycling) -> Heater on (high stable)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.learning.features import CycleFeatures
from app.models import PowerReading
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OperatingMode:
    """Represents an operating mode with characteristic power signature."""
    
    mode_id: str  # e.g., "preheat", "baking", "spin"
    name: str  # Human-readable: "Vorheizen", "Backen"
    avg_power_w: float
    peak_power_w: float
    typical_duration_s: float
    is_transient: bool  # True if ramping/transitional, False if stable
    stability_score: float  # 0-1, higher = more stable
    frequency: int  # How often observed
    

class ModeAnalyzer:
    """Analyzes power cycles to detect distinct operating modes."""
    
    def __init__(self):
        self.detected_modes: dict[str, OperatingMode] = {}
        self.mode_sequences: List[List[str]] = []  # Track sequences of modes observed
    
    @staticmethod
    def analyze_cycle_for_modes(
        cycle_features: CycleFeatures,
        samples: List[PowerReading]
    ) -> List[Tuple[float, float, str]]:
        """
        Analyze a power cycle and detect separate modes within it.
        
        Returns: List of (avg_power_w, duration_s, mode_type) tuples
        
        Mode types:
        - "standby": Very low power (<5% of cycle peak)
        - "startup": Ramping phase (high rise rate)
        - "operating": Main operation (stable/cycling)
        - "shutdown": Falling phase (high fall rate)
        """
        if not cycle_features or not samples:
            return []
        
        values = [float(r.power_w) for r in samples]
        n = len(values)
        
        if n < 5:
            return [(_avg(values), cycle_features.duration_s, "operating")]
        
        # Segment cycle into distinct power phases
        segments = ModeAnalyzer._segment_by_power_level(
            values, samples, cycle_features
        )
        
        # Classify each segment
        modes = []
        for segment_values, segment_duration, segment_samples in segments:
            mode_type = ModeAnalyzer._classify_segment(
                segment_values,
                segment_duration,
                cycle_features,
                values
            )
            modes.append((_avg(segment_values), segment_duration, mode_type))
        
        return modes
    
    @staticmethod
    def _segment_by_power_level(
        values: List[float],
        samples: List[PowerReading],
        features: CycleFeatures
    ) -> List[Tuple[List[float], float, List[PowerReading]]]:
        """
        Segment power profile into distinct power-level phases.
        
        E.g., for oven: [low_idle] -> [ramping] -> [high_stable] -> [falling]
        """
        if len(values) < 5:
            return [(values, features.duration_s, samples)]
        
        # Normalize to 0-1 range
        min_val = min(values)
        max_val = max(values)
        range_val = max(max_val - min_val, 0.1)
        normalized = [(v - min_val) / range_val for v in values]
        
        # Detect phase boundaries using slope changes
        # If slope changes significantly, it's a phase boundary
        segments = []
        current_segment_start = 0
        phase_boundaries = [0]
        
        for i in range(1, len(normalized) - 1):
            slope_before = normalized[i] - normalized[i-1]
            slope_after = normalized[i+1] - normalized[i]
            
            # Big slope change = phase transition
            if abs(slope_before - slope_after) > 0.15:
                phase_boundaries.append(i)
        
        phase_boundaries.append(len(values) - 1)
        
        # Extract segments
        for i in range(len(phase_boundaries) - 1):
            start_idx = phase_boundaries[i]
            end_idx = phase_boundaries[i + 1]
            
            segment_values = values[start_idx:end_idx+1]
            segment_samples = samples[start_idx:end_idx+1]
            
            if len(segment_samples) >= 2:
                segment_duration = (segment_samples[-1].timestamp - segment_samples[0].timestamp).total_seconds()
                if segment_duration > 0.5:  # Only segments > 0.5s
                    segments.append((segment_values, segment_duration, segment_samples))
        
        return segments if segments else [(values, features.duration_s, samples)]
    
    @staticmethod
    def _classify_segment(
        segment: List[float],
        duration: float,
        full_cycle_features: CycleFeatures,
        full_values: List[float]
    ) -> str:
        """Classify a power segment into a mode type."""
        
        avg_seg = _avg(segment)
        peak_seg = max(segment) if segment else 0
        min_seg = min(segment) if segment else 0
        
        # Stability = variance / mean
        var_seg = sum((v - avg_seg) ** 2 for v in segment) / len(segment) if segment else 0
        std_seg = var_seg ** 0.5
        stability = 1.0 - min(std_seg / max(avg_seg, 1.0), 1.0)  # 0-1
        
        # Rise rate in segment
        rise_rate = (peak_seg - min_seg) / max(duration, 0.1) if len(segment) > 1 else 0
        
        # Classify based on power level and stability
        cycle_peak = full_cycle_features.peak_power_w
        cycle_avg = full_cycle_features.avg_power_w
        
        # Very low power = standby
        if avg_seg < cycle_peak * 0.1:
            return "standby"
        
        # High rise rate with ramping = startup
        if rise_rate > 5.0 and stability < 0.7:
            return "startup"
        
        # Falling phase = shutdown
        if rise_rate < -2.0:
            return "shutdown"
        
        # Stable operation
        return "operating"


def _avg(values: List[float]) -> float:
    """Calculate average of list."""
    return sum(values) / len(values) if values else 0.0
