"""Inverter / variable-load device session tracker.

Tracks a device that operates at continuously variable power levels (heat
pumps, inverter compressors, EV chargers, etc.) through a multi-state FSM.
Unlike simple ON/OFF detectors this model records the sequence of power
states within a single run cycle so that patterns can be learned from
the shape of the session rather than a single average.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Power-level buckets
# ──────────────────────────────────────────────────────────────────────────────
_IDLE_W = 50.0
_LOW_W = 300.0
_MEDIUM_W = 1000.0


def _power_to_state(power_w: float) -> str:
    if power_w < _IDLE_W:
        return "idle"
    if power_w < _LOW_W:
        return "low"
    if power_w < _MEDIUM_W:
        return "medium"
    return "high"


@dataclass
class StateInterval:
    """A contiguous period spent at one power level."""
    state: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    peak_power_w: float = 0.0
    avg_power_w: float = 0.0
    sample_count: int = 0

    @property
    def duration_s(self) -> float:
        if self.ended_at is None:
            return 0.0
        return max((self.ended_at - self.started_at).total_seconds(), 0.0)


@dataclass
class DeviceSession:
    """Tracks a single on-cycle session for a variable / inverter-driven device.

    Usage::

        session = DeviceSession()
        for ts, power in samples:
            session.update(ts, power)
        print(session.current_state)
        print(session.summary())

    The ``states`` list records the full sequence of :class:`StateInterval`
    entries, which can be stored in the DB as a session signature for
    pattern learning.
    """

    states: List[StateInterval] = field(default_factory=list)
    current_state: str = "idle"
    _current_interval: Optional[StateInterval] = field(default=None, repr=False)
    _power_sum: float = field(default=0.0, repr=False)
    _power_count: int = field(default=0, repr=False)

    def update(self, power_w: float, ts: Optional[datetime] = None) -> str:
        """Ingest one power sample.  Returns the new state label."""
        ts = ts or datetime.utcnow()
        new_state = _power_to_state(power_w)

        if self._current_interval is None:
            # First sample
            self._current_interval = StateInterval(
                state=new_state, started_at=ts, peak_power_w=power_w, avg_power_w=power_w, sample_count=1
            )
            self._power_sum = power_w
            self._power_count = 1
            self.current_state = new_state
            return new_state

        if new_state != self.current_state:
            # Close current interval
            self._current_interval.ended_at = ts
            self._current_interval.avg_power_w = (
                self._power_sum / self._power_count if self._power_count else power_w
            )
            self.states.append(self._current_interval)

            # Open new interval
            self._current_interval = StateInterval(
                state=new_state, started_at=ts, peak_power_w=power_w, avg_power_w=power_w, sample_count=1
            )
            self._power_sum = power_w
            self._power_count = 1
            self.current_state = new_state
        else:
            # Update current interval
            self._current_interval.sample_count += 1
            self._current_interval.peak_power_w = max(self._current_interval.peak_power_w, power_w)
            self._power_sum += power_w
            self._power_count += 1

        return new_state

    def close(self, ts: Optional[datetime] = None) -> None:
        """Finalise the last open interval (call when device turns off)."""
        ts = ts or datetime.utcnow()
        if self._current_interval is not None:
            self._current_interval.ended_at = ts
            self._current_interval.avg_power_w = (
                self._power_sum / self._power_count if self._power_count else 0.0
            )
            self.states.append(self._current_interval)
            self._current_interval = None

    def reset(self) -> None:
        """Clear all state – use when a new session begins."""
        self.states = []
        self.current_state = "idle"
        self._current_interval = None
        self._power_sum = 0.0
        self._power_count = 0

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a JSON-serialisable summary of the session."""
        all_intervals = list(self.states)
        if self._current_interval is not None:
            all_intervals.append(self._current_interval)

        total_duration_s = sum(i.duration_s for i in all_intervals)
        non_idle = [i for i in all_intervals if i.state != "idle"]
        active_duration_s = sum(i.duration_s for i in non_idle)

        peak_w = max((i.peak_power_w for i in all_intervals), default=0.0)
        all_powers = [i.avg_power_w for i in all_intervals if i.sample_count > 0]
        overall_avg = sum(all_powers) / len(all_powers) if all_powers else 0.0

        state_sequence = [i.state for i in all_intervals]
        state_durations = {
            s: sum(i.duration_s for i in all_intervals if i.state == s)
            for s in {"idle", "low", "medium", "high"}
        }

        return {
            "current_state": self.current_state,
            "total_duration_s": total_duration_s,
            "active_duration_s": active_duration_s,
            "peak_power_w": peak_w,
            "avg_power_w": overall_avg,
            "interval_count": len(all_intervals),
            "state_sequence": state_sequence,
            "state_durations_s": state_durations,
        }
