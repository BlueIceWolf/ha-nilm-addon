"""Adaptive event detection primitives for NILM cycle extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import deque
from typing import Optional


STATE_IDLE = "IDLE"
STATE_POSSIBLE_START = "POSSIBLE_START"
STATE_ACTIVE = "ACTIVE"
STATE_POSSIBLE_END = "POSSIBLE_END"
STATE_ENDED = "ENDED"

# Backward-compatible aliases for existing callers/tests.
STATE_PRE_EVENT = STATE_POSSIBLE_START
STATE_ENDING = STATE_POSSIBLE_END


@dataclass
class EventDetectionConfig:
    delta_on_w: float = 30.0
    delta_off_w: float = 12.0
    derivative_threshold_w_per_s: float = 120.0
    start_step_delta_w: float = 18.0
    inrush_ratio_threshold: float = 1.6
    debounce_samples: int = 2
    max_gap_s: float = 6.0
    end_hold_s: float = 6.0
    stabilization_grace_s: float = 12.0
    end_variance_max_w: float = 10.0
    end_min_samples: int = 3
    shutdown_negative_slope_w_per_s: float = 40.0


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
    start_signals: int = 0
    end_signals: int = 0


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
        self._ending_powers = deque(maxlen=24)

    def reset(self) -> None:
        self._state = STATE_IDLE
        self._stable_count = 0
        self._on_since = None
        self._candidate_since = None
        self._ending_since = None
        self._start_reason = ""
        self._last_ts = None
        self._last_power_w = None
        self._ending_powers.clear()

    @property
    def is_on(self) -> bool:
        return self._state in {STATE_POSSIBLE_START, STATE_ACTIVE, STATE_POSSIBLE_END}

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

        step_delta = 0.0
        if self._last_power_w is not None:
            step_delta = float(power_w) - float(self._last_power_w)

        derivative_triggered = derivative_w_per_s >= float(self.config.derivative_threshold_w_per_s)
        step_triggered = step_delta >= float(self.config.start_step_delta_w)
        delta_triggered = delta_w >= self.config.delta_on_w
        inrush_ratio = float(power_w) / max(float(baseline_w), 1.0)
        inrush_triggered = inrush_ratio >= float(self.config.inrush_ratio_threshold) and derivative_w_per_s >= 0.0

        start_signals = int(delta_triggered) + int(derivative_triggered) + int(step_triggered) + int(inrush_triggered)
        strong_start = delta_triggered or derivative_triggered
        transition.start_signals = start_signals

        near_baseline = delta_w <= self.config.delta_off_w
        low_variance = False
        if self._ending_powers:
            avg = sum(self._ending_powers) / len(self._ending_powers)
            spread = sum(abs(v - avg) for v in self._ending_powers) / len(self._ending_powers)
            low_variance = spread <= float(self.config.end_variance_max_w)
        negative_shutdown_slope = derivative_w_per_s <= -abs(float(self.config.shutdown_negative_slope_w_per_s))
        end_signals = int(near_baseline) + int(low_variance) + int(negative_shutdown_slope)
        transition.end_signals = end_signals

        if self._state == STATE_IDLE:
            if strong_start or start_signals >= 2:
                self._candidate_since = ts
                if derivative_triggered:
                    self._start_reason = "derivative_spike"
                elif step_triggered:
                    self._start_reason = "step_jump"
                elif inrush_triggered:
                    self._start_reason = "inrush_ratio"
                else:
                    self._start_reason = "delta_threshold"
                self._stable_count = 1
                if self._stable_count >= max(1, int(self.config.debounce_samples)):
                    self._state = STATE_ACTIVE
                    self._on_since = ts
                    transition.started = True
                    transition.start_reason = self._start_reason
                else:
                    self._state = STATE_POSSIBLE_START
            else:
                self._stable_count = 0

        elif self._state == STATE_POSSIBLE_START:
            if strong_start or start_signals >= 2:
                self._stable_count += 1
                if self._stable_count >= max(1, int(self.config.debounce_samples)):
                    self._state = STATE_ACTIVE
                    self._on_since = self._candidate_since or ts
                    transition.started = True
                    transition.start_reason = self._start_reason or "delta_threshold"
            elif delta_w <= max(self.config.delta_off_w * 0.5, 0.0):
                self._state = STATE_IDLE
                self._candidate_since = None
                self._stable_count = 0

        elif self._state == STATE_ACTIVE:
            on_runtime_s = 0.0
            if self._on_since is not None:
                on_runtime_s = max((ts - self._on_since).total_seconds(), 0.0)

            if on_runtime_s >= max(0.0, float(self.config.stabilization_grace_s)) and (near_baseline or negative_shutdown_slope):
                self._state = STATE_POSSIBLE_END
                self._ending_since = ts
                self._stable_count = 1
                self._ending_powers.clear()
                self._ending_powers.append(float(power_w))
            else:
                self._stable_count = 0

        elif self._state == STATE_POSSIBLE_END:
            self._ending_powers.append(float(power_w))
            if near_baseline or end_signals >= 2:
                if self._ending_since is None:
                    self._ending_since = ts
                self._stable_count += 1
                stable_duration_s = max((ts - self._ending_since).total_seconds(), 0.0)
                transition.stable_duration_s = stable_duration_s

                enough_points = len(self._ending_powers) >= max(2, int(self.config.end_min_samples))
                baseline_converged = near_baseline and low_variance
                end_confirmed = enough_points and (baseline_converged or (near_baseline and stable_duration_s >= float(self.config.end_hold_s)))
                if (
                    self._stable_count >= max(1, int(self.config.debounce_samples))
                    and stable_duration_s >= max(1.0, float(self.config.end_hold_s or self.config.max_gap_s))
                    and end_confirmed
                ):
                    self._state = STATE_IDLE
                    self._stable_count = 0
                    self._candidate_since = None
                    self._ending_since = None
                    self._on_since = None
                    transition.ended = True
                    transition.end_reason = "stable_near_baseline"
                    transition.state = STATE_ENDED
                    self._ending_powers.clear()
            else:
                if strong_start or start_signals >= 2:
                    self._state = STATE_ACTIVE
                    self._stable_count = 0
                    self._ending_since = None
                    self._ending_powers.clear()
                elif self._ending_since is not None:
                    # Keep possible_end if power hovers close to baseline and variance is low.
                    stable_duration_s = max((ts - self._ending_since).total_seconds(), 0.0)
                    transition.stable_duration_s = stable_duration_s

        if transition.state != STATE_ENDED:
            transition.state = self._state

        self._last_ts = ts
        self._last_power_w = float(power_w)
        return transition
