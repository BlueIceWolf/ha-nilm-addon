"""Unsupervised cycle-based pattern learner with intelligent multi-mode detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional

from app.learning.features import CycleFeatures
from app.learning.mode_analyzer import ModeAnalyzer
from app.learning.smart_classifier import SmartDeviceClassifier
from app.models import PowerReading
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LearnedCycle:
    """A completed ON/OFF cycle extracted from power readings with advanced features."""

    start_ts: datetime
    end_ts: datetime
    duration_s: float
    avg_power_w: float
    peak_power_w: float
    energy_wh: float
    sample_count: int
    
    # Advanced features (optional for backwards compatibility)
    features: Optional[CycleFeatures] = None
    
    # Multi-mode detection
    operating_modes: List[Dict] = field(default_factory=list)  # [{mode, avg_power, duration, stability}]
    has_multiple_modes: bool = False


class PatternLearner:
    """Detects repeated ON/OFF cycles and extracts stable signatures with adaptive thresholds."""

    def __init__(
        self,
        on_threshold_w: float = 40.0,
        off_threshold_w: float = 20.0,
        min_cycle_seconds: float = 5.0,  # Reduced from 20.0 to catch microwaves/toasters
        max_cycle_seconds: float = 8 * 3600.0,
        use_adaptive_thresholds: bool = True,  # Enable adaptive baseline tracking
        adaptive_on_offset_w: float = 30.0,    # Baseline + 30W = ON
        adaptive_off_offset_w: float = 10.0,   # Baseline + 10W = OFF (hysteresis!)
        debounce_samples: int = 2,             # Require 2 consecutive samples for state change
        baseline_window_size: int = 60,        # Track last 60 idle samples
        noise_filter_window: int = 3,          # Median filter window for spike rejection (reduced from 5)
    ):
        # Legacy fixed thresholds (fallback if adaptive disabled)
        self.on_threshold_w = float(on_threshold_w)
        self.off_threshold_w = float(off_threshold_w)
        self.min_cycle_seconds = float(min_cycle_seconds)
        self.max_cycle_seconds = float(max_cycle_seconds)
        
        # Adaptive thresholds configuration
        self.use_adaptive_thresholds = use_adaptive_thresholds
        self.adaptive_on_offset_w = adaptive_on_offset_w
        self.adaptive_off_offset_w = adaptive_off_offset_w
        self.debounce_samples = debounce_samples
        self.baseline_window_size = baseline_window_size
        self.noise_filter_window = noise_filter_window
        
        # Adaptive baseline tracking
        self._baseline_power_w: float = 0.0
        self._baseline_history: Deque[float] = deque(maxlen=baseline_window_size)
        self._last_power_w: float = 0.0
        
        # Noise filtering (spike rejection)
        self._power_window: Deque[float] = deque(maxlen=noise_filter_window)
        
        # State machine with debouncing
        self._is_on = False
        self._stable_count = 0  # Debounce counter
        self._last_ts: Optional[datetime] = None
        self._cycle_start: Optional[datetime] = None
        self._cycle_samples: List[PowerReading] = []

    def ingest(self, reading: PowerReading) -> Optional[LearnedCycle]:
        """Ingest one reading. Returns a completed cycle when one is detected."""
        raw_power = float(reading.power_w)
        self._power_window.append(raw_power)
        
        # Apply noise filtering (median filter for spike rejection)
        power = self._get_filtered_power()
        self._last_power_w = power
        
        # Calculate dynamic thresholds
        if self.use_adaptive_thresholds:
            on_threshold = self._baseline_power_w + self.adaptive_on_offset_w
            off_threshold = self._baseline_power_w + self.adaptive_off_offset_w
        else:
            on_threshold = self.on_threshold_w
            off_threshold = self.off_threshold_w
        
        # State: OFF -> waiting for ON transition
        if not self._is_on:
            if power >= on_threshold:
                self._stable_count += 1
                if self._stable_count >= self.debounce_samples:
                    # Confirmed ON transition
                    self._is_on = True
                    self._cycle_start = reading.timestamp
                    self._cycle_samples = [reading]
                    self._last_ts = reading.timestamp
                    self._stable_count = 0
                    logger.debug(f"Cycle START: {power:.1f}W (threshold={on_threshold:.1f}W, baseline={self._baseline_power_w:.1f}W)")
            else:
                # Still idle - update baseline
                self._stable_count = 0
                self._update_baseline(power)
            return None
        
        # State: ON -> collecting samples, waiting for OFF
        if self._is_on:
            self._cycle_samples.append(reading)
            self._last_ts = reading.timestamp
            
            if power <= off_threshold:
                self._stable_count += 1
                if self._stable_count >= self.debounce_samples:
                    # Confirmed OFF transition - build cycle
                    cycle = self._build_cycle(reading.timestamp)
                    self._is_on = False
                    self._cycle_start = None
                    self._cycle_samples = []
                    self._stable_count = 0
                    logger.debug(f"Cycle END: {power:.1f}W (threshold={off_threshold:.1f}W)")
                    return cycle
            else:
                # Still ON - reset debounce counter
                self._stable_count = 0
            
            # Failsafe for very long runs that never drop below threshold
            if self._cycle_start:
                runtime = (reading.timestamp - self._cycle_start).total_seconds()
                if runtime > self.max_cycle_seconds:
                    logger.debug(f"Cycle exceeded max duration ({self.max_cycle_seconds}s); resetting")
                    self._is_on = False
                    self._cycle_start = None
                    self._cycle_samples = []
                    self._stable_count = 0
        
        return None
    
    def _get_filtered_power(self) -> float:
        """Get median-filtered power to reject transient spikes."""
        if len(self._power_window) == 0:
            return 0.0
        if len(self._power_window) < 3:
            # Not enough samples for robust median - use average
            return sum(self._power_window) / len(self._power_window)
        # Use median for robust spike rejection
        sorted_window = sorted(self._power_window)
        median_idx = len(sorted_window) // 2
        return sorted_window[median_idx]
    
    def _update_baseline(self, power: float) -> None:
        """Update adaptive baseline with new idle power reading."""
        if not self.use_adaptive_thresholds:
            return
        
        # Only update baseline with low-power samples (likely idle)
        # Avoid pollution from device activity
        if power < (self._baseline_power_w + self.adaptive_on_offset_w * 0.5):
            self._baseline_history.append(power)
            if len(self._baseline_history) >= 5:  # Need minimum samples
                # Use median for robustness against outliers
                sorted_samples = sorted(self._baseline_history)
                median_idx = len(sorted_samples) // 2
                self._baseline_power_w = sorted_samples[median_idx]
                logger.debug(f"Baseline updated: {self._baseline_power_w:.1f}W (from {len(self._baseline_history)} samples)")

    def _build_cycle(self, end_ts: datetime) -> Optional[LearnedCycle]:
        if not self._cycle_start or len(self._cycle_samples) < 2:
            return None

        duration_s = (end_ts - self._cycle_start).total_seconds()
        if duration_s < self.min_cycle_seconds or duration_s > self.max_cycle_seconds:
            return None

        values = [float(r.power_w) for r in self._cycle_samples]
        avg_power = sum(values) / len(values)
        peak_power = max(values)

        # Trapezoid integration with simple step fallback for uneven timestamps.
        energy_ws = 0.0
        for idx in range(1, len(self._cycle_samples)):
            prev = self._cycle_samples[idx - 1]
            curr = self._cycle_samples[idx]
            dt = max((curr.timestamp - prev.timestamp).total_seconds(), 0.0)
            energy_ws += (float(prev.power_w) + float(curr.power_w)) * 0.5 * dt

        energy_wh = energy_ws / 3600.0

        # Extract advanced features for better pattern recognition
        features = CycleFeatures.extract(self._cycle_samples)
        
        # Analyze for multiple operating modes (intelligent learning!)
        operating_modes = []
        has_multiple_modes = False
        if features:
            try:
                mode_list = ModeAnalyzer.analyze_cycle_for_modes(
                    features, self._cycle_samples
                )
                # Filter out very short segments and convert to dict format
                for avg_mode, duration_mode, mode_type in mode_list:
                    if duration_mode > 1.0:  # Only segments > 1s
                        operating_modes.append({
                            "type": mode_type,
                            "avg_power_w": round(avg_mode, 1),
                            "duration_s": round(duration_mode, 1),
                        })
                has_multiple_modes = len(operating_modes) > 1
                logger.debug(f"Detected {len(operating_modes)} operating modes in cycle")
            except Exception as e:
                logger.debug(f"Mode analysis failed: {e}")

        return LearnedCycle(
            start_ts=self._cycle_start,
            end_ts=end_ts,
            duration_s=duration_s,
            avg_power_w=avg_power,
            peak_power_w=peak_power,
            energy_wh=energy_wh,
            sample_count=len(self._cycle_samples),
            features=features,
            operating_modes=operating_modes,
            has_multiple_modes=has_multiple_modes,
        )

    @staticmethod
    def suggest_device_type(cycle: LearnedCycle) -> str:
        """
        Intelligent device type suggestion using SmartClassifier.
        
        Supports 25+ device types with phase-aware detection and multi-mode learning.
        Returns device type string (e.g., "microwave", "washing_machine").
        """
        try:
            # Use intelligent SmartClassifier (25+ device types, phase-aware)
            device_id, confidence, device_name = SmartDeviceClassifier.classify(cycle)
            logger.debug(f"Device classification: {device_name} (id={device_id}, conf={confidence:.2f})")
            return device_id
        except Exception as e:
            logger.warning(f"SmartClassifier failed: {e}, falling back to legacy classification")
            return PatternLearner._suggest_device_type_legacy(cycle)
    
    @staticmethod
    def _suggest_device_type_legacy(cycle: LearnedCycle) -> str:
        """Legacy fallback classification (kept for compatibility)."""
        d = cycle.duration_s
        p = cycle.peak_power_w
        avg = cycle.avg_power_w
        
        # Check multi-mode signatures first
        if cycle.has_multiple_modes and cycle.operating_modes:
            mode_types = [m["type"] for m in cycle.operating_modes]
            
            if "startup" in mode_types and p >= 1000:
                return "oven"
            
            if "startup" in mode_types and "operating" in mode_types:
                if 400 <= p <= 1600 and 1200 <= d <= 10800:
                    return "washing_machine"
                if 700 <= p <= 2600 and 1200 <= d <= 14400:
                    return "dishwasher"
            
            if "operating" in mode_types and "startup" not in mode_types:
                if p < 350 and 120 <= d <= 3600:
                    return "fridge"
        
        # Use advanced features if available
        if cycle.features:
            f = cycle.features
            
            if f.has_heating_pattern and f.rise_rate_w_per_s > 100 and p >= 1400 and d <= 900:
                return "kettle"
            
            if f.has_motor_pattern and p < 350 and 120 <= d <= 3600 and f.duty_cycle < 0.7:
                return "fridge"
            
            if f.num_substates >= 2 and 400 <= p <= 1600 and 1200 <= d <= 10800:
                return "washing_machine"
            
            if f.has_heating_pattern and 700 <= p <= 2600 and 1200 <= d <= 14400:
                return "dishwasher"
            
            if f.has_heating_pattern and p >= 1000 and f.power_variance / max(avg*avg, 1.0) < 0.1:
                return "oven"
            
            if p >= 800 and f.power_variance / max(avg*avg, 1.0) < 0.05 and 30 <= d <= 600:
                return "microwave"
        
        # Fallback heuristics
        if p < 350 and 120 <= d <= 3600:
            return "fridge"
        if 400 <= p <= 1600 and 1200 <= d <= 10800:
            return "washing_machine"
        if 700 <= p <= 2600 and 1200 <= d <= 14400:
            return "dishwasher"
        if p >= 1400 and d <= 900:
            return "kettle"
        
        return "unknown"
