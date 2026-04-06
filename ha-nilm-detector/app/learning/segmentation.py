"""Segmentation helpers that normalize completed cycle payloads for storage.

The goal is to keep start/end truncation, pre-roll/post-roll context, and
waveform exports explicit so classification can reason about incomplete windows.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _serialize_samples(samples: Iterable[Any], start_ts: Any = None, duration_hint_s: float = 0.0) -> List[Dict[str, float]]:
    base_ts = getattr(start_ts, "timestamp", None)
    if callable(base_ts):
        base = start_ts
    else:
        base = None
    out: List[Dict[str, float]] = []
    raw = list(samples or [])
    if not raw:
        return out
    if base is None:
        base = getattr(raw[0], "timestamp", None)
    total_duration = max(float(duration_hint_s or 0.0), 1.0)
    for idx, sample in enumerate(raw):
        ts = getattr(sample, "timestamp", None)
        t_s = 0.0
        if ts is not None and base is not None:
            try:
                t_s = max((ts - base).total_seconds(), 0.0)
            except Exception:
                t_s = float(idx)
        else:
            t_s = float(idx)
        out.append(
            {
                "t_s": round(t_s, 3),
                "t_norm": round(min(max(t_s / total_duration, 0.0), 1.0), 6),
                "power_w": round(float(getattr(sample, "power_w", 0.0) or 0.0), 3),
            }
        )
    if out and out[-1]["t_s"] > 0.0:
        end = out[-1]["t_s"]
        for item in out:
            item["t_norm"] = round(min(max(item["t_s"] / max(end, 1.0), 0.0), 1.0), 6)
    return out


def build_segmentation_payload(cycle: Any) -> Dict[str, Any]:
    event_samples = list(getattr(cycle, "event_samples", []) or [])
    pre_roll_samples = list(getattr(cycle, "pre_roll_samples", []) or [])
    post_roll_samples = list(getattr(cycle, "post_roll_samples", []) or [])
    start_ts = getattr(cycle, "start_ts", None)
    duration_s = float(getattr(cycle, "duration_s", 0.0) or 0.0)
    full_samples = pre_roll_samples + event_samples + post_roll_samples
    return {
        "profile_points": _serialize_samples(event_samples, start_ts=start_ts, duration_hint_s=duration_s),
        "waveform_points": _serialize_samples(full_samples, start_ts=(pre_roll_samples[0].timestamp if pre_roll_samples else start_ts), duration_hint_s=max(duration_s + 4.0, duration_s)),
        "pre_roll_samples": _serialize_samples(pre_roll_samples, start_ts=(pre_roll_samples[0].timestamp if pre_roll_samples else start_ts), duration_hint_s=max(float(getattr(cycle, "pre_roll_duration_s", 0.0) or 0.0), 1.0)),
        "post_roll_samples": _serialize_samples(post_roll_samples, start_ts=(post_roll_samples[0].timestamp if post_roll_samples else start_ts), duration_hint_s=max(float(getattr(cycle, "post_roll_duration_s", 0.0) or 0.0), 1.0)),
        "segmentation_flags": dict(getattr(cycle, "segmentation_flags", {}) or {}),
        "truncated_start": bool(getattr(cycle, "truncated_start", False)),
        "truncated_end": bool(getattr(cycle, "truncated_end", False)),
        "pre_roll_duration_s": float(getattr(cycle, "pre_roll_duration_s", 0.0) or 0.0),
        "post_roll_duration_s": float(getattr(cycle, "post_roll_duration_s", 0.0) or 0.0),
    }