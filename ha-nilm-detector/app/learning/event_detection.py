"""Adaptive event detection primitives for NILM cycle extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EventDetectionConfig:
    delta_on_w: float = 30.0
    delta_off_w: float = 12.0
    debounce_samples: int = 2
    max_gap_s: float = 6.0


@dataclass
class EventTransition:
    started: bool = False
    ended: bool = False


class AdaptiveEventDetector:
    """State machine for ON/OFF cycle detection with hysteresis and gap merge."""

    def __init__(self, config: EventDetectionConfig):
        self.config = config
        self._is_on = False
        self._stable_count = 0
        self._below_off_since: Optional[datetime] = None

    def reset(self) -> None:
        self._is_on = False
        self._stable_count = 0
        self._below_off_since = None

    @property
    def is_on(self) -> bool:
        return self._is_on

    def ingest(self, ts: datetime, power_w: float, baseline_w: float) -> EventTransition:
        on_threshold = baseline_w + self.config.delta_on_w
        off_threshold = baseline_w + self.config.delta_off_w

        transition = EventTransition(started=False, ended=False)

        if not self._is_on:
            if power_w >= on_threshold:
                self._stable_count += 1
                if self._stable_count >= max(1, int(self.config.debounce_samples)):
                    self._is_on = True
                    self._stable_count = 0
                    self._below_off_since = None
                    transition.started = True
            else:
                self._stable_count = 0
            return transition

        # Currently ON
        if power_w <= off_threshold:
            if self._below_off_since is None:
                self._below_off_since = ts
            self._stable_count += 1

            below_duration_s = 0.0
            if self._below_off_since is not None:
                below_duration_s = max((ts - self._below_off_since).total_seconds(), 0.0)

            if self._stable_count >= max(1, int(self.config.debounce_samples)) and below_duration_s >= max(1.0, float(self.config.max_gap_s)):
                self._is_on = False
                self._stable_count = 0
                self._below_off_since = None
                transition.ended = True
            return transition

        # Still ON
        self._stable_count = 0
        self._below_off_since = None
        return transition
