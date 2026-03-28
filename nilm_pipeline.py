#!/usr/bin/env python3
"""NILM learning pipeline.

CLI:
    python nilm_pipeline.py input.json --out out

Pipeline:
    raw data -> event detection -> feature extraction -> clustering/update ->
    quality/classification -> export datasets
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple


QUALITY_LABELS = ("sehr_gut", "brauchbar", "unsicher", "verwerfen")
DEVICE_TYPES = ("fridge", "pump", "kettle", "microwave", "oven", "heater")


@dataclass
class Sample:
    t: float
    power_w: float


@dataclass
class Event:
    event_id: str
    start_idx: int
    end_idx: int
    start_t: float
    end_t: float
    baseline_w: float
    samples: List[Sample] = field(default_factory=list)


@dataclass
class EventFeatures:
    event_id: str
    start_t: float
    end_t: float
    duration_s: float
    avg_power_w: float
    peak_power_w: float
    energy_wh: float
    power_std: float
    power_variance: float
    plateau_count: int
    dominant_levels_w: List[float]
    jump_count: int
    largest_jump_w: float
    rise_rate_w_per_s: float
    fall_rate_w_per_s: float
    peak_to_avg_ratio: float
    profile_points: List[float]
    phase: str


@dataclass
class PatternState:
    pattern_id: str
    seen_count: int
    avg_power_w: float
    peak_power_w: float
    duration_s: float
    energy_wh: float
    power_variance: float
    power_std: float
    plateau_count: int
    dominant_levels_w: List[float]
    jump_count: int
    rise_rate_w_per_s: float
    fall_rate_w_per_s: float
    peak_to_avg_ratio: float
    stability_score: float
    confidence_score: float
    candidate_name: str
    suggestion_type: str
    phase: str
    profile_points: List[float]
    event_times: List[float] = field(default_factory=list)
    frequency_per_day: float = 0.0
    quality_label: str = "unsicher"
    quality_reason: str = ""
    alternative_hints: List[str] = field(default_factory=list)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            x = float(text)
        except ValueError:
            return default
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return default
        return int(round(value))
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _clamp(v: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(vmax, v))


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(round((len(sorted_vals) - 1) * _clamp(pct, 0.0, 1.0)))
    return sorted_vals[idx]


def _extract_profile_values(profile_points: Any) -> List[float]:
    if not isinstance(profile_points, list):
        return []
    values: List[float] = []
    for p in profile_points:
        if isinstance(p, (int, float, str)):
            values.append(_safe_float(p))
            continue
        if isinstance(p, dict):
            for key in ("power_w", "power", "value", "w", "watts", "p"):
                if key in p:
                    values.append(_safe_float(p.get(key)))
                    break
    return [max(0.0, x) for x in values]


def load_input(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if isinstance(payload, list):
        return {"readings": payload, "patterns": []}
    if not isinstance(payload, dict):
        raise ValueError("Input root must be a JSON object or a list of readings")

    readings = payload.get("readings")
    if readings is None:
        for key in ("power_series", "series", "samples"):
            if isinstance(payload.get(key), list):
                readings = payload.get(key)
                break
    if readings is None:
        readings = []

    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        patterns = []

    return {"readings": readings, "patterns": patterns, "raw": payload}


def normalize_readings(items: Any) -> List[Sample]:
    if not isinstance(items, list):
        return []

    samples: List[Sample] = []
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        if "power_w" in row:
            power = _safe_float(row.get("power_w"))
        elif "power" in row:
            power = _safe_float(row.get("power"))
        elif "value" in row:
            power = _safe_float(row.get("value"))
        else:
            continue

        if "t" in row:
            t = _safe_float(row.get("t"), default=float(idx))
        elif "ts" in row:
            t = _safe_float(row.get("ts"), default=float(idx))
        elif "timestamp" in row:
            t = _safe_float(row.get("timestamp"), default=float(idx))
        else:
            t = float(idx)

        samples.append(Sample(t=t, power_w=max(0.0, power)))

    if not samples:
        return []

    samples.sort(key=lambda x: x.t)
    # Ensure monotonic timestamps.
    last_t = samples[0].t
    for i in range(1, len(samples)):
        if samples[i].t <= last_t:
            samples[i].t = last_t + 1.0
        last_t = samples[i].t
    return samples


def _fallback_profile(avg_power_w: float, peak_power_w: float, duration_s: float) -> List[float]:
    p1 = max(0.0, avg_power_w * 0.55)
    p2 = max(p1, min(peak_power_w, max(avg_power_w * 1.15, p1 + 20.0)))
    p3 = max(0.0, avg_power_w)
    p4 = max(0.0, avg_power_w * 0.8)
    n = int(_clamp(duration_s, 20.0, 1200.0))
    n = max(12, min(n, 80))
    out: List[float] = []
    for i in range(n):
        frac = i / max(1, n - 1)
        if frac < 0.2:
            out.append(p1 + (p2 - p1) * (frac / 0.2))
        elif frac < 0.7:
            out.append(p3 + (p2 - p3) * 0.15)
        else:
            out.append(p4)
    return out


def simulate_readings_from_patterns(patterns: Sequence[Dict[str, Any]]) -> List[Sample]:
    samples: List[Sample] = []
    t = 0.0
    baseline = 90.0

    for pat in patterns:
        seen_count = _clamp(float(_safe_int(pat.get("seen_count"), default=1)), 1.0, 10.0)
        repeats = int(seen_count)

        avg_power = max(10.0, _safe_float(pat.get("avg_power_w"), 150.0))
        peak_power = max(avg_power, _safe_float(pat.get("peak_power_w"), avg_power * 1.2))
        duration_s = max(15.0, _safe_float(pat.get("duration_s"), 120.0))
        profile = _extract_profile_values(pat.get("profile_points"))
        if not profile:
            profile = _fallback_profile(avg_power, peak_power, duration_s)

        for _ in range(repeats):
            idle_gap = 20
            for _k in range(idle_gap):
                samples.append(Sample(t=t, power_w=baseline))
                t += 1.0

            for val in profile:
                p = baseline + max(0.0, val)
                samples.append(Sample(t=t, power_w=p))
                t += 1.0

            # Small cooldown section.
            for _k in range(8):
                samples.append(Sample(t=t, power_w=baseline + avg_power * 0.05))
                t += 1.0

    return samples


def build_raw_samples(payload: Dict[str, Any]) -> Tuple[List[Sample], str]:
    readings = normalize_readings(payload.get("readings"))
    patterns = payload.get("patterns") if isinstance(payload.get("patterns"), list) else []

    if readings:
        return readings, "readings"

    if patterns:
        # Root cause: current workflow often exports already learned patterns only.
        # Without raw power stream, no new events are detected, no cluster merge happens,
        # and no pattern state is updated over time. This script simulates a raw stream
        # from profile_points so we can re-run detection and force actual learning steps.
        simulated = simulate_readings_from_patterns(patterns)
        return simulated, "simulated_from_patterns"

    raise ValueError("No readings and no patterns found in input JSON")


def estimate_baseline(power_values: Sequence[float]) -> float:
    if not power_values:
        return 0.0
    return _percentile(power_values, 0.2)


def detect_events(
    samples: Sequence[Sample],
    threshold_w: float,
    min_duration_s: float,
    gap_merge_s: float,
    baseline_window: int = 120,
) -> List[Event]:
    if not samples:
        return []

    power_values = [s.power_w for s in samples]
    baseline_global = estimate_baseline(power_values)

    baseline_hist: Deque[float] = deque(maxlen=max(10, baseline_window))
    baseline_hist.extend(power_values[: min(len(power_values), 40)])

    events: List[Event] = []
    in_event = False
    start_idx = 0
    baseline_at_start = baseline_global

    for idx, s in enumerate(samples):
        rolling_base = statistics.median(baseline_hist) if baseline_hist else baseline_global
        trigger = rolling_base + threshold_w

        if not in_event and s.power_w > trigger:
            in_event = True
            start_idx = idx
            baseline_at_start = rolling_base

        if in_event:
            end_trigger = rolling_base + threshold_w * 0.55
            if s.power_w <= end_trigger:
                end_idx = idx
                duration = samples[end_idx].t - samples[start_idx].t
                if duration >= min_duration_s:
                    ev = Event(
                        event_id=f"ev_{len(events):05d}",
                        start_idx=start_idx,
                        end_idx=end_idx,
                        start_t=samples[start_idx].t,
                        end_t=samples[end_idx].t,
                        baseline_w=baseline_at_start,
                        samples=list(samples[start_idx : end_idx + 1]),
                    )
                    events.append(ev)
                in_event = False

        if not in_event:
            baseline_hist.append(s.power_w)

    if in_event:
        end_idx = len(samples) - 1
        duration = samples[end_idx].t - samples[start_idx].t
        if duration >= min_duration_s:
            events.append(
                Event(
                    event_id=f"ev_{len(events):05d}",
                    start_idx=start_idx,
                    end_idx=end_idx,
                    start_t=samples[start_idx].t,
                    end_t=samples[end_idx].t,
                    baseline_w=baseline_at_start,
                    samples=list(samples[start_idx : end_idx + 1]),
                )
            )

    return merge_short_gaps(events, samples, gap_merge_s)


def merge_short_gaps(events: Sequence[Event], samples: Sequence[Sample], gap_merge_s: float) -> List[Event]:
    if not events:
        return []

    merged: List[Event] = []
    current = events[0]

    for nxt in events[1:]:
        gap = max(0.0, nxt.start_t - current.end_t)
        if gap <= gap_merge_s:
            current.end_idx = nxt.end_idx
            current.end_t = nxt.end_t
            current.samples = list(samples[current.start_idx : current.end_idx + 1])
            continue
        merged.append(current)
        current = nxt

    merged.append(current)

    for idx, ev in enumerate(merged):
        ev.event_id = f"ev_{idx:05d}"
    return merged


def _cluster_levels(levels: Sequence[float], tol: float) -> List[float]:
    if not levels:
        return []
    sorted_vals = sorted(levels)
    groups: List[List[float]] = [[sorted_vals[0]]]
    for val in sorted_vals[1:]:
        if abs(val - statistics.mean(groups[-1])) <= tol:
            groups[-1].append(val)
        else:
            groups.append([val])
    return [round(statistics.mean(g), 2) for g in groups]


def _detect_plateaus_and_jumps(values: Sequence[float]) -> Tuple[int, List[float], int, float]:
    if len(values) < 3:
        return 0, [], 0, 0.0

    arr = [max(0.0, x) for x in values]
    med = statistics.median(arr)
    tol = max(15.0, med * 0.08)
    jump_threshold = max(35.0, max(arr) * 0.12)

    plateaus: List[Tuple[int, int, float]] = []
    seg_start = 0
    for idx in range(1, len(arr)):
        if abs(arr[idx] - arr[idx - 1]) <= tol:
            continue
        seg_end = idx - 1
        if seg_end - seg_start + 1 >= 2:
            segment = arr[seg_start : seg_end + 1]
            plateaus.append((seg_start, seg_end, statistics.mean(segment)))
        seg_start = idx

    if len(arr) - seg_start >= 2:
        seg = arr[seg_start:]
        plateaus.append((seg_start, len(arr) - 1, statistics.mean(seg)))

    jumps = [abs(arr[i] - arr[i - 1]) for i in range(1, len(arr)) if abs(arr[i] - arr[i - 1]) >= jump_threshold]
    levels = _cluster_levels([p[2] for p in plateaus], tol=max(22.0, tol * 1.5))

    return len(plateaus), levels, len(jumps), (max(jumps) if jumps else 0.0)


def _resample_profile(values: Sequence[float], target_len: int = 24) -> List[float]:
    if not values:
        return [0.0] * target_len
    if len(values) == target_len:
        return [round(v, 2) for v in values]

    out: List[float] = []
    n = len(values)
    for i in range(target_len):
        pos = (i * (n - 1)) / max(1, target_len - 1)
        lo = int(math.floor(pos))
        hi = min(n - 1, lo + 1)
        alpha = pos - lo
        val = values[lo] * (1.0 - alpha) + values[hi] * alpha
        out.append(round(val, 2))
    return out


def _median_dt(samples: Sequence[Sample]) -> float:
    if len(samples) < 2:
        return 1.0
    diffs = [samples[i].t - samples[i - 1].t for i in range(1, len(samples))]
    diffs = [d for d in diffs if d > 0]
    if not diffs:
        return 1.0
    return max(0.1, statistics.median(diffs))


def extract_event_features(events: Sequence[Event], phase: str = "unknown") -> List[EventFeatures]:
    results: List[EventFeatures] = []

    for ev in events:
        powers = [s.power_w - ev.baseline_w for s in ev.samples]
        powers = [max(0.0, p) for p in powers]
        if not powers:
            continue

        dt = _median_dt(ev.samples)
        duration = max(dt, ev.end_t - ev.start_t + dt)
        avg_power = statistics.mean(powers)
        peak_power = max(powers)
        energy = sum(p * dt for p in powers) / 3600.0

        variance = statistics.pvariance(powers) if len(powers) > 1 else 0.0
        std = math.sqrt(max(0.0, variance))

        plateau_count, dominant_levels, jump_count, largest_jump = _detect_plateaus_and_jumps(powers)

        peak_idx = powers.index(peak_power)
        rise_time = max(dt, ev.samples[peak_idx].t - ev.samples[0].t)
        fall_time = max(dt, ev.samples[-1].t - ev.samples[peak_idx].t)

        rise_rate = (peak_power - powers[0]) / rise_time
        fall_rate = (powers[-1] - peak_power) / fall_time

        profile = _resample_profile(powers, target_len=32)
        peak_to_avg = peak_power / avg_power if avg_power > 1e-9 else 1.0

        results.append(
            EventFeatures(
                event_id=ev.event_id,
                start_t=ev.start_t,
                end_t=ev.end_t,
                duration_s=duration,
                avg_power_w=avg_power,
                peak_power_w=peak_power,
                energy_wh=energy,
                power_std=std,
                power_variance=variance,
                plateau_count=plateau_count,
                dominant_levels_w=dominant_levels,
                jump_count=jump_count,
                largest_jump_w=largest_jump,
                rise_rate_w_per_s=rise_rate,
                fall_rate_w_per_s=fall_rate,
                peak_to_avg_ratio=peak_to_avg,
                profile_points=profile,
                phase=phase,
            )
        )

    return results


def _infer_label(raw: str) -> str:
    text = (raw or "").strip().lower()
    aliases = {
        "kuehlschrank": "fridge",
        "kuhlschrank": "fridge",
        "wasserkocher": "kettle",
        "mikrowelle": "microwave",
        "ofen": "oven",
        "heizung": "heater",
        "waermepumpe": "pump",
    }
    if text in aliases:
        return aliases[text]
    for t in DEVICE_TYPES:
        if t in text:
            return t
    return text if text else "unknown"


def _load_existing_patterns(patterns: Sequence[Dict[str, Any]]) -> List[PatternState]:
    states: List[PatternState] = []
    for idx, p in enumerate(patterns):
        if not isinstance(p, dict):
            continue
        pattern_id = str(p.get("id") or p.get("pattern_id") or f"pat_{idx:05d}")
        candidate = _infer_label(str(p.get("candidate_name") or p.get("suggestion_type") or "unknown"))

        profile = _extract_profile_values(p.get("profile_points"))
        profile = _resample_profile(profile, target_len=32) if profile else [0.0] * 32

        state = PatternState(
            pattern_id=pattern_id,
            seen_count=max(1, _safe_int(p.get("seen_count"), 1)),
            avg_power_w=max(0.0, _safe_float(p.get("avg_power_w"), 0.0)),
            peak_power_w=max(0.0, _safe_float(p.get("peak_power_w"), 0.0)),
            duration_s=max(1.0, _safe_float(p.get("duration_s"), 1.0)),
            energy_wh=max(0.0, _safe_float(p.get("energy_wh"), 0.0)),
            power_variance=max(0.0, _safe_float(p.get("power_variance"), 0.0)),
            power_std=math.sqrt(max(0.0, _safe_float(p.get("power_variance"), 0.0))),
            plateau_count=max(0, _safe_int(p.get("num_substates"), 0)),
            dominant_levels_w=[],
            jump_count=max(0, _safe_int(p.get("num_substates"), 0)),
            rise_rate_w_per_s=_safe_float(p.get("rise_rate_w_per_s"), 0.0),
            fall_rate_w_per_s=_safe_float(p.get("fall_rate_w_per_s"), 0.0),
            peak_to_avg_ratio=max(0.0, _safe_float(p.get("peak_to_avg_ratio"), 1.0)),
            stability_score=_clamp(_safe_float(p.get("stability_score"), 0.4), 0.0, 1.0),
            confidence_score=_clamp(_safe_float(p.get("confidence_score"), 0.45), 0.0, 1.0),
            candidate_name=candidate,
            suggestion_type=str(p.get("suggestion_type") or candidate or "unknown"),
            phase=str(p.get("phase") or "unknown"),
            profile_points=profile,
            event_times=[],
        )
        states.append(state)
    return states


def _profile_distance(a: Sequence[float], b: Sequence[float]) -> float:
    aa = _resample_profile(a, 24)
    bb = _resample_profile(b, 24)
    if not aa or not bb:
        return 1.0
    scale = max(80.0, statistics.mean(aa) if aa else 80.0, statistics.mean(bb) if bb else 80.0)
    mad = statistics.mean(abs(x - y) for x, y in zip(aa, bb))
    return mad / scale


def _event_pattern_distance(f: EventFeatures, p: PatternState) -> float:
    avg_ref = max(80.0, p.avg_power_w)
    dur_ref = max(30.0, p.duration_s)

    avg_diff = abs(f.avg_power_w - p.avg_power_w) / avg_ref
    dur_diff = abs(f.duration_s - p.duration_s) / dur_ref
    shape_diff = _profile_distance(f.profile_points, p.profile_points)
    plateau_diff = min(1.0, abs(f.plateau_count - p.plateau_count) / 4.0)

    return 0.4 * avg_diff + 0.25 * dur_diff + 0.25 * shape_diff + 0.10 * plateau_diff


def _is_compatible(f: EventFeatures, p: PatternState) -> bool:
    avg_ref = max(80.0, p.avg_power_w)
    dur_ref = max(30.0, p.duration_s)
    avg_ok = abs(f.avg_power_w - p.avg_power_w) <= avg_ref * 0.15
    dur_ok = abs(f.duration_s - p.duration_s) <= dur_ref * 0.5
    plateau_ok = abs(f.plateau_count - p.plateau_count) <= 2
    return avg_ok and dur_ok and plateau_ok


def _weighted_update(old: float, new: float, seen_count: int) -> float:
    w_old = max(1, seen_count)
    return ((old * w_old) + new) / (w_old + 1)


def _blend_profiles(old_profile: Sequence[float], new_profile: Sequence[float], alpha: float = 0.25) -> List[float]:
    old_r = _resample_profile(old_profile, 32)
    new_r = _resample_profile(new_profile, 32)
    out = [round((1.0 - alpha) * o + alpha * n, 2) for o, n in zip(old_r, new_r)]
    return out


def cluster_and_update_patterns(
    event_features: Sequence[EventFeatures],
    existing_patterns: Sequence[Dict[str, Any]],
) -> Tuple[List[PatternState], Dict[str, str], int, int]:
    patterns = _load_existing_patterns(existing_patterns)
    event_to_pattern: Dict[str, str] = {}
    merged = 0
    new_count = 0

    for f in event_features:
        best_idx = -1
        best_distance = 999.0

        for idx, p in enumerate(patterns):
            if not _is_compatible(f, p):
                continue
            d = _event_pattern_distance(f, p)
            if d < best_distance:
                best_idx = idx
                best_distance = d

        if best_idx >= 0 and best_distance <= 0.85:
            p = patterns[best_idx]
            old_seen = p.seen_count
            p.seen_count += 1
            p.avg_power_w = _weighted_update(p.avg_power_w, f.avg_power_w, old_seen)
            p.peak_power_w = _weighted_update(p.peak_power_w, f.peak_power_w, old_seen)
            p.duration_s = _weighted_update(p.duration_s, f.duration_s, old_seen)
            p.energy_wh = _weighted_update(p.energy_wh, f.energy_wh, old_seen)
            p.power_variance = _weighted_update(p.power_variance, f.power_variance, old_seen)
            p.power_std = math.sqrt(max(0.0, p.power_variance))
            p.plateau_count = int(round(_weighted_update(float(p.plateau_count), float(f.plateau_count), old_seen)))
            p.jump_count = int(round(_weighted_update(float(p.jump_count), float(f.jump_count), old_seen)))
            p.rise_rate_w_per_s = _weighted_update(p.rise_rate_w_per_s, f.rise_rate_w_per_s, old_seen)
            p.fall_rate_w_per_s = _weighted_update(p.fall_rate_w_per_s, f.fall_rate_w_per_s, old_seen)
            p.peak_to_avg_ratio = _weighted_update(p.peak_to_avg_ratio, f.peak_to_avg_ratio, old_seen)
            p.profile_points = _blend_profiles(p.profile_points, f.profile_points, alpha=0.22)
            p.event_times.append(f.start_t)

            event_to_pattern[f.event_id] = p.pattern_id
            merged += 1
            continue

        new_pattern = PatternState(
            pattern_id=f"pat_new_{new_count:05d}",
            seen_count=1,
            avg_power_w=f.avg_power_w,
            peak_power_w=f.peak_power_w,
            duration_s=f.duration_s,
            energy_wh=f.energy_wh,
            power_variance=f.power_variance,
            power_std=f.power_std,
            plateau_count=f.plateau_count,
            dominant_levels_w=f.dominant_levels_w,
            jump_count=f.jump_count,
            rise_rate_w_per_s=f.rise_rate_w_per_s,
            fall_rate_w_per_s=f.fall_rate_w_per_s,
            peak_to_avg_ratio=f.peak_to_avg_ratio,
            stability_score=0.45,
            confidence_score=0.42,
            candidate_name="unknown",
            suggestion_type="auto_clustered",
            phase=f.phase,
            profile_points=f.profile_points,
            event_times=[f.start_t],
        )
        patterns.append(new_pattern)
        event_to_pattern[f.event_id] = new_pattern.pattern_id
        new_count += 1

    _refresh_pattern_temporal_stats(patterns)
    return patterns, event_to_pattern, new_count, merged


def _refresh_pattern_temporal_stats(patterns: Sequence[PatternState]) -> None:
    for p in patterns:
        if len(p.event_times) >= 2:
            spans = [p.event_times[i] - p.event_times[i - 1] for i in range(1, len(p.event_times))]
            valid = [s for s in spans if s > 0]
            if valid:
                typical = statistics.median(valid)
                p.frequency_per_day = 86400.0 / typical if typical > 0 else 0.0
            else:
                p.frequency_per_day = 0.0
        else:
            p.frequency_per_day = 0.0


def _repeatability_score(p: PatternState) -> float:
    seen_component = _clamp(p.seen_count / 12.0, 0.0, 1.0)
    variance_component = _clamp(1.0 - (p.power_std / max(70.0, p.avg_power_w)), 0.0, 1.0)
    frequency_component = _clamp(p.frequency_per_day / 8.0, 0.0, 1.0)
    return 0.45 * seen_component + 0.35 * variance_component + 0.20 * frequency_component


def _plausibility_by_device(p: PatternState) -> Dict[str, float]:
    power = p.avg_power_w
    duration = p.duration_s
    cv = p.power_std / max(1.0, p.avg_power_w)
    rep = _repeatability_score(p)

    scores: Dict[str, float] = {}

    fridge = 0.5
    fridge += 0.2 if 70 <= power <= 350 else -0.18
    fridge += 0.18 if 300 <= duration <= 3600 else -0.15
    fridge += 0.1 if cv <= 0.25 else -0.08
    fridge += 0.08 if rep >= 0.5 else -0.05
    scores["fridge"] = _clamp(fridge, 0.0, 1.0)

    pump = 0.5
    pump += 0.2 if 120 <= power <= 1800 else -0.15
    pump += 0.16 if 45 <= duration <= 5400 else -0.12
    pump += 0.16 if cv <= 0.2 else -0.1
    scores["pump"] = _clamp(pump, 0.0, 1.0)

    kettle = 0.5
    kettle += 0.24 if 1200 <= power <= 3200 else -0.26
    kettle += 0.22 if 20 <= duration <= 420 else -0.28
    kettle += 0.08 if p.plateau_count <= 2 else -0.08
    scores["kettle"] = _clamp(kettle, 0.0, 1.0)

    microwave = 0.5
    microwave += 0.2 if 700 <= power <= 2200 else -0.18
    microwave += 0.16 if 30 <= duration <= 1800 else -0.2
    microwave += 0.06 if p.plateau_count <= 3 else -0.05
    scores["microwave"] = _clamp(microwave, 0.0, 1.0)

    oven = 0.5
    oven += 0.2 if 900 <= power <= 4200 else -0.15
    oven += 0.2 if 600 <= duration <= 14400 else -0.16
    oven += 0.1 if p.plateau_count >= 2 else -0.06
    scores["oven"] = _clamp(oven, 0.0, 1.0)

    heater = 0.5
    heater += 0.18 if 400 <= power <= 3500 else -0.14
    heater += 0.2 if duration >= 300 else -0.18
    heater += 0.1 if p.peak_to_avg_ratio <= 1.45 else -0.08
    scores["heater"] = _clamp(heater, 0.0, 1.0)

    return scores


def _build_reason(p: PatternState, quality: str, label_plausibility: float, best_type: str) -> str:
    parts: List[str] = []

    if p.seen_count >= 6:
        parts.append(f"{p.seen_count} Wiederholungen")
    elif p.seen_count <= 2:
        parts.append("Wenige Wiederholungen")

    cv = p.power_std / max(1.0, p.avg_power_w)
    if cv <= 0.2:
        parts.append("sehr stabil")
    elif cv > 0.6:
        parts.append("stark schwankend")

    if p.plateau_count >= 4:
        parts.append("mehrere Plateaus, moegliche Mischlast")

    if p.candidate_name in DEVICE_TYPES and label_plausibility < 0.45:
        parts.append(f"Leistung/Dauer unplausibel fuer {p.candidate_name}")

    if p.candidate_name not in DEVICE_TYPES and best_type in DEVICE_TYPES:
        parts.append(f"wahrscheinlicher Typ: {best_type}")

    if quality == "verwerfen":
        parts.append("zu unsicher fuer verlaessliches Label")

    if not parts:
        parts.append("keine starken Gegenindizien, moderate Qualitaet")

    return "; ".join(parts)


def evaluate_patterns(patterns: Sequence[PatternState]) -> Tuple[List[PatternState], int]:
    rejected = 0

    for p in patterns:
        rep = _repeatability_score(p)
        cv = p.power_std / max(1.0, p.avg_power_w)

        stability = _clamp(1.0 - cv, 0.0, 1.0)
        p.stability_score = round((0.55 * stability + 0.45 * rep), 4)

        plaus = _plausibility_by_device(p)
        best_type = max(plaus, key=lambda k: plaus[k])
        label_plaus = plaus.get(p.candidate_name, 0.35)

        if p.candidate_name in DEVICE_TYPES and label_plaus < 0.42:
            p.confidence_score *= 0.72
        else:
            p.confidence_score = _clamp((p.confidence_score * 0.7) + (plaus[best_type] * 0.3), 0.0, 1.0)

        score = 0.0
        score += 0.28 if p.seen_count >= 7 else (0.16 if p.seen_count >= 4 else -0.12)
        score += (p.stability_score - 0.5) * 0.5
        score += (plaus[best_type] - 0.5) * 0.7
        score += (p.confidence_score - 0.5) * 0.6
        if p.plateau_count >= 5 and p.jump_count >= 7:
            score -= 0.2

        if score >= 0.55 and p.confidence_score >= 0.65:
            quality = "sehr_gut"
        elif score >= 0.2 and p.confidence_score >= 0.45:
            quality = "brauchbar"
        elif score >= -0.1 and p.confidence_score >= 0.25:
            quality = "unsicher"
        else:
            quality = "verwerfen"
            rejected += 1

        p.quality_label = quality
        p.alternative_hints = [dtype for dtype, s in sorted(plaus.items(), key=lambda x: x[1], reverse=True) if dtype != p.candidate_name and s >= 0.6][:3]
        p.quality_reason = _build_reason(p, quality, label_plaus, best_type)

        if p.candidate_name not in DEVICE_TYPES or label_plaus >= 0.55:
            p.suggestion_type = best_type

    return list(patterns), rejected


def _event_to_json(event: Event, feat: EventFeatures) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "start_t": event.start_t,
        "end_t": event.end_t,
        "duration_s": feat.duration_s,
        "baseline_w": event.baseline_w,
        "avg_power_w": feat.avg_power_w,
        "peak_power_w": feat.peak_power_w,
        "energy_wh": feat.energy_wh,
        "plateau_count": feat.plateau_count,
        "jump_count": feat.jump_count,
        "largest_jump_w": feat.largest_jump_w,
        "rise_rate_w_per_s": feat.rise_rate_w_per_s,
        "fall_rate_w_per_s": feat.fall_rate_w_per_s,
        "profile_points": feat.profile_points,
    }


def _pattern_to_json(p: PatternState) -> Dict[str, Any]:
    return {
        "pattern_id": p.pattern_id,
        "seen_count": p.seen_count,
        "avg_power_w": round(p.avg_power_w, 4),
        "peak_power_w": round(p.peak_power_w, 4),
        "duration_s": round(p.duration_s, 4),
        "energy_wh": round(p.energy_wh, 4),
        "power_variance": round(p.power_variance, 6),
        "power_std": round(p.power_std, 6),
        "plateau_count": p.plateau_count,
        "dominant_levels_w": p.dominant_levels_w,
        "jump_count": p.jump_count,
        "rise_rate_w_per_s": round(p.rise_rate_w_per_s, 6),
        "fall_rate_w_per_s": round(p.fall_rate_w_per_s, 6),
        "peak_to_avg_ratio": round(p.peak_to_avg_ratio, 6),
        "stability_score": p.stability_score,
        "confidence_score": round(p.confidence_score, 6),
        "frequency_per_day": round(p.frequency_per_day, 6),
        "candidate_name": p.candidate_name,
        "suggestion_type": p.suggestion_type,
        "phase": p.phase,
        "quality_label": p.quality_label,
        "quality_reason": p.quality_reason,
        "alternative_hints": p.alternative_hints,
        "profile_points": p.profile_points,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_features_csv(path: Path, features: Sequence[EventFeatures], event_to_pattern: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_id",
        "pattern_id",
        "start_t",
        "end_t",
        "duration_s",
        "avg_power_w",
        "peak_power_w",
        "energy_wh",
        "power_std",
        "power_variance",
        "plateau_count",
        "dominant_levels_w",
        "jump_count",
        "largest_jump_w",
        "rise_rate_w_per_s",
        "fall_rate_w_per_s",
        "peak_to_avg_ratio",
        "phase",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in features:
            writer.writerow(
                {
                    "event_id": row.event_id,
                    "pattern_id": event_to_pattern.get(row.event_id, ""),
                    "start_t": row.start_t,
                    "end_t": row.end_t,
                    "duration_s": row.duration_s,
                    "avg_power_w": row.avg_power_w,
                    "peak_power_w": row.peak_power_w,
                    "energy_wh": row.energy_wh,
                    "power_std": row.power_std,
                    "power_variance": row.power_variance,
                    "plateau_count": row.plateau_count,
                    "dominant_levels_w": "|".join(str(v) for v in row.dominant_levels_w),
                    "jump_count": row.jump_count,
                    "largest_jump_w": row.largest_jump_w,
                    "rise_rate_w_per_s": row.rise_rate_w_per_s,
                    "fall_rate_w_per_s": row.fall_rate_w_per_s,
                    "peak_to_avg_ratio": row.peak_to_avg_ratio,
                    "phase": row.phase,
                }
            )


def write_dataset_jsonl(path: Path, features: Sequence[EventFeatures], event_to_pattern: Dict[str, str], patterns: Sequence[PatternState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pattern_map = {p.pattern_id: p for p in patterns}
    with path.open("w", encoding="utf-8") as f:
        for feat in features:
            pid = event_to_pattern.get(feat.event_id, "")
            p = pattern_map.get(pid)
            row = {
                "event_id": feat.event_id,
                "pattern_id": pid,
                "target_candidate": p.candidate_name if p else "unknown",
                "target_quality": p.quality_label if p else "unsicher",
                "features": {
                    "avg_power_w": feat.avg_power_w,
                    "peak_power_w": feat.peak_power_w,
                    "duration_s": feat.duration_s,
                    "energy_wh": feat.energy_wh,
                    "power_std": feat.power_std,
                    "power_variance": feat.power_variance,
                    "plateau_count": feat.plateau_count,
                    "jump_count": feat.jump_count,
                    "largest_jump_w": feat.largest_jump_w,
                    "rise_rate_w_per_s": feat.rise_rate_w_per_s,
                    "fall_rate_w_per_s": feat.fall_rate_w_per_s,
                    "peak_to_avg_ratio": feat.peak_to_avg_ratio,
                },
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    threshold_w: float,
    min_duration_s: float,
    gap_merge_s: float,
) -> Dict[str, Any]:
    loaded = load_input(input_path)
    raw_patterns = loaded.get("patterns")
    patterns_input: List[Dict[str, Any]] = []
    if isinstance(raw_patterns, list):
        patterns_input = [p for p in raw_patterns if isinstance(p, dict)]

    raw_samples, source = build_raw_samples(loaded)

    events = detect_events(
        samples=raw_samples,
        threshold_w=threshold_w,
        min_duration_s=min_duration_s,
        gap_merge_s=gap_merge_s,
    )

    features = extract_event_features(events)
    updated_patterns, event_to_pattern, new_patterns, merged_patterns = cluster_and_update_patterns(features, patterns_input)
    updated_patterns, rejected_patterns = evaluate_patterns(updated_patterns)

    event_lookup = {ev.event_id: ev for ev in events}
    events_json = [_event_to_json(event_lookup[f.event_id], f) for f in features if f.event_id in event_lookup]
    patterns_json = [_pattern_to_json(p) for p in updated_patterns]

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "events_detected.json", events_json)
    write_json(output_dir / "patterns_updated.json", patterns_json)
    write_features_csv(output_dir / "features.csv", features, event_to_pattern)
    write_dataset_jsonl(output_dir / "dataset.jsonl", features, event_to_pattern, updated_patterns)

    quality_counts = Counter(p.quality_label for p in updated_patterns)

    summary = {
        "input_source": source,
        "raw_samples": len(raw_samples),
        "events_detected": len(events_json),
        "patterns_total": len(updated_patterns),
        "patterns_new": new_patterns,
        "patterns_merged": merged_patterns,
        "patterns_rejected": rejected_patterns,
        "quality_counts": dict(quality_counts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ml_ready": {
            "dataset_jsonl": str((output_dir / "dataset.jsonl").name),
            "next": [
                "train_test_split on event-level rows",
                "baseline model with sklearn RandomForest",
                "optional switch to XGBoost after label curation",
            ],
        },
    }

    write_json(output_dir / "summary.json", summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NILM learning pipeline")
    parser.add_argument("input", type=Path, help="Input JSON with readings and/or patterns")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    parser.add_argument("--threshold", type=float, default=25.0, help="Event threshold above baseline in W")
    parser.add_argument("--min-duration", type=float, default=8.0, help="Minimum event duration in seconds")
    parser.add_argument("--gap-merge", type=float, default=6.0, help="Merge neighboring events if gap <= seconds")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        summary = run_pipeline(
            input_path=args.input,
            output_dir=args.out,
            threshold_w=max(1.0, args.threshold),
            min_duration_s=max(1.0, args.min_duration),
            gap_merge_s=max(0.0, args.gap_merge),
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        return 1

    print(f"Input source: {summary['input_source']}")
    print(f"Raw samples: {summary['raw_samples']}")
    print(f"Events detected: {summary['events_detected']}")
    print(f"Patterns new: {summary['patterns_new']}")
    print(f"Patterns merged: {summary['patterns_merged']}")
    print(f"Patterns rejected: {summary['patterns_rejected']}")
    print("Quality:")
    for q in QUALITY_LABELS:
        print(f"  - {q}: {summary['quality_counts'].get(q, 0)}")
    print("Outputs:")
    print("  - patterns_updated.json")
    print("  - events_detected.json")
    print("  - features.csv")
    print("  - dataset.jsonl")
    print("  - summary.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
