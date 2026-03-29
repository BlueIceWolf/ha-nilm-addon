"""Signal overlap helpers for separating strong and weak sub-events.

This module provides a conservative two-pass event decomposition:
1) detect strong segments in the original signal,
2) subtract strong influence,
3) detect weaker segments in the residual signal.
"""

from __future__ import annotations

from typing import Dict, Iterable, List


def _extract_signal(samples: Iterable[object]) -> List[float]:
    out: List[float] = []
    for item in samples or []:
        value = None
        if isinstance(item, (int, float)):
            value = float(item)
        elif isinstance(item, dict):
            raw = item.get("power_w")
            if isinstance(raw, (int, float)):
                value = float(raw)
        if value is None:
            continue
        out.append(max(value, 0.0))
    return out


def _detect_segments(signal: List[float], threshold_w: float, min_len: int = 2) -> List[Dict[str, float]]:
    events: List[Dict[str, float]] = []
    start = -1
    for idx, value in enumerate(signal):
        if value >= threshold_w:
            if start < 0:
                start = idx
            continue
        if start >= 0:
            end = idx - 1
            if end - start + 1 >= min_len:
                seg = signal[start : end + 1]
                events.append(
                    {
                        "start_idx": float(start),
                        "end_idx": float(end),
                        "peak_w": max(seg),
                        "energy": sum(seg),
                    }
                )
            start = -1

    if start >= 0:
        end = len(signal) - 1
        if end - start + 1 >= min_len:
            seg = signal[start : end + 1]
            events.append(
                {
                    "start_idx": float(start),
                    "end_idx": float(end),
                    "peak_w": max(seg),
                    "energy": sum(seg),
                }
            )
    return events


def detect_strong(signal: List[float]) -> List[Dict[str, float]]:
    if not signal:
        return []
    peak = max(signal)
    threshold = max(40.0, peak * 0.55)
    return _detect_segments(signal, threshold_w=threshold, min_len=2)


def subtract(signal: List[float], strong_events: List[Dict[str, float]]) -> List[float]:
    residual = list(signal)
    if not residual:
        return residual

    for ev in strong_events:
        start = int(ev.get("start_idx", -1))
        end = int(ev.get("end_idx", -1))
        if start < 0 or end < start:
            continue
        span = residual[start : end + 1]
        if not span:
            continue
        # Remove most of strong component but keep a small residue so weak events
        # nested within the strong span can still be identified.
        baseline = min(span)
        attenuation = max((max(span) - baseline) * 0.75, 0.0)
        for i in range(start, min(end + 1, len(residual))):
            residual[i] = max(residual[i] - attenuation, 0.0)

    return residual


def detect_weak(signal: List[float]) -> List[Dict[str, float]]:
    if not signal:
        return []
    peak = max(signal)
    threshold = max(15.0, peak * 0.30)
    return _detect_segments(signal, threshold_w=threshold, min_len=2)


def process_signal(samples: Iterable[object]) -> List[Dict[str, float]]:
    """Detect overlapping events in two passes (strong then weak)."""
    signal = _extract_signal(samples)
    strong_events = detect_strong(signal)
    cleaned_signal = subtract(signal, strong_events)
    weak_events = detect_weak(cleaned_signal)
    return strong_events + weak_events


def estimate_overlap_score(samples: Iterable[object]) -> float:
    """Return overlap score in [0,1] based on weak-vs-total event energy."""
    signal = _extract_signal(samples)
    if len(signal) < 4:
        return 0.0

    strong_events = detect_strong(signal)
    if not strong_events:
        return 0.0

    residual = subtract(signal, strong_events)
    weak_events = detect_weak(residual)

    strong_energy = sum(float(ev.get("energy", 0.0)) for ev in strong_events)
    weak_energy = sum(float(ev.get("energy", 0.0)) for ev in weak_events)
    total = strong_energy + weak_energy
    if total <= 0.0:
        return 0.0

    # Weight weak contribution higher to better flag multi-device overlap.
    score = min(max((weak_energy / total) * 1.6, 0.0), 1.0)
    return float(round(score, 3))
