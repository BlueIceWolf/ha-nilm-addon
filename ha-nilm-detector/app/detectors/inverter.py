from collections import deque
from datetime import datetime, timedelta
from typing import Deque, List, Optional

import numpy as np

from app.models import DeviceConfig, DeviceState, PowerReading, DetectionResult
from app.utils.logging import get_logger

logger = get_logger(__name__)


class InverterDeviceDetector:
    """Detector for inverter-driven loads (soft ramps, variable runtime)."""

    def __init__(self, config: DeviceConfig, sample_window: int = 30):
        self.config = config
        self.name = config.name
        self.current_state = DeviceState.OFF
        self.power_history: Deque[tuple[datetime, float]] = deque(maxlen=300)
        self.cycle_start: Optional[datetime] = None
        self.ramp_start: Optional[datetime] = None
        self.state_phase = 0
        self.sample_window = sample_window
        self.baseline = config.power_min_w
        self.ramp_threshold = 5.0

    def detect(self, reading: PowerReading) -> Optional[DetectionResult]:
        power_w = reading.power_w
        now = reading.timestamp
        self.power_history.append((now, power_w))
        slope = self._calculate_slope()
        is_stable = self._is_stable(8)
        current_power_above_baseline = power_w > self.baseline + 40

        if self.current_state == DeviceState.OFF:
            if slope > self.ramp_threshold and current_power_above_baseline:
                self.current_state = DeviceState.STARTING
                self.ramp_start = now
                self.cycle_start = now
                logger.debug(f"{self.name}: Soft ramp startup detected (slope={slope:.2f})")
                return self._build_result(DeviceState.STARTING, reading, confidence=0.6)

        elif self.current_state == DeviceState.STARTING:
            if self.ramp_start and (now - self.ramp_start).total_seconds() >= 1 and is_stable:
                self.current_state = DeviceState.ON
                self.state_phase += 1
                logger.debug(f"{self.name}: Ramp complete, entering ON")
                return self._build_result(DeviceState.ON, reading, confidence=0.75)
            if power_w < self.baseline + 20:
                self.current_state = DeviceState.OFF
                return self._build_result(DeviceState.OFF, reading, confidence=0.4)
            return self._build_result(DeviceState.STARTING, reading, confidence=0.55)

        elif self.current_state == DeviceState.ON:
            if power_w < self.baseline + 30 or slope < -self.ramp_threshold:
                if self.cycle_start:
                    runtime = (now - self.cycle_start).total_seconds()
                    if runtime >= max(self.config.min_runtime_seconds, 10):
                        self.current_state = DeviceState.OFF
                        logger.debug(f"{self.name}: Inverter cycle done (runtime={runtime:.1f}s)")
                        return self._build_result(DeviceState.OFF, reading, confidence=0.7)
                    return self._build_result(DeviceState.ON, reading, confidence=0.55)
            return self._build_result(DeviceState.ON, reading, confidence=0.8)
        return None

    def _calculate_slope(self, window_seconds: int = 3) -> float:
        if len(self.power_history) < 2:
            return 0.0
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent = [(t, p) for t, p in self.power_history if t >= cutoff]
        if len(recent) < 2:
            recent = list(self.power_history)[-3:]
        if len(recent) < 2:
            return 0.0
        t0 = (recent[0][0] - recent[0][0]).total_seconds()
        times = [(t - recent[0][0]).total_seconds() for t, _ in recent]
        powers = [p for _, p in recent]
        duration = times[-1] - times[0]
        if duration <= 0:
            return 0.0
        return (powers[-1] - powers[0]) / duration

    def _is_stable(self, window: int) -> bool:
        if len(self.power_history) < window:
            return False
        read = [p for _, p in list(self.power_history)[-window:]]
        return float(np.var(read)) < 1500

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
        recent_window = [p for _, p in list(self.power_history)[-5:]] if self.power_history else []
        recent_avg = float(np.mean(recent_window)) if recent_window else 0.0
        recent_variance = float(np.var(recent_window)) if recent_window else 0.0
        slope = self._calculate_slope()
        cycle_elapsed = (datetime.now() - self.cycle_start).total_seconds() if self.cycle_start else 0.0
        return {
            "state": self.current_state.value,
            "power_slope_w_per_s": slope,
            "is_stable": self._is_stable(8),
            "recent_power_w": recent_window[-1] if recent_window else 0.0,
            "recent_avg_power_w": recent_avg,
            "recent_power_variance": recent_variance,
            "cycle_elapsed_s": cycle_elapsed,
            "buffered": len(self.power_history),
        }

    def reset(self) -> None:
        self.current_state = DeviceState.OFF
        self.power_history.clear()
        self.cycle_start = None
        self.ramp_start = None
        self.state_phase = 0
        logger.info(f"{self.name}: Inverter detector reset")
