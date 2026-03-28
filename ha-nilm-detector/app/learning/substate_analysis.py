"""Substate and transition analysis for NILM events/patterns."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import List, Sequence

from app.learning.shape_similarity import normalize_profile_points


@dataclass
class SubstateSummary:
    plateau_count: int
    num_substates: int
    dominant_power_levels: List[float]
    step_count: int
    max_step_w: float
    avg_step_w: float
    state_transition_count: int
    substate_durations: List[float]
    substate_power_levels: List[float]


def analyze_profile_substates(profile_points: object) -> SubstateSummary:
    values = normalize_profile_points(profile_points)
    if len(values) < 3:
        return SubstateSummary(
            plateau_count=0,
            num_substates=0,
            dominant_power_levels=[],
            step_count=0,
            max_step_w=0.0,
            avg_step_w=0.0,
            state_transition_count=0,
            substate_durations=[],
            substate_power_levels=[],
        )

    baseline = median(values)
    plateau_tol = max(12.0, abs(baseline) * 0.08)
    step_threshold = max(20.0, max(values) * 0.1)

    segments: List[tuple[int, int, float]] = []
    start = 0
    for idx in range(1, len(values)):
        if abs(values[idx] - values[idx - 1]) <= plateau_tol:
            continue
        end = idx - 1
        if end - start + 1 >= 2:
            seg = values[start : end + 1]
            segments.append((start, end, mean(seg)))
        start = idx

    if len(values) - start >= 2:
        seg = values[start:]
        segments.append((start, len(values) - 1, mean(seg)))

    jump_values: List[float] = []
    for idx in range(1, len(values)):
        delta = abs(values[idx] - values[idx - 1])
        if delta >= step_threshold:
            jump_values.append(delta)

    dominant = _cluster_levels([seg[2] for seg in segments], tol=max(18.0, plateau_tol * 1.4))
    durations = [float((seg[1] - seg[0] + 1)) for seg in segments]
    power_levels = [float(seg[2]) for seg in segments]

    step_count = len(jump_values)
    avg_step = sum(jump_values) / step_count if step_count else 0.0

    return SubstateSummary(
        plateau_count=len(segments),
        num_substates=len(dominant),
        dominant_power_levels=[round(v, 2) for v in dominant],
        step_count=step_count,
        max_step_w=max(jump_values) if jump_values else 0.0,
        avg_step_w=avg_step,
        state_transition_count=max(0, len(segments) - 1),
        substate_durations=[round(v, 3) for v in durations],
        substate_power_levels=[round(v, 3) for v in power_levels],
    )


def _cluster_levels(levels: Sequence[float], tol: float) -> List[float]:
    if not levels:
        return []
    sorted_levels = sorted(float(v) for v in levels)
    clusters: List[List[float]] = [[sorted_levels[0]]]
    for level in sorted_levels[1:]:
        center = sum(clusters[-1]) / len(clusters[-1])
        if abs(level - center) <= tol:
            clusters[-1].append(level)
        else:
            clusters.append([level])
    return [sum(cluster) / len(cluster) for cluster in clusters]
