from collections import deque
from typing import Deque, Optional

from app.models import PowerReading
from app.utils.logging import get_logger


logger = get_logger(__name__)


class ProcessingPipeline:
    """Prepares raw power data for detector consumption."""

    def __init__(
        self,
        smoothing_window: int = 5,
        noise_threshold: float = 2.0,
        adaptive_correction: bool = True,
    ):
        self.smoothing_window = max(smoothing_window, 3)
        self.noise_threshold = max(noise_threshold, 0.1)
        self.adaptive_correction = adaptive_correction

        self._smoothing_buffer: Deque[float] = deque(maxlen=self.smoothing_window)
        self._baseline_power = 0.0
        self._baseline_samples = 0

    def process(self, reading: PowerReading) -> PowerReading:
        """Apply smoothing, noise filtering and optional adaptive correction."""
        self._smoothing_buffer.append(reading.power_w)
        smoothed = float(sum(self._smoothing_buffer)) / len(self._smoothing_buffer)

        noise_filtered = self._noise_filter(smoothed, reading.power_w)
        corrected = self._auto_correct_baseline(noise_filtered)

        return PowerReading(
            timestamp=reading.timestamp,
            power_w=corrected,
            phase=reading.phase,
            metadata={**reading.metadata, "smoothed_power_w": smoothed},
        )

    def _noise_filter(self, smoothed: float, raw: float) -> float:
        """Dampen small oscillations and treat spikes carefully."""
        if abs(smoothed - raw) <= self.noise_threshold:
            return smoothed
        return raw

    def _auto_correct_baseline(self, value: float) -> float:
        """Adapt baseline during sustained idle periods."""
        if not self.adaptive_correction:
            return value

        if value <= self._baseline_power + 5.0 or self._baseline_samples < self.smoothing_window:
            self._baseline_samples += 1
            weight = 1 / self._baseline_samples
            self._baseline_power = (self._baseline_power * (1 - weight)) + value * weight
            logger.debug(f"Updated baseline to {self._baseline_power:.1f}W")

        return max(value, self._baseline_power)
