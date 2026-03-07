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

        # Rise rate (first 20% of samples or first minute)
        rise_samples = min(max(int(n * 0.2), 3), 12)  # First 20% or max 12 samples
        rise_duration = (samples[rise_samples - 1].timestamp - samples[0].timestamp).total_seconds()
        rise_duration = max(rise_duration, 1.0)
        rise_rate = (values[rise_samples - 1] - values[0]) / rise_duration

        # Fall rate (last 20% of samples)
        fall_samples = min(max(int(n * 0.2), 3), 12)
        fall_start_idx = n - fall_samples
        fall_duration = (samples[-1].timestamp - samples[fall_start_idx].timestamp).total_seconds()
        fall_duration = max(fall_duration, 1.0)
        fall_rate = abs(values[-1] - values[fall_start_idx]) / fall_duration

        # Duty cycle (time above 50% of peak)
        threshold = peak_power * 0.5
        above_threshold = sum(1 for v in values if v >= threshold)
        duty_cycle = above_threshold / n

        # Peak-to-average ratio
        peak_to_avg = peak_power / max(avg_power, 1.0)

        # Multi-state detection: find distinct power levels (k-means-like clustering)
        substates = cls._detect_substates(values, duration_s)

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
            has_heating_pattern=has_heating,
            has_motor_pattern=has_motor,
        )

    @staticmethod
    def _detect_substates(values: List[float], duration_s: float) -> List[Tuple[float, float]]:
        """Detect distinct power levels (states) in the cycle.

        Uses simple binning approach - lightweight alternative to k-means.
        """
        if len(values) < 5:
            return []

        # Create power histogram with adaptive bins
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val

        if range_val < 10:  # Too stable, single state
            return [(sum(values) / len(values), duration_s)]

        # Use 10 bins for simplicity
        num_bins = min(10, len(values) // 3)
        bin_width = range_val / num_bins
        bins = [0] * num_bins

        # Count samples in each bin
        for v in values:
            bin_idx = min(int((v - min_val) / bin_width), num_bins - 1)
            bins[bin_idx] += 1

        # Find significant peaks in histogram (local maxima with >10% of samples)
        threshold = len(values) * 0.1
        states = []
        for i in range(num_bins):
            if bins[i] < threshold:
                continue
            # Check if local maximum
            is_peak = True
            for j in range(max(0, i - 1), min(num_bins, i + 2)):
                if j != i and bins[j] > bins[i]:
                    is_peak = False
                    break
            if is_peak:
                # Power level is center of bin
                power_level = min_val + (i + 0.5) * bin_width
                # Duration is proportional to bin count
                state_duration = duration_s * (bins[i] / len(values))
                states.append((power_level, state_duration))

        return sorted(states, key=lambda x: x[1], reverse=True)  # Sort by duration

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
        # Variance should be 10-60% of average power squared
        rel_variance = variance / max(avg * avg, 1.0)

        if not (0.1 <= rel_variance <= 0.6):
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
