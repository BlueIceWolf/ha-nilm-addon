"""Adaptive event detection primitives for NILM cycle extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


STATE_IDLE = "IDLE"
STATE_PRE_EVENT = "PRE_EVENT"
STATE_ACTIVE = "ACTIVE"
STATE_ENDING = "ENDING"


@dataclass
class EventDetectionConfig:
    delta_on_w: float = 30.0
    delta_off_w: float = 12.0
    derivative_threshold_w_per_s: float = 120.0
    debounce_samples: int = 2
    max_gap_s: float = 6.0
    end_hold_s: float = 6.0
    stabilization_grace_s: float = 12.0


@dataclass
class EventTransition:
    started: bool = False
    ended: bool = False
    previous_state: str = STATE_IDLE
    state: str = STATE_IDLE
    start_reason: str = ""
    end_reason: str = ""
    baseline_w: float = 0.0
    delta_w: float = 0.0
    derivative_w_per_s: float = 0.0
    stable_duration_s: float = 0.0


class AdaptiveEventDetector:
    """State machine for ON/OFF cycle detection with hysteresis and gap merge."""

    def __init__(self, config: EventDetectionConfig):
        self.config = config
        self._state = STATE_IDLE
        self._stable_count = 0
        self._on_since: Optional[datetime] = None
        self._candidate_since: Optional[datetime] = None
        self._ending_since: Optional[datetime] = None
        self._start_reason = ""
        self._last_ts: Optional[datetime] = None
        self._last_power_w: Optional[float] = None

    def reset(self) -> None:
        self._state = STATE_IDLE
        self._stable_count = 0
        self._on_since = None
        self._candidate_since = None
        self._ending_since = None
        self._start_reason = ""
        self._last_ts = None
        self._last_power_w = None

    @property
    def is_on(self) -> bool:
        return self._state in {STATE_PRE_EVENT, STATE_ACTIVE, STATE_ENDING}

    @property
    def state(self) -> str:
        return self._state

    def ingest(self, ts: datetime, power_w: float, baseline_w: float) -> EventTransition:
        on_threshold = baseline_w + self.config.delta_on_w
        off_threshold = baseline_w + self.config.delta_off_w
        delta_w = power_w - baseline_w

        derivative_w_per_s = 0.0
        if self._last_ts is not None and self._last_power_w is not None:
            dt_s = max((ts - self._last_ts).total_seconds(), 0.0)
            if dt_s > 0.0:
                derivative_w_per_s = (power_w - self._last_power_w) / dt_s

        transition = EventTransition(
            started=False,
            ended=False,
            previous_state=self._state,
            state=self._state,
            baseline_w=float(baseline_w),
            delta_w=float(delta_w),
            derivative_w_per_s=float(derivative_w_per_s),
        )

        start_triggered = delta_w >= self.config.delta_on_w
        derivative_triggered = derivative_w_per_s >= float(self.config.derivative_threshold_w_per_s)

        if self._state == STATE_IDLE:
            if start_triggered or derivative_triggered:
                self._candidate_since = ts
                self._start_reason = "derivative_spike" if derivative_triggered and derivative_w_per_s >= delta_w else "delta_threshold"
                self._stable_count = 1
                if self._stable_count >= max(1, int(self.config.debounce_samples)):
                    self._state = STATE_ACTIVE
                    self._on_since = ts
                    transition.started = True
                    transition.start_reason = self._start_reason
                else:
                    self._state = STATE_PRE_EVENT
            else:
                self._stable_count = 0

        elif self._state == STATE_PRE_EVENT:
            if start_triggered or derivative_triggered:
                self._stable_count += 1
                if self._stable_count >= max(1, int(self.config.debounce_samples)):
                    self._state = STATE_ACTIVE
                    self._on_since = self._candidate_since or ts
                    transition.started = True
                    transition.start_reason = self._start_reason or (
                        "derivative_spike" if derivative_triggered else "delta_threshold"
                    )
            elif delta_w <= max(self.config.delta_off_w * 0.5, 0.0):
                self._state = STATE_IDLE
                self._candidate_since = None
                self._stable_count = 0

        elif self._state == STATE_ACTIVE:
            on_runtime_s = 0.0
            if self._on_since is not None:
                on_runtime_s = max((ts - self._on_since).total_seconds(), 0.0)

            if delta_w <= self.config.delta_off_w and on_runtime_s >= max(0.0, float(self.config.stabilization_grace_s)):
                self._state = STATE_ENDING
                self._ending_since = ts
                self._stable_count = 1
            else:
                self._stable_count = 0

        elif self._state == STATE_ENDING:
            if delta_w <= self.config.delta_off_w:
                if self._ending_since is None:
                    self._ending_since = ts
                self._stable_count += 1
                stable_duration_s = max((ts - self._ending_since).total_seconds(), 0.0)
                transition.stable_duration_s = stable_duration_s
                if (
                    self._stable_count >= max(1, int(self.config.debounce_samples))
                    and stable_duration_s >= max(1.0, float(self.config.end_hold_s or self.config.max_gap_s))
                ):
                    self._state = STATE_IDLE
                    self._stable_count = 0
                    self._candidate_since = None
                    self._ending_since = None
                    self._on_since = None
                    transition.ended = True
                    transition.end_reason = "stable_near_baseline"
            else:
                self._state = STATE_ACTIVE
                self._stable_count = 0
                self._ending_since = None

        transition.state = self._state

        self._last_ts = ts
        self._last_power_w = float(power_w)
        return transition
