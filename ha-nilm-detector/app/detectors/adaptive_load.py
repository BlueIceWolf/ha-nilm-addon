from collections import deque
from datetime import datetime, timedelta
from typing import Deque, List, Optional

import numpy as np

from app.models import DeviceConfig, DeviceState, PowerReading, DetectionResult
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AdaptiveLoadDetector:
    """Adaptive detector that learns baselines and trends for variable loads."""

    def __init__(self, config: DeviceConfig, learning_samples: int = 30):
        self.config = config
        self.name = config.name
        self.current_state = DeviceState.OFF
        self.learning_samples = max(learning_samples, 10)
        self.power_history: Deque[tuple[datetime, float]] = deque(maxlen=300)
        self.baseline_power = config.power_min_w
        self.baseline_variance = 5.0
        self.cycle_start: Optional[datetime] = None
        self.startup_phase_end: Optional[datetime] = None
        self.cycle_power: List[float] = []
        self.startup_multiplier = 1.4

    def detect(self, reading: PowerReading) -> Optional[DetectionResult]:
        power_w = reading.power_w
        now = reading.timestamp
        self.power_history.append((now, power_w))
        if self.current_state == DeviceState.OFF and len(self.power_history) >= self.learning_samples:
            self._update_baseline()

        startup_threshold = self.baseline_power + self.baseline_variance * self.startup_multiplier
        off_threshold = self.baseline_power + self.baseline_variance * 0.5
        rising = self._is_rising(3)
        stable = self._is_stable(5)

        if self.current_state == DeviceState.OFF:
            if power_w >= startup_threshold and rising:
                self.current_state = DeviceState.STARTING
                self.cycle_start = now
                self.startup_phase_end = now + timedelta(seconds=self.config.startup_duration_seconds)
                self.cycle_power = [power_w]
                return self._build_result(DeviceState.STARTING, reading, confidence=0.6)

        elif self.current_state == DeviceState.STARTING:
            self.cycle_power.append(power_w)
            if now >= self.startup_phase_end and stable and power_w >= off_threshold:
                self.current_state = DeviceState.ON
                return self._build_result(DeviceState.ON, reading, confidence=0.75)
            if power_w < off_threshold:
                self.current_state = DeviceState.OFF
                return self._build_result(DeviceState.OFF, reading, confidence=0.35)
            return self._build_result(DeviceState.STARTING, reading, confidence=0.55)

        elif self.current_state == DeviceState.ON:
            self.cycle_power.append(power_w)
            if power_w < off_threshold or not stable:
                if self.cycle_start:
                    runtime = (now - self.cycle_start).total_seconds()
                    if runtime >= self.config.min_runtime_seconds:
                        self.current_state = DeviceState.OFF
                        return self._build_result(DeviceState.OFF, reading, confidence=0.7)
                    return self._build_result(DeviceState.ON, reading, confidence=0.6)
        return None

    def _update_baseline(self) -> None:
        samples = [p for t, p in self.power_history if p < self.baseline_power + 50]
        if samples:
            self.baseline_power = float(np.mean(samples))
            self.baseline_variance = float(max(np.std(samples), 2.0))
            logger.debug(
                f"{self.name}: Baseline updated to {self.baseline_power:.1f}W ± {self.baseline_variance:.1f}W"
            )

    def _is_stable(self, window: int) -> bool:
        if len(self.power_history) < window:
            return False
        recent = [p for _, p in list(self.power_history)[-window:]]
        return float(np.var(recent)) < 300

    def _is_rising(self, window: int) -> bool:
        if len(self.power_history) < window:
            return False
        recent = list(self.power_history)[-window:]
        return recent[-1][1] > recent[0][1]

    def _build_result(self, state: DeviceState, reading: PowerReading, confidence: float) -> DetectionResult:
        return DetectionResult(
            device_name=self.name,
            timestamp=reading.timestamp,
            state=state,
            power_w=reading.power_w,
            confidence=confidence,
            details=self.get_diagnostics(),
        )

    def get_diagnostics(self) -> dict:
        history = list(self.power_history)
        latest = history[-1][1] if history else 0.0
        recent = [p for _, p in history[-5:]] if history else []
        recent_avg = float(np.mean(recent)) if recent else 0.0
        startup_threshold = self.baseline_power + self.baseline_variance * self.startup_multiplier
        learning_mode = len(history) < self.learning_samples
        return {
            "state": self.current_state.value,
            "baseline_power_w": self.baseline_power,
            "baseline_variance_w": self.baseline_variance,
            "latest_power_w": latest,
            "buffered": len(history),
            "learning_mode": learning_mode,
            "recent_avg_power_w": recent_avg,
            "startup_threshold_w": startup_threshold,
        }

    def reset(self) -> None:
        self.current_state = DeviceState.OFF
        self.learning_samples = max(self.learning_samples, 10)
        self.power_history.clear()
        self.cycle_power.clear()
        self.cycle_start = None
        self.startup_phase_end = None
        self.baseline_power = self.config.power_min_w
        self.baseline_variance = 5.0
        logger.info(f"{self.name}: Adaptive detector reset")
