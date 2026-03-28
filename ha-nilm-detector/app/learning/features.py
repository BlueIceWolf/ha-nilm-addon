"""Advanced feature extraction for NILM pattern learning.

Inspired by state-of-the-art NILM research (Torch-NILM concepts),
but implemented lightweight without PyTorch for local execution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.models import PowerReading


@dataclass
class CycleFeatures:
    """Rich feature set extracted from a power cycle for better pattern recognition."""

    # Basic stats (already in LearnedCycle)
    avg_power_w: float
    peak_power_w: float
    duration_s: float
    energy_wh: float

    # Advanced features (new!)
    power_variance: float  # How stable is the power during the cycle?
    rise_rate_w_per_s: float  # How fast does it turn on? (ramp detection)
    fall_rate_w_per_s: float  # How fast does it turn off?
    duty_cycle: float  # Percentage of time above 50% of peak
    peak_to_avg_ratio: float  # Spikiness indicator
    power_std_dev: float  # Standard deviation of power

    # Multi-state detection (new!)
    num_substates: int  # Number of distinct power levels (e.g., washing machine phases)
    substates: List[Tuple[float, float]]  # (power_level, duration) pairs
    step_count: int  # Number of significant power jumps
    has_heating_pattern: bool  # Gradual rise pattern (kettle, oven)
    has_motor_pattern: bool  # Cyclic on/off (fridge, washing machine)

    @classmethod
    def extract(cls, samples: List[PowerReading]) -> Optional[CycleFeatures]:
        """Extract all features from power samples."""
        if len(samples) < 3:
            return None

        values = [float(r.power_w) for r in samples]
        n = len(values)

        # Basic stats
        avg_power = sum(values) / n
        peak_power = max(values)
        min_power = min(values)

        # Duration
        duration_s = (samples[-1].timestamp - samples[0].timestamp).total_seconds()
        if duration_s <= 0:
            duration_s = len(samples) * 5.0  # Fallback: assume 5s intervals

        # Energy (trapezoid integration)
        energy_ws = 0.0
        for idx in range(1, len(samples)):
            prev = samples[idx - 1]
            curr = samples[idx]
            dt = max((curr.timestamp - prev.timestamp).total_seconds(), 0.0)
            energy_ws += (float(prev.power_w) + float(curr.power_w)) * 0.5 * dt
        energy_wh = energy_ws / 3600.0

        # Power variance and std deviation
        variance = sum((v - avg_power) ** 2 for v in values) / n
        std_dev = math.sqrt(variance)

        # Robust edge rates from baseline/peak crossings.
        baseline = min_power
        amplitude = max(peak_power - baseline, 1.0)
        rise_low = baseline + (0.1 * amplitude)
        rise_high = baseline + (0.8 * amplitude)
        fall_high = baseline + (0.8 * amplitude)
        fall_low = baseline + (0.1 * amplitude)

        rise_t1 = None
        rise_t2 = None
        for idx, v in enumerate(values):
            if rise_t1 is None and v >= rise_low:
                rise_t1 = samples[idx].timestamp
            if rise_t2 is None and v >= rise_high:
                rise_t2 = samples[idx].timestamp
            if rise_t1 is not None and rise_t2 is not None:
                break

        if rise_t1 is not None and rise_t2 is not None:
            rise_dt = max((rise_t2 - rise_t1).total_seconds(), 0.1)
            rise_rate = (rise_high - rise_low) / rise_dt
        else:
            rise_dt = max((samples[-1].timestamp - samples[0].timestamp).total_seconds(), 1.0)
            rise_rate = max(0.0, (values[-1] - values[0]) / rise_dt)

        fall_t1 = None
        fall_t2 = None
        for rev_idx in range(n - 1, -1, -1):
            v = values[rev_idx]
            if fall_t1 is None and v >= fall_high:
                fall_t1 = samples[rev_idx].timestamp
            if fall_t2 is None and v <= fall_low:
                fall_t2 = samples[rev_idx].timestamp
            if fall_t1 is not None and fall_t2 is not None:
                break

        if fall_t1 is not None and fall_t2 is not None:
            fall_dt = max((fall_t2 - fall_t1).total_seconds(), 0.1)
            fall_rate = abs(fall_high - fall_low) / max(abs(fall_dt), 0.1)
        else:
            tail_count = min(max(int(n * 0.2), 3), 12)
            tail_start = n - tail_count
            tail_dt = max((samples[-1].timestamp - samples[tail_start].timestamp).total_seconds(), 1.0)
            fall_rate = abs(values[-1] - values[tail_start]) / tail_dt

        # Duty cycle (time above 50% of peak)
        threshold = peak_power * 0.5
        above_threshold = sum(1 for v in values if v >= threshold)
        duty_cycle = above_threshold / n

        # Peak-to-average ratio
        peak_to_avg = peak_power / max(avg_power, 1.0)

        # Multi-state detection: plateau segmentation + significant step counting.
        substates, step_count = cls._detect_substates(values, samples, duration_s)

        # Pattern detection
        has_heating = cls._detect_heating_pattern(values)
        has_motor = cls._detect_motor_pattern(values, variance, avg_power)

        return cls(
            avg_power_w=avg_power,
            peak_power_w=peak_power,
            duration_s=duration_s,
            energy_wh=energy_wh,
            power_variance=variance,
            rise_rate_w_per_s=rise_rate,
            fall_rate_w_per_s=fall_rate,
            duty_cycle=duty_cycle,
            peak_to_avg_ratio=peak_to_avg,
            power_std_dev=std_dev,
            num_substates=len(substates),
            substates=substates,
            step_count=step_count,
            has_heating_pattern=has_heating,
            has_motor_pattern=has_motor,
        )

    @staticmethod
    def _detect_substates(
        values: List[float],
        samples: List[PowerReading],
        duration_s: float,
    ) -> Tuple[List[Tuple[float, float]], int]:
        """Detect distinct power levels (states) in the cycle.

        Uses plateau segmentation with adaptive jump threshold.
        """
        if len(values) < 5:
            return ([], 0)

        min_val = min(values)
        max_val = max(values)
        amplitude = max(max_val - min_val, 0.0)
        if amplitude < 10.0:
            return ([(sum(values) / len(values), duration_s)], 0)

        jump_threshold = max(25.0, amplitude * 0.12)
        min_plateau_samples = max(2, int(len(values) * 0.03))

        plateaus: List[Tuple[float, float]] = []
        step_count = 0
        seg_start = 0

        for idx in range(1, len(values)):
            if abs(values[idx] - values[idx - 1]) > jump_threshold:
                seg_len = idx - seg_start
                if seg_len >= min_plateau_samples:
                    seg_values = values[seg_start:idx]
                    seg_level = sum(seg_values) / max(len(seg_values), 1)
                    seg_duration = max((samples[idx - 1].timestamp - samples[seg_start].timestamp).total_seconds(), 0.0)
                    plateaus.append((seg_level, seg_duration))
                step_count += 1
                seg_start = idx

        # trailing plateau
        if seg_start < len(values) - 1:
            seg_values = values[seg_start:]
            seg_level = sum(seg_values) / max(len(seg_values), 1)
            seg_duration = max((samples[-1].timestamp - samples[seg_start].timestamp).total_seconds(), 0.0)
            plateaus.append((seg_level, seg_duration))

        # Merge neighboring plateaus with near-identical levels.
        merged: List[Tuple[float, float]] = []
        level_merge_threshold = max(15.0, amplitude * 0.06)
        for level, dur in plateaus:
            if dur <= 0.0:
                continue
            if not merged:
                merged.append((level, dur))
                continue
            prev_level, prev_dur = merged[-1]
            if abs(level - prev_level) <= level_merge_threshold:
                total_dur = prev_dur + dur
                blended_level = ((prev_level * prev_dur) + (level * dur)) / max(total_dur, 1e-6)
                merged[-1] = (blended_level, total_dur)
            else:
                merged.append((level, dur))

        # Keep dominant substates by time, ignore very short noise plateaus.
        min_state_duration = max(2.0, duration_s * 0.03)
        significant = [s for s in merged if s[1] >= min_state_duration]
        if not significant:
            significant = merged[:]

        # Distinct substates by power level (800 -> 1200 -> 800 should become 2 levels).
        distinct: List[Tuple[float, float]] = []
        for level, dur in significant:
            matched = False
            for idx, (d_level, d_dur) in enumerate(distinct):
                if abs(level - d_level) <= level_merge_threshold:
                    total_dur = d_dur + dur
                    new_level = ((d_level * d_dur) + (level * dur)) / max(total_dur, 1e-6)
                    distinct[idx] = (new_level, total_dur)
                    matched = True
                    break
            if not matched:
                distinct.append((level, dur))

        distinct.sort(key=lambda x: x[1], reverse=True)
        return (distinct, step_count)

    @staticmethod
    def _detect_heating_pattern(values: List[float]) -> bool:
        """Detect gradual rise pattern typical for heating elements."""
        if len(values) < 10:
            return False

        # Check if first 30% shows consistent rise
        n = len(values)
        check_len = min(int(n * 0.3), 20)

        rises = 0
        for i in range(1, check_len):
            if values[i] > values[i - 1]:
                rises += 1

        # If >70% of initial samples are rising, it's likely heating
        return (rises / check_len) > 0.7

    @staticmethod
    def _detect_motor_pattern(values: List[float], variance: float, avg: float) -> bool:
        """Detect cyclic motor pattern (fridge compressor, washing machine)."""
        if len(values) < 15:
            return False

        # Motor patterns have moderate variance (cycling on/off)
        # Use Coefficient of Variation (CV = stdev/mean) - scale-independent
        # This is more robust than variance/(mean^2)
        std_dev = variance ** 0.5 if variance > 0 else 0.0
        if avg > 5.0:  # Only for meaningful power levels
            cv = std_dev / avg
        else:
            cv = 0.0

        # CV 0.25-0.85 = good motor pattern (25-85% variation around mean)
        # Refrigerators: 100W avg, 50-150W cycle -> CV ~0.35-0.5 OK
        # Well-regulated devices: CV < 0.25 (not motor pattern)
        # Chaotic loads: CV > 0.85 (not typical motor)
        if not (0.25 <= cv <= 0.85):
            return False

        # Look for periodic peaks (simple zero-crossing of detrended signal)
        mean_val = sum(values) / len(values)
        detrended = [v - mean_val for v in values]

        zero_crossings = 0
        for i in range(1, len(detrended)):
            if (detrended[i - 1] < 0 and detrended[i] >= 0) or (detrended[i - 1] >= 0 and detrended[i] < 0):
                zero_crossings += 1

        # If we have 3+ zero crossings, it's likely cyclic
        return zero_crossings >= 3


def shape_similarity(features1: CycleFeatures, features2: CycleFeatures) -> float:
    """Calculate shape-based similarity between two cycles.

    Returns a value between 0 (identical) and 1 (very different).
    Inspired by DTW concepts but simplified for speed.
    """

    def rel_dist(a: float, b: float) -> float:
        """Relative distance normalized by magnitude."""
        base = max(abs(a), abs(b), 1.0)
        return abs(a - b) / base

    # Compare basic power characteristics
    power_dist = rel_dist(features1.avg_power_w, features2.avg_power_w) * 0.20
    peak_dist = rel_dist(features1.peak_power_w, features2.peak_power_w) * 0.20
    duration_dist = rel_dist(features1.duration_s, features2.duration_s) * 0.15
    energy_dist = rel_dist(features1.energy_wh, features2.energy_wh) * 0.10

    # Compare shape features (this is where we add intelligence!)
    variance_dist = rel_dist(features1.power_variance, features2.power_variance) * 0.08
    rise_dist = rel_dist(features1.rise_rate_w_per_s, features2.rise_rate_w_per_s) * 0.07
    fall_dist = rel_dist(features1.fall_rate_w_per_s, features2.fall_rate_w_per_s) * 0.07
    duty_dist = abs(features1.duty_cycle - features2.duty_cycle) * 0.05
    ratio_dist = rel_dist(features1.peak_to_avg_ratio, features2.peak_to_avg_ratio) * 0.05

    # Pattern matching bonus/penalty
    pattern_dist = 0.0
    if features1.has_heating_pattern != features2.has_heating_pattern:
        pattern_dist += 0.02
    if features1.has_motor_pattern != features2.has_motor_pattern:
        pattern_dist += 0.01

    total = (
        power_dist
        + peak_dist
        + duration_dist
        + energy_dist
        + variance_dist
        + rise_dist
        + fall_dist
        + duty_dist
        + ratio_dist
        + pattern_dist
    )

    return min(total, 1.0)
