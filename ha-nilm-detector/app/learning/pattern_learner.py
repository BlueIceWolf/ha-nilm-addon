"""Unsupervised cycle-based pattern learner for single power sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from app.learning.features import CycleFeatures
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


class PatternLearner:
    """Detects repeated ON/OFF cycles and extracts stable signatures."""

    def __init__(
        self,
        on_threshold_w: float = 40.0,
        off_threshold_w: float = 20.0,
        min_cycle_seconds: float = 20.0,
        max_cycle_seconds: float = 8 * 3600.0,
    ):
        self.on_threshold_w = float(on_threshold_w)
        self.off_threshold_w = float(off_threshold_w)
        self.min_cycle_seconds = float(min_cycle_seconds)
        self.max_cycle_seconds = float(max_cycle_seconds)

        self._is_on = False
        self._last_ts: Optional[datetime] = None
        self._cycle_start: Optional[datetime] = None
        self._cycle_samples: List[PowerReading] = []

    def ingest(self, reading: PowerReading) -> Optional[LearnedCycle]:
        """Ingest one reading. Returns a completed cycle when one is detected."""
        power = float(reading.power_w)

        if not self._is_on and power >= self.on_threshold_w:
            self._is_on = True
            self._cycle_start = reading.timestamp
            self._cycle_samples = [reading]
            self._last_ts = reading.timestamp
            return None

        if self._is_on:
            self._cycle_samples.append(reading)
            self._last_ts = reading.timestamp

            if power <= self.off_threshold_w:
                cycle = self._build_cycle(reading.timestamp)
                self._is_on = False
                self._cycle_start = None
                self._cycle_samples = []
                return cycle

            # Failsafe for very long runs that never drop below threshold.
            if self._cycle_start:
                runtime = (reading.timestamp - self._cycle_start).total_seconds()
                if runtime > self.max_cycle_seconds:
                    logger.debug("Cycle exceeded max duration; resetting learner state")
                    self._is_on = False
                    self._cycle_start = None
                    self._cycle_samples = []

        return None

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

        return LearnedCycle(
            start_ts=self._cycle_start,
            end_ts=end_ts,
            duration_s=duration_s,
            avg_power_w=avg_power,
            peak_power_w=peak_power,
            energy_wh=energy_wh,
            sample_count=len(self._cycle_samples),
            features=features,
        )

    @staticmethod
    def suggest_device_type(cycle: LearnedCycle) -> str:
        """AI-like heuristic for appliance type based on advanced cycle features.
        
        Uses shape features inspired by NILM research for better accuracy.
        """
        d = cycle.duration_s
        p = cycle.peak_power_w
        avg = cycle.avg_power_w
        
        # Use advanced features if available
        if cycle.features:
            f = cycle.features
            
            # Kettle/Water heater: fast rise, high power, short duration
            if f.has_heating_pattern and f.rise_rate_w_per_s > 100 and p >= 1400 and d <= 900:
                return "kettle_like"
            
            # Fridge: motor pattern, low-medium power, regular cycling
            if f.has_motor_pattern and p < 350 and 120 <= d <= 3600 and f.duty_cycle < 0.7:
                return "fridge_like"
            
            # Washing machine: multiple states, long duration, medium-high power
            if f.num_substates >= 2 and 400 <= p <= 1600 and 1200 <= d <= 10800:
                return "washing_machine_like"
            
            # Dishwasher: heating pattern initially, long duration
            if f.has_heating_pattern and 700 <= p <= 2600 and 1200 <= d <= 14400:
                return "dishwasher_like"
            
            # Oven: gradual heating, high power, very stable
            if f.has_heating_pattern and p >= 1000 and f.power_variance / max(avg*avg, 1.0) < 0.1:
                return "oven_like"
            
            # Microwave: very stable high power, short to medium duration
            if p >= 800 and f.power_variance / max(avg*avg, 1.0) < 0.05 and 30 <= d <= 600:
                return "microwave_like"
        
        # Fallback to simple heuristics if no advanced features
        if p < 350 and 120 <= d <= 3600:
            return "fridge_like"
        if 400 <= p <= 1600 and 1200 <= d <= 10800:
            return "washing_machine_like"
        if 700 <= p <= 2600 and 1200 <= d <= 14400:
            return "dishwasher_like"
        if p >= 1400 and d <= 900:
            return "kettle_or_oven_like"
        
        return "unknown"
