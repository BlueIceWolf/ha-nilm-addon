from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np

from app.models import DeviceConfig, DeviceState, PowerReading, DetectionResult
from app.utils.logging import get_logger

logger = get_logger(__name__)


class FridgeDetector:
    """Rule-based refrigerator detector focusing on startup spikes and cycles."""

    def __init__(self, config: DeviceConfig):
        self.config = config
        self.name = config.name
        self.current_state = DeviceState.OFF
        self.power_history: List[PowerReading] = []
        self.cycle_start: Optional[datetime] = None
        self.last_cycle_duration = 0.0
        self.startup_phase_end: Optional[datetime] = None

    def detect(self, reading: PowerReading) -> Optional[DetectionResult]:
        self.power_history.append(reading)
        if len(self.power_history) > 300:
            self.power_history.pop(0)

        power_w = reading.power_w
        if self.current_state == DeviceState.OFF:
            if power_w > self.config.power_min_w:
                self.current_state = DeviceState.STARTING
                self.cycle_start = reading.timestamp
                self.startup_phase_end = reading.timestamp + timedelta(seconds=self.config.startup_duration_seconds)
                logger.debug(f"{self.name}: Detected startup spike ({power_w:.1f}W)")
                return self._build_result(DeviceState.STARTING, reading, confidence=0.65)

        elif self.current_state == DeviceState.STARTING:
            if power_w > self.config.power_min_w:
                if self.startup_phase_end and reading.timestamp >= self.startup_phase_end:
                    self.current_state = DeviceState.ON
                    logger.debug(f"{self.name}: Running phase entered")
                    return self._build_result(DeviceState.ON, reading, confidence=0.82)
                return self._build_result(DeviceState.STARTING, reading, confidence=0.55)
            self.current_state = DeviceState.OFF
            logger.debug(f"{self.name}: False startup, reverting to OFF")
            return self._build_result(DeviceState.OFF, reading, confidence=0.4)

        elif self.current_state == DeviceState.ON:
            if power_w > self.config.power_min_w:
                return self._build_result(DeviceState.ON, reading, confidence=0.88)
            if self.cycle_start:
                duration = (reading.timestamp - self.cycle_start).total_seconds()
                if duration >= self.config.min_runtime_seconds:
                    self.current_state = DeviceState.OFF
                    self.last_cycle_duration = duration
                    logger.debug(f"{self.name}: Cycle complete (runtime={duration:.1f}s)")
                    return self._build_result(DeviceState.OFF, reading, confidence=0.75)
                logger.debug(f"{self.name}: Runtime {duration:.1f}s below minimum")
                return self._build_result(DeviceState.ON, reading, confidence=0.66)
        return None

    def _build_result(self, state: DeviceState, reading: PowerReading, confidence: float) -> DetectionResult:
        estimated_power_w = self._estimate_device_power(reading)
        phase_total_w = float(reading.power_w)

        details = self.get_cycle_info()
        details.update(
            {
                "phase_total_w": phase_total_w,
                "estimated_power_w": estimated_power_w,
            }
        )

        return DetectionResult(
            device_name=self.name,
            timestamp=reading.timestamp,
            state=state,
            power_w=estimated_power_w,
            confidence=confidence,
            details=details,
        )

    def _estimate_device_power(self, reading: PowerReading) -> float:
        """Estimate device-only power from phase total using a local baseline."""
        phase_total = float(reading.power_w)

        # Use a short history window to approximate idle baseline for this phase.
        recent = [r.power_w for r in self.power_history[-60:]]
        baseline = min(recent) if recent else 0.0

        estimated = max(0.0, phase_total - baseline)
        return float(min(estimated, self.config.power_max_w))

    def get_cycle_info(self, window_seconds: int = 60) -> dict:
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        window = [r.power_w for r in self.power_history if r.timestamp >= cutoff]
        if not window and self.power_history:
            window = [self.power_history[-1].power_w]
        stats = np.array(window) if window else np.array([0.0])
        return {
            "state": self.current_state.value,
            "last_cycle_duration_s": self.last_cycle_duration,
            "avg_power_w": float(np.mean(stats)),
            "max_power_w": float(np.max(stats)),
            "min_power_w": float(np.min(stats)),
            "readings": len(window),
        }

    def reset(self) -> None:
        self.current_state = DeviceState.OFF
        self.power_history.clear()
        self.cycle_start = None
        self.last_cycle_duration = 0.0
        self.startup_phase_end = None
        logger.info(f"{self.name}: Detector reset")
