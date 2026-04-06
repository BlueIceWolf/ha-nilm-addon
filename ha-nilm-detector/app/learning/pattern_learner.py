"""Unsupervised cycle-based pattern learner with intelligent multi-mode detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple

from app.learning.event_detection import (
    AdaptiveEventDetector,
    EventDetectionConfig,
    STATE_ACTIVE,
    STATE_ENDING,
    STATE_IDLE,
    STATE_PRE_EVENT,
)
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
    
    # Phase information
    phase_mode: str = "single_phase"  # "single_phase" or "multi_phase"

    # Compact profile used for UI visualization (real learned curve).
    profile_points: List[Dict[str, float]] = field(default_factory=list)

    # Segmentation context kept for review/debug and downstream labeling.
    waveform_points: List[Dict[str, float]] = field(default_factory=list)
    pre_roll_samples: List[PowerReading] = field(default_factory=list)
    event_samples: List[PowerReading] = field(default_factory=list)
    post_roll_samples: List[PowerReading] = field(default_factory=list)
    segmentation_flags: Dict[str, object] = field(default_factory=dict)
    truncated_start: bool = False
    truncated_end: bool = False
    pre_roll_duration_s: float = 0.0
    post_roll_duration_s: float = 0.0


class PatternLearner:
    """Detects repeated ON/OFF cycles and extracts stable signatures with adaptive thresholds."""

    def __init__(
        self,
        on_threshold_w: float = 40.0,
        off_threshold_w: float = 20.0,
        min_cycle_seconds: float = 5.0,  # Reduced from 20.0 to catch microwaves/toasters
        max_cycle_seconds: float = 8 * 3600.0,
        use_adaptive_thresholds: bool = True,  # Enable adaptive baseline tracking
        adaptive_on_offset_w: float = 30.0,    # Baseline + delta_on_w = ON
        adaptive_off_offset_w: float = 10.0,   # Baseline + delta_off_w = OFF (hysteresis!)
        debounce_samples: int = 2,             # Require 2 consecutive samples for state change
        baseline_window_size: int = 60,        # Track last 60 idle samples
        baseline_window_seconds: float = 5.0,
        noise_filter_window: int = 3,          # Median filter window for spike rejection (reduced from 5)
        max_gap_s: float = 6.0,                # Merge short OFF gaps inside one running cycle
        end_hold_s: float = 6.0,
        pre_roll_seconds: float = 2.0,
        post_roll_seconds: float = 2.0,
        stabilization_grace_s: float = 12.0,
        derivative_threshold_w_per_s: float = 120.0,
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
        self.baseline_window_seconds = max(1.0, float(baseline_window_seconds))
        self.noise_filter_window = noise_filter_window
        self.max_gap_s = max(1.0, float(max_gap_s))
        self.end_hold_s = max(1.0, float(end_hold_s))
        self.pre_roll_seconds = max(0.0, float(pre_roll_seconds))
        self.post_roll_seconds = max(0.0, float(post_roll_seconds))
        self.stabilization_grace_s = max(0.0, float(stabilization_grace_s))
        self.derivative_threshold_w_per_s = max(1.0, float(derivative_threshold_w_per_s))
        
        # Adaptive baseline tracking
        self._baseline_power_w: float = 0.0
        self._baseline_history: Deque[Tuple[datetime, float]] = deque(maxlen=baseline_window_size)
        self._last_power_w: float = 0.0
        
        # Noise filtering (spike rejection)
        self._power_window: Deque[float] = deque(maxlen=noise_filter_window)
        
        # Shared event detector state machine.
        self._event_detector = AdaptiveEventDetector(
            EventDetectionConfig(
                delta_on_w=self.adaptive_on_offset_w,
                delta_off_w=self.adaptive_off_offset_w,
                derivative_threshold_w_per_s=self.derivative_threshold_w_per_s,
                debounce_samples=self.debounce_samples,
                max_gap_s=self.max_gap_s,
                end_hold_s=self.end_hold_s,
                stabilization_grace_s=self.stabilization_grace_s,
            )
        )
        self._last_ts: Optional[datetime] = None
        self._cycle_start: Optional[datetime] = None
        self._cycle_samples: List[PowerReading] = []
        self._candidate_event_samples: List[PowerReading] = []
        self._event_samples: List[PowerReading] = []
        self._pre_event_buffer: Deque[PowerReading] = deque()
        self._pre_roll_samples: List[PowerReading] = []
        self._post_roll_samples: List[PowerReading] = []
        self._pending_end_ts: Optional[datetime] = None
        self._pending_finalize_at: Optional[datetime] = None
        self._truncated_start = False
        self._truncated_end = False
        self._segmentation_flags: Dict[str, object] = {}

    def prime_baseline(self, power_values: List[float]) -> None:
        """Seed adaptive baseline from historical idle-ish samples before ingesting replay data."""
        if not self.use_adaptive_thresholds:
            return

        cleaned: List[float] = []
        for value in power_values:
            try:
                cleaned.append(float(value))
            except (TypeError, ValueError):
                continue

        if not cleaned:
            return

        sorted_samples = sorted(cleaned)
        median_idx = len(sorted_samples) // 2
        baseline = sorted_samples[median_idx]
        self._baseline_power_w = baseline

        self._baseline_history.clear()

    def ingest(self, reading: PowerReading) -> Optional[LearnedCycle]:
        """Ingest one reading. Returns a completed cycle when one is detected."""
        completed_cycle: Optional[LearnedCycle] = None
        raw_power = float(reading.power_w)
        self._power_window.append(raw_power)
        self._append_pre_event_sample(reading)
        
        # Apply noise filtering (median filter for spike rejection)
        power = self._get_filtered_power()
        self._last_power_w = power
        
        # Update rolling idle baseline before start detection.
        if self.use_adaptive_thresholds:
            if self._event_detector.state == STATE_IDLE and not self._pending_end_ts:
                self._update_baseline(power, reading.timestamp)
            on_threshold = self._baseline_power_w + self.adaptive_on_offset_w
            off_threshold = self._baseline_power_w + self.adaptive_off_offset_w
        else:
            on_threshold = self.on_threshold_w
            off_threshold = self.off_threshold_w
        
        transition = self._event_detector.ingest(
            ts=reading.timestamp,
            power_w=power,
            baseline_w=self._baseline_power_w,
        )

        if transition.previous_state == STATE_PRE_EVENT or transition.state == STATE_PRE_EVENT or transition.started:
            self._append_candidate_event_sample(reading)

        if transition.previous_state == STATE_PRE_EVENT and transition.state == STATE_IDLE and not transition.started:
            self._candidate_event_samples = []

        if transition.started:
            if self._pending_end_ts:
                completed_cycle = completed_cycle or self._build_cycle(self._pending_end_ts)
                self._reset_cycle_buffers()

            event_seed = list(self._candidate_event_samples) or [reading]
            self._cycle_start = event_seed[0].timestamp
            self._pre_roll_samples = self._collect_pre_roll_samples(self._cycle_start)
            self._event_samples = list(event_seed)
            self._cycle_samples = list(event_seed)
            self._candidate_event_samples = []
            self._post_roll_samples = []
            self._pending_end_ts = None
            self._pending_finalize_at = None
            self._truncated_start = self._pre_roll_duration(self._pre_roll_samples) < max(self.pre_roll_seconds * 0.5, 0.5)
            self._truncated_end = False
            self._segmentation_flags = {
                "used_rolling_baseline": True,
                "event_start_reason": str(transition.start_reason or "delta_threshold"),
                "event_end_reason": None,
                "event_state_path": [STATE_IDLE, STATE_PRE_EVENT, STATE_ACTIVE],
                "start_threshold_w": self.adaptive_on_offset_w,
                "end_threshold_w": self.adaptive_off_offset_w,
                "derivative_threshold_w_per_s": self.derivative_threshold_w_per_s,
                "baseline_start_w": round(float(self._baseline_power_w), 3),
                "start_delta_w": round(float(transition.delta_w), 3),
                "start_derivative_w_per_s": round(float(transition.derivative_w_per_s), 3),
                "stabilization_grace_s": self.stabilization_grace_s,
                "hold_time_s": self.end_hold_s,
                "pre_roll_seconds": self.pre_roll_seconds,
                "post_roll_seconds": self.post_roll_seconds,
            }
            self._last_ts = reading.timestamp
            logger.debug(
                "event started due to %s (power=%.1fW delta=%.1fW dP/dt=%.1fW/s baseline=%.1fW pre_roll=%.1fs truncated_start=%s)",
                transition.start_reason or "delta_threshold",
                power,
                transition.delta_w,
                transition.derivative_w_per_s,
                self._baseline_power_w,
                self._pre_roll_duration(self._pre_roll_samples),
                self._truncated_start,
            )
            return completed_cycle

        if self._cycle_start and transition.previous_state in {STATE_ACTIVE, STATE_ENDING} and not transition.started:
            self._append_event_sample(reading)

        if transition.ended:
            self._pending_end_ts = reading.timestamp
            self._pending_finalize_at = reading.timestamp + timedelta(seconds=self.post_roll_seconds)
            self._segmentation_flags["event_end_reason"] = str(transition.end_reason or "stable_near_baseline")
            self._segmentation_flags["baseline_end_w"] = round(float(self._baseline_power_w), 3)
            self._segmentation_flags["end_delta_w"] = round(float(transition.delta_w), 3)
            self._segmentation_flags["end_stable_duration_s"] = round(float(transition.stable_duration_s), 3)
            self._segmentation_flags["event_state_path"] = [STATE_IDLE, STATE_PRE_EVENT, STATE_ACTIVE, STATE_ENDING, STATE_IDLE]
            if self.post_roll_seconds <= 0.0:
                completed_cycle = completed_cycle or self._build_cycle(reading.timestamp)
                self._reset_cycle_buffers()
            return completed_cycle

        if self._pending_end_ts and self._event_detector.state == STATE_IDLE:
            self._post_roll_samples.append(reading)
            self._cycle_samples.append(reading)
            self._update_baseline(power, reading.timestamp)
            if self._pending_finalize_at and reading.timestamp >= self._pending_finalize_at:
                completed_cycle = completed_cycle or self._build_cycle(self._pending_end_ts)
                if completed_cycle:
                    logger.debug(
                        "event ended after %.1fs stable near baseline (duration=%.1fs baseline_end=%.1fW truncated_start=%s truncated_end=%s)",
                        float(self._segmentation_flags.get("end_stable_duration_s", 0.0) or 0.0),
                        completed_cycle.duration_s,
                        float(self._segmentation_flags.get("baseline_end_w", self._baseline_power_w) or self._baseline_power_w),
                        completed_cycle.truncated_start,
                        completed_cycle.truncated_end,
                    )
                self._reset_cycle_buffers()
            return completed_cycle

        if self._event_detector.state == STATE_IDLE and not self._pending_end_ts:
            self._update_baseline(power, reading.timestamp)
            return completed_cycle

        self._last_ts = reading.timestamp

        # Failsafe for very long runs that never drop below threshold.
        if self._cycle_start:
            runtime = (reading.timestamp - self._cycle_start).total_seconds()
            if runtime > self.max_cycle_seconds:
                logger.debug(f"Cycle exceeded max duration ({self.max_cycle_seconds}s); resetting")
                self._truncated_end = True
                self._segmentation_flags["event_end_reason"] = "timeout"
                self._event_detector.reset()
                self._reset_cycle_buffers()

        return completed_cycle

    def _append_candidate_event_sample(self, reading: PowerReading) -> None:
        if self._candidate_event_samples and self._candidate_event_samples[-1].timestamp == reading.timestamp:
            return
        self._candidate_event_samples.append(reading)

    def _append_event_sample(self, reading: PowerReading) -> None:
        if self._event_samples and self._event_samples[-1].timestamp == reading.timestamp:
            return
        self._event_samples.append(reading)
        self._cycle_samples.append(reading)

    def _append_pre_event_sample(self, reading: PowerReading) -> None:
        self._pre_event_buffer.append(reading)
        while len(self._pre_event_buffer) >= 2:
            oldest = self._pre_event_buffer[0]
            newest = self._pre_event_buffer[-1]
            try:
                age_s = (newest.timestamp - oldest.timestamp).total_seconds()
            except Exception:
                break
            if age_s <= max(self.pre_roll_seconds + self.baseline_window_seconds, 10.0):
                break
            self._pre_event_buffer.popleft()

    def _collect_pre_roll_samples(self, start_ts: datetime) -> List[PowerReading]:
        out = [
            sample
            for sample in self._pre_event_buffer
            if sample.timestamp < start_ts
            and (start_ts - sample.timestamp).total_seconds() <= max(self.pre_roll_seconds, 0.0)
        ]
        return list(out)

    @staticmethod
    def _pre_roll_duration(samples: List[PowerReading]) -> float:
        if not samples:
            return 0.0
        if len(samples) == 1:
            return 0.0

        span_s = max((samples[-1].timestamp - samples[0].timestamp).total_seconds(), 0.0)
        intervals = [
            max((samples[idx].timestamp - samples[idx - 1].timestamp).total_seconds(), 0.0)
            for idx in range(1, len(samples))
        ]
        if not intervals:
            return span_s
        representative_step_s = sum(intervals) / max(len(intervals), 1)
        return span_s + representative_step_s

    def _reset_cycle_buffers(self) -> None:
        self._cycle_start = None
        self._cycle_samples = []
        self._candidate_event_samples = []
        self._event_samples = []
        self._pre_roll_samples = []
        self._post_roll_samples = []
        self._pending_end_ts = None
        self._pending_finalize_at = None
        self._segmentation_flags = {}
        self._truncated_start = False
        self._truncated_end = False
    
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
    
    def _update_baseline(self, power: float, ts: datetime) -> None:
        """Update adaptive baseline with new idle power reading."""
        if not self.use_adaptive_thresholds:
            return

        candidate_limit = self._baseline_power_w + max(self.adaptive_on_offset_w * 0.5, 15.0)
        if self._baseline_power_w <= 0.0 or power <= candidate_limit:
            self._baseline_history.append((ts, power))

        while self._baseline_history:
            oldest_ts, _ = self._baseline_history[0]
            if oldest_ts == datetime.min:
                break
            if (ts - oldest_ts).total_seconds() <= self.baseline_window_seconds:
                break
            self._baseline_history.popleft()

        idle_samples = [value for _, value in self._baseline_history]
        if not idle_samples:
            return
        self._baseline_power_w = sum(idle_samples) / max(len(idle_samples), 1)

    def _detect_truncated_start(
        self,
        *,
        pre_roll_samples: List[PowerReading],
        event_samples: List[PowerReading],
        baseline_w: float,
    ) -> bool:
        pre_roll_duration = self._pre_roll_duration(pre_roll_samples)
        if pre_roll_duration < max(self.pre_roll_seconds * 0.5, 0.5):
            return True
        if len(event_samples) < 2:
            return True

        first_power = float(event_samples[0].power_w)
        recent_pre_max = max((float(sample.power_w) for sample in pre_roll_samples[-3:]), default=baseline_w)
        pre_roll_already_elevated = (recent_pre_max - baseline_w) >= max(self.adaptive_on_offset_w * 0.6, 15.0)
        first_sample_already_high = (first_power - baseline_w) >= max(self.adaptive_on_offset_w * 0.8, 20.0)
        return bool(pre_roll_already_elevated and first_sample_already_high)

    def _detect_truncated_end(
        self,
        *,
        event_samples: List[PowerReading],
        post_roll_samples: List[PowerReading],
        baseline_w: float,
    ) -> bool:
        if self._truncated_end:
            return True
        if len(event_samples) < 3:
            return False

        tail = [float(sample.power_w) for sample in event_samples[-3:]]
        last_drop = tail[-2] - tail[-1]
        abrupt_drop = last_drop >= max(self.adaptive_off_offset_w * 2.5, 20.0) and tail[-1] <= (baseline_w + self.adaptive_off_offset_w)
        post_roll_duration = self._pre_roll_duration(post_roll_samples)
        return bool(abrupt_drop and post_roll_duration < max(self.post_roll_seconds * 0.5, 0.5))
    
    def _check_synchronized_phase_rise(self, samples: List[PowerReading]) -> bool:
        """Check if multiple phases rise synchronously (true 3-phase device).
        
        A true 3-phase device has all phases rising/falling together.
        Multiple 1-phase devices on different phases rise independently.
        """
        if len(samples) < 5:
            return False
        
        try:
            # Extract phase powers over time
            phase_timeseries: Dict[str, List[Tuple[datetime, float]]] = {}
            
            for reading in samples:
                # Check metadata for individual phase powers
                if isinstance(reading.metadata, dict) and "phase_powers_w" in reading.metadata:
                    phase_powers = reading.metadata.get("phase_powers_w", {})
                    for phase_name, power_w in phase_powers.items():
                        if phase_name not in phase_timeseries:
                            phase_timeseries[phase_name] = []
                        phase_timeseries[phase_name].append((reading.timestamp, float(power_w)))
            
            # Need at least 2 active phases to check synchronization
            active_phases = {ph: ts for ph, ts in phase_timeseries.items() if len(ts) >= 3}
            if len(active_phases) < 2:
                return False
            
            # Find the rise point for each phase (first significant increase)
            rise_times: Dict[str, Optional[datetime]] = {}
            for phase_name, timeseries in active_phases.items():
                # Find when power increases by >30W
                baseline_power = timeseries[0][1]
                for ts, power in timeseries:
                    if power > baseline_power + 30.0:
                        rise_times[phase_name] = ts
                        break
            
            # Check if rises are synchronized (within 10 seconds window)
            valid_rises = [t for t in rise_times.values() if t is not None]
            if len(valid_rises) < 2:
                return False
            
            rise_window_s = (max(valid_rises) - min(valid_rises)).total_seconds()
            is_synchronized = rise_window_s <= 10.0  # Phases rise within 10s = synchronized
            
            if is_synchronized:
                logger.debug(f"Synchronized 3-phase rise detected: {len(valid_rises)} phases within {rise_window_s:.1f}s")
            
            return is_synchronized
            
        except Exception as e:
            logger.debug(f"Phase synchronization check failed: {e}")
            return False

    def _build_cycle(self, end_ts: datetime) -> Optional[LearnedCycle]:
        if not self._cycle_start or len(self._event_samples) < 2:
            return None

        duration_s = (end_ts - self._cycle_start).total_seconds()
        if duration_s < self.min_cycle_seconds or duration_s > self.max_cycle_seconds:
            return None

        values = [float(r.power_w) for r in self._event_samples]
        avg_power = sum(values) / len(values)
        peak_power = max(values)

        # Trapezoid integration with simple step fallback for uneven timestamps.
        energy_ws = 0.0
        for idx in range(1, len(self._event_samples)):
            prev = self._event_samples[idx - 1]
            curr = self._event_samples[idx]
            dt = max((curr.timestamp - prev.timestamp).total_seconds(), 0.0)
            energy_ws += (float(prev.power_w) + float(curr.power_w)) * 0.5 * dt

        energy_wh = energy_ws / 3600.0

        # Extract advanced features for better pattern recognition
        features = CycleFeatures.extract(self._event_samples)
        
        # Analyze for multiple operating modes (intelligent learning!)
        operating_modes = []
        has_multiple_modes = False
        if features:
            try:
                mode_list = ModeAnalyzer.analyze_cycle_for_modes(
                    features, self._event_samples
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
        
        # Detect phase mode from samples with synchronization check
        phases_set = set(r.phase for r in self._event_samples if r.phase)
        
        # Check if multiple phases rise synchronously (true 3-phase device)
        # vs. just happening to have multiple phases in samples (separate 1-phase devices)
        is_synchronized_3phase = False
        if len(phases_set) > 1:
            is_synchronized_3phase = self._check_synchronized_phase_rise(self._event_samples)
        
        if is_synchronized_3phase:
            phase_mode = "multi_phase"  # True 3-phase device (synchronized)
        elif len(phases_set) > 1:
            phase_mode = "single_phase"  # Multiple 1-phase devices on different phases
        else:
            phase_mode = "single_phase"  # Single phase only

        profile_points = self._build_profile_points(self._event_samples)
        waveform_points = self._build_profile_points(self._pre_roll_samples + self._event_samples + self._post_roll_samples)
        truncated_start = self._detect_truncated_start(
            pre_roll_samples=self._pre_roll_samples,
            event_samples=self._event_samples,
            baseline_w=float(self._segmentation_flags.get("baseline_start_w", self._baseline_power_w) or self._baseline_power_w),
        )
        truncated_end = self._detect_truncated_end(
            event_samples=self._event_samples,
            post_roll_samples=self._post_roll_samples,
            baseline_w=float(self._segmentation_flags.get("baseline_end_w", self._baseline_power_w) or self._baseline_power_w),
        )
        segmentation_flags = dict(self._segmentation_flags)
        segmentation_flags["duration_s"] = round(duration_s, 3)
        segmentation_flags["sample_count"] = len(self._event_samples)
        segmentation_flags["end_threshold_w"] = self.adaptive_off_offset_w

        return LearnedCycle(
            start_ts=self._cycle_start,
            end_ts=end_ts,
            duration_s=duration_s,
            avg_power_w=avg_power,
            peak_power_w=peak_power,
            energy_wh=energy_wh,
            sample_count=len(self._event_samples),
            features=features,
            operating_modes=operating_modes,
            has_multiple_modes=has_multiple_modes,
            phase_mode=phase_mode,
            profile_points=profile_points,
            waveform_points=waveform_points,
            pre_roll_samples=list(self._pre_roll_samples),
            event_samples=list(self._event_samples),
            post_roll_samples=list(self._post_roll_samples),
            segmentation_flags=segmentation_flags,
            truncated_start=truncated_start,
            truncated_end=truncated_end,
            pre_roll_duration_s=self._pre_roll_duration(self._pre_roll_samples),
            post_roll_duration_s=self._pre_roll_duration(self._post_roll_samples),
        )

    @staticmethod
    def _build_profile_points(samples: List[PowerReading], max_points: int = 96) -> List[Dict[str, float]]:
        """Create a compact normalized profile from cycle samples for visualization."""
        if len(samples) < 2:
            return []

        start_ts = samples[0].timestamp
        end_ts = samples[-1].timestamp
        total_s = max((end_ts - start_ts).total_seconds(), 1.0)
        step = max(1, int(len(samples) / max(max_points, 1)))

        points: List[Dict[str, float]] = []
        for idx in range(0, len(samples), step):
            sample = samples[idx]
            t_rel = max((sample.timestamp - start_ts).total_seconds(), 0.0)
            points.append(
                {
                    "t_s": round(t_rel, 3),
                    "power_w": round(float(sample.power_w), 3),
                    "t_norm": round(min(max(t_rel / total_s, 0.0), 1.0), 6),
                }
            )

        # Ensure last sample is always included.
        last = samples[-1]
        t_rel_last = max((last.timestamp - start_ts).total_seconds(), 0.0)
        if not points or points[-1].get("t_s") != round(t_rel_last, 3):
            points.append(
                {
                    "t_s": round(t_rel_last, 3),
                    "power_w": round(float(last.power_w), 3),
                    "t_norm": 1.0,
                }
            )

        return points

    @staticmethod
    def suggest_device_type(cycle: LearnedCycle) -> str:
        """
        Intelligent device type suggestion using SmartClassifier.
        
        Supports 25+ device types with phase-aware detection and multi-mode learning.
        Returns device type string (e.g., "microwave", "washing_machine").
        """
        heuristic_label, heuristic_rule = PatternLearner._suggest_device_type_first_level(cycle)
        if heuristic_label != "unknown":
            logger.debug(
                "First-level heuristic classification: label=%s rule=%s avg=%.1f peak=%.1f duration=%.1fs",
                heuristic_label,
                heuristic_rule,
                cycle.avg_power_w,
                cycle.peak_power_w,
                cycle.duration_s,
            )
            return heuristic_label

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

    @staticmethod
    def _suggest_device_type_first_level(cycle: LearnedCycle) -> tuple[str, str]:
        """Rule-based first-level classification (no ML).

        Only return concrete device types for highly distinctive signatures.
        Ambiguous cycles should fall through to the richer classifier instead of
        being forced into coarse buckets like "heater" or "long_running".
        """
        avg_power = float(cycle.avg_power_w)
        peak_power = float(cycle.peak_power_w)
        duration_s = float(cycle.duration_s)
        features = cycle.features

        if features:
            if (
                features.has_heating_pattern
                and features.rise_rate_w_per_s > 100.0
                and peak_power >= 1400.0
                and 30.0 <= duration_s <= 900.0
                and features.power_variance / max(avg_power * avg_power, 1.0) < 0.08
            ):
                return ("kettle", "distinct_heating_fast_rise_short_cycle")

            if (
                features.has_motor_pattern
                and peak_power < 350.0
                and 120.0 <= duration_s <= 3600.0
                and features.duty_cycle < 0.7
            ):
                return ("fridge", "distinct_low_power_motor_cycle")

            if (
                features.num_substates >= 2
                and features.has_motor_pattern
                and 400.0 <= peak_power <= 1600.0
                and 1200.0 <= duration_s <= 10800.0
            ):
                return ("washing_machine", "distinct_multistate_motor_cycle")

            if (
                features.has_heating_pattern
                and 700.0 <= peak_power <= 2600.0
                and 1200.0 <= duration_s <= 14400.0
            ):
                return ("dishwasher", "distinct_heating_long_cycle")

            if (
                peak_power >= 800.0
                and 30.0 <= duration_s <= 600.0
                and features.power_variance / max(avg_power * avg_power, 1.0) < 0.05
                and features.peak_to_avg_ratio < 1.35
            ):
                return ("microwave", "distinct_short_stable_high_power")

        return ("unknown", "no_rule_matched")
