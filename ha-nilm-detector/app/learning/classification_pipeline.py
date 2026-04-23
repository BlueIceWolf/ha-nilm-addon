"""Structured NILM learning helpers for staged feature extraction and labeling.

This module keeps the richer NILM event representation separate from storage so
segmentation, heuristics, shape matching, and temporal scoring can evolve
without turning SQLiteStore into one large rule block.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

from app.learning.shape_similarity import dtw_similarity, euclidean_similarity, normalize_profile_points
from app.utils.logging import get_logger


EPSILON = 1e-6
logger = get_logger(__name__)


@dataclass
class ShapeMatchScore:
    label: str
    score: float
    distance: float
    euclidean: float
    dtw: float
    pattern_id: int | None
    cluster_id: str
    reasons: List[str]
    valid: bool = True


@dataclass
class TemporalContextScore:
    recurrence_interval_s: float
    similarity_to_previous: float
    hour_of_day_score: float
    typical_run_duration_s: float
    occurrence_count: int
    score: float
    reasons: List[str]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except Exception:
        pass
    return float(default)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(float(value), upper))


def parse_shape_signature(raw: Any) -> List[float]:
    if isinstance(raw, list):
        return [safe_float(item) for item in raw]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [safe_float(item) for item in parsed]


def _resample_profile(points: object, fallback_shape_signature: Any = None, sample_count: int = 32) -> List[float]:
    values = normalize_profile_points(points)
    if not values:
        values = parse_shape_signature(fallback_shape_signature)
    if not values:
        return []
    if len(values) == sample_count:
        return [float(v) for v in values]
    if len(values) == 1:
        return [float(values[0])] * sample_count

    out: List[float] = []
    last = len(values) - 1
    for idx in range(sample_count):
        position = (idx * last) / max(sample_count - 1, 1)
        lo = int(math.floor(position))
        hi = min(last, lo + 1)
        alpha = position - lo
        interpolated = (values[lo] * (1.0 - alpha)) + (values[hi] * alpha)
        out.append(float(interpolated))
    return out


def _duration_bucket(duration_s: float) -> str:
    if duration_s < 20.0:
        return "short"
    if duration_s < 180.0:
        return "medium"
    if duration_s < 1800.0:
        return "long"
    return "very_long"


def _load_level_bucket(avg_power_w: float) -> str:
    if avg_power_w < 40.0:
        return "very_low"
    if avg_power_w < 150.0:
        return "low"
    if avg_power_w < 800.0:
        return "medium"
    if avg_power_w < 2200.0:
        return "high"
    return "very_high"


def _tail_slope(points: Sequence[Dict[str, float]]) -> float:
    if len(points) < 2:
        return 0.0
    start_idx = max(0, int(len(points) * 0.7) - 1)
    start = points[start_idx]
    end = points[-1]
    dt = max(safe_float(end.get("t_s")) - safe_float(start.get("t_s")), 1.0)
    return (safe_float(end.get("power_w")) - safe_float(start.get("power_w"))) / dt


def _peak_position(points: Sequence[Dict[str, float]]) -> float:
    if not points:
        return 0.0
    peak_idx = max(range(len(points)), key=lambda idx: safe_float(points[idx].get("power_w")))
    return peak_idx / max(len(points) - 1, 1)


def _plateau_stability(points: Sequence[Dict[str, float]]) -> float:
    if not points:
        return 0.0
    start_idx = min(len(points) - 1, max(int(len(points) * 0.6), 0))
    tail = [safe_float(item.get("power_w")) for item in points[start_idx:]]
    if not tail:
        return 0.0
    avg = sum(tail) / max(len(tail), 1)
    variance = sum((item - avg) ** 2 for item in tail) / max(len(tail), 1)
    return math.sqrt(max(variance, 0.0))


def _point_powers(points: Sequence[Dict[str, Any]]) -> List[float]:
    return [safe_float(point.get("power_w")) for point in points if isinstance(point, dict)]


def _baseline_visible(points: Sequence[Dict[str, Any]], baseline_w: float) -> bool:
    values = _point_powers(points)
    if len(values) < 2:
        return False
    tolerance = max(abs(baseline_w) * 0.15, 12.0)
    median_like = sorted(values)[len(values) // 2]
    return abs(median_like - baseline_w) <= tolerance


def _baseline_edge_visible(points: Sequence[Dict[str, Any]], baseline_w: float, *, from_start: bool) -> bool:
    values = _point_powers(points[:2] if from_start else points[-2:])
    if not values:
        return False
    tolerance = max(abs(baseline_w) * 0.15, 12.0)
    return min(abs(value - baseline_w) for value in values) <= tolerance


def _shape_signature_meta(cycle: Dict[str, Any]) -> Dict[str, Any]:
    signature = str(cycle.get("shape_signature") or "").strip()
    waveform_points = list(cycle.get("waveform_points") or [])
    sample_count = len(waveform_points)
    if signature:
        parsed = parse_shape_signature(signature)
        if len(parsed) >= 8:
            return {
                "shape_signature_status": "valid",
                "shape_signature_reason": "waveform_signature_ready",
                "shape_signature_sample_count": len(parsed),
            }
        return {
            "shape_signature_status": "missing",
            "shape_signature_reason": "invalid_shape_signature_payload",
            "shape_signature_sample_count": len(parsed),
        }
    if sample_count >= 8:
        return {
            "shape_signature_status": "missing",
            "shape_signature_reason": "waveform_present_but_signature_missing",
            "shape_signature_sample_count": sample_count,
        }
    return {
        "shape_signature_status": "missing",
        "shape_signature_reason": "waveform_insufficient_samples",
        "shape_signature_sample_count": sample_count,
    }


def build_waveform_summary(cycle: Dict[str, Any]) -> Dict[str, Any]:
    waveform = list(cycle.get("waveform_points") or cycle.get("profile_points") or [])
    delta_points = list(cycle.get("delta_profile_points") or waveform)
    pre_roll = list(cycle.get("pre_roll_samples") or [])
    post_roll = list(cycle.get("post_roll_samples") or [])
    explicit_waveform = list(cycle.get("waveform_points") or [])
    profile_only_cycle = bool(waveform) and not explicit_waveform and not pre_roll and not post_roll
    baseline_before = safe_float(cycle.get("baseline_before_w", cycle.get("baseline_start_w", 0.0)))
    baseline_after = safe_float(cycle.get("baseline_after_w", cycle.get("baseline_end_w", baseline_before)))
    avg_power = max(safe_float(cycle.get("avg_power_w")), EPSILON)
    peak_power = safe_float(cycle.get("peak_power_w"), avg_power)
    variance = safe_float(cycle.get("power_variance"))
    rise_rate = safe_float(cycle.get("rise_rate_w_per_s"))
    fall_rate = safe_float(cycle.get("fall_rate_w_per_s"))
    inrush_ratio = peak_power / max(avg_power, EPSILON)
    normalized_variance = variance / max(avg_power, EPSILON)
    plateau_stability = _plateau_stability(delta_points or waveform)
    startup_sharpness = rise_rate / max(avg_power, EPSILON)
    shutdown_sharpness = fall_rate / max(avg_power, EPSILON)
    shape_peak_position = _peak_position(delta_points or waveform)
    shape_tail_slope = _tail_slope(delta_points or waveform)
    has_flat_plateau = plateau_stability <= max(avg_power * 0.08, 15.0)
    has_inrush_spike = inrush_ratio >= 1.35
    has_multi_stage_shape = int(cycle.get("num_substates", 0) or 0) >= 2 or int(cycle.get("step_count", 0) or 0) >= 2
    baseline_visible_before = _baseline_visible(pre_roll, baseline_before)
    baseline_visible_after = _baseline_visible(post_roll, baseline_after)
    if profile_only_cycle:
        baseline_visible_before = baseline_visible_before or _baseline_edge_visible(waveform, baseline_before, from_start=True)
        baseline_visible_after = baseline_visible_after or _baseline_edge_visible(waveform, baseline_after, from_start=False)
    startup_visible = baseline_visible_before and not bool(cycle.get("truncated_start", False))
    shutdown_visible = baseline_visible_after and not bool(cycle.get("truncated_end", False))
    duration_s = safe_float(cycle.get("duration_s"))
    sample_quality = clamp(len(waveform) / 18.0)
    synthetic_context_support = profile_only_cycle and startup_visible and shutdown_visible
    pre_roll_seconds = safe_float(cycle.get("pre_roll_duration_s"))
    post_roll_seconds = safe_float(cycle.get("post_roll_duration_s"))
    pre_roll_support = clamp(pre_roll_seconds / 3.0) if pre_roll_seconds > 0.0 else (0.85 if synthetic_context_support else 0.25)
    post_roll_support = clamp(post_roll_seconds / 3.0) if post_roll_seconds > 0.0 else (0.85 if synthetic_context_support else 0.25)
    startup_support = 1.0 if startup_visible else (0.55 if baseline_visible_before else 0.25)
    shutdown_support = 1.0 if shutdown_visible else (0.55 if baseline_visible_after else 0.25)
    plateau_duration_support = 1.0 if (has_flat_plateau and duration_s >= 90.0) else (0.78 if duration_s >= 45.0 else 0.55)
    waveform_completeness_score = clamp(
        (0.24 * pre_roll_support)
        + (0.24 * post_roll_support)
        + (0.18 * startup_support)
        + (0.18 * shutdown_support)
        + (0.16 * sample_quality)
    )
    truncation_penalty = 0.0
    if bool(cycle.get("truncated_start", False)):
        truncation_penalty += 0.08
    if bool(cycle.get("truncated_end", False)):
        truncation_penalty += 0.06
    segmentation_confidence = clamp(
        (0.24 * pre_roll_support)
        + (0.24 * post_roll_support)
        + (0.34 * waveform_completeness_score)
        + (0.18 * plateau_duration_support)
        - truncation_penalty
    )
    penalties: List[str] = []
    if not baseline_visible_before:
        penalties.append("missing_pre_roll_penalty")
    if not baseline_visible_after:
        penalties.append("missing_post_roll_penalty")
    if bool(cycle.get("truncated_start", False)) or bool(cycle.get("truncated_end", False)):
        penalties.append("segmentation_truncated_confidence_penalty")
    if safe_float(cycle.get("duration_s")) < 45.0 and not startup_visible:
        penalties.append("short_cycle_without_temporal_support_penalty")
    shape_meta = _shape_signature_meta(cycle)
    if str(shape_meta.get("shape_signature_status")) != "valid":
        penalties.append("missing_shape_signature_penalty")
    learning_tier = "blocked"
    if segmentation_confidence >= 0.6:
        learning_tier = "stable"
    elif segmentation_confidence >= 0.28:
        learning_tier = "provisional"

    delta_from_baseline = max(avg_power - baseline_before, 0.0)
    time_to_peak_s = 0.0
    if waveform:
        peak_idx = max(range(len(waveform)), key=lambda idx: safe_float(waveform[idx].get("power_w")))
        time_to_peak_s = safe_float(waveform[peak_idx].get("t_s"))
    area_under_curve = max(safe_float(cycle.get("energy_wh")) * 3600.0, 0.0)
    normalized_energy = area_under_curve / max(duration_s, 1.0)
    load_factor = avg_power / max(peak_power, EPSILON)
    phase_stability = clamp(1.0 - min(normalized_variance / 12.0, 1.0))

    plateau_lengths: List[float] = []
    if waveform:
        pw = [safe_float(item.get("power_w")) for item in waveform]
        pmin = min(pw)
        pmax = max(pw)
        level = pmin + (pmax - pmin) * 0.5
        tol = max((pmax - pmin) * 0.1, 8.0)
        seg_start = None
        for idx, value in enumerate(pw):
            on_level = abs(value - level) <= tol
            if on_level and seg_start is None:
                seg_start = idx
            if (not on_level or idx == len(pw) - 1) and seg_start is not None:
                end_idx = idx if not on_level else idx
                t0 = safe_float(waveform[seg_start].get("t_s"))
                t1 = safe_float(waveform[end_idx].get("t_s"))
                if t1 > t0:
                    plateau_lengths.append(round(t1 - t0, 3))
                seg_start = None
    waveform_summary = {
        "sample_count": len(waveform),
        "delta_sample_count": len(delta_points),
        "shape_peak_position": round(shape_peak_position, 4),
        "shape_tail_slope": round(shape_tail_slope, 4),
        "pre_roll_seconds": safe_float(cycle.get("pre_roll_duration_s")),
        "post_roll_seconds": safe_float(cycle.get("post_roll_duration_s")),
        "truncated_start": bool(cycle.get("truncated_start", False)),
        "truncated_end": bool(cycle.get("truncated_end", False)),
        "event_start_reason": str(cycle.get("segmentation_flags", {}).get("event_start_reason") or cycle.get("event_start_reason") or ""),
        "event_end_reason": str(cycle.get("segmentation_flags", {}).get("event_end_reason") or cycle.get("event_end_reason") or ""),
        "baseline_at_start": round(baseline_before, 4),
        "baseline_at_end": round(baseline_after, 4),
        "baseline_visible_before": baseline_visible_before,
        "baseline_visible_after": baseline_visible_after,
        "startup_visible": startup_visible,
        "shutdown_visible": shutdown_visible,
        "waveform_completeness_score": round(waveform_completeness_score, 4),
    }
    return {
        "inrush_ratio": round(inrush_ratio, 4),
        "normalized_variance": round(normalized_variance, 4),
        "plateau_stability": round(plateau_stability, 4),
        "startup_sharpness": round(startup_sharpness, 4),
        "shutdown_sharpness": round(shutdown_sharpness, 4),
        "duration_bucket": _duration_bucket(safe_float(cycle.get("duration_s"))),
        "load_level_bucket": _load_level_bucket(avg_power),
        "has_flat_plateau": has_flat_plateau,
        "has_inrush_spike": has_inrush_spike,
        "has_multi_stage_shape": has_multi_stage_shape,
        "shape_peak_position": round(shape_peak_position, 4),
        "shape_tail_slope": round(shape_tail_slope, 4),
        "baseline_before": round(baseline_before, 4),
        "baseline_after": round(baseline_after, 4),
        "delta_from_baseline": round(delta_from_baseline, 4),
        "slope_up": round(startup_sharpness, 4),
        "slope_down": round(shutdown_sharpness, 4),
        "plateau_lengths": plateau_lengths,
        "time_to_peak_s": round(time_to_peak_s, 4),
        "area_under_curve": round(area_under_curve, 4),
        "normalized_energy": round(normalized_energy, 4),
        "load_factor": round(load_factor, 4),
        "phase_stability": round(phase_stability, 4),
        "baseline_visible_before": baseline_visible_before,
        "baseline_visible_after": baseline_visible_after,
        "startup_visible": startup_visible,
        "shutdown_visible": shutdown_visible,
        "event_start_reason": str(cycle.get("segmentation_flags", {}).get("event_start_reason") or cycle.get("event_start_reason") or ""),
        "event_end_reason": str(cycle.get("segmentation_flags", {}).get("event_end_reason") or cycle.get("event_end_reason") or ""),
        "baseline_at_start": round(baseline_before, 4),
        "baseline_at_end": round(baseline_after, 4),
        "waveform_completeness_score": round(waveform_completeness_score, 4),
        "segmentation_confidence": round(segmentation_confidence, 4),
        "confidence_penalties": penalties,
        "learning_allowed": learning_tier != "blocked",
        "learning_tier": learning_tier,
        **shape_meta,
        "waveform_summary": waveform_summary,
    }


def infer_unknown_subclass(cycle: Dict[str, Any]) -> Tuple[str, List[str]]:
    features = dict(cycle.get("derived_features") or {})
    duration_s = safe_float(cycle.get("duration_s"))
    avg_power = safe_float(cycle.get("avg_power_w"))
    inrush_ratio = safe_float(features.get("inrush_ratio", cycle.get("inrush_ratio", 0.0)))
    normalized_variance = safe_float(features.get("normalized_variance"))
    reasons: List[str] = []

    if bool(features.get("has_multi_stage_shape")):
        reasons.append("multiple_plateaus_detected")
        return ("unknown_multistage", reasons)
    if avg_power < 120.0 and duration_s >= 120.0 and normalized_variance <= 6.0:
        reasons.append("stable_low_power")
        return ("constant_low_power", reasons)
    if 120.0 <= avg_power < 450.0 and duration_s >= 90.0 and normalized_variance <= 8.0:
        reasons.append("stable_medium_power")
        return ("constant_medium_power", reasons)
    if inrush_ratio >= 1.7:
        reasons.append("high_inrush_ratio")
        if avg_power <= 400.0:
            return ("compressor_low_power", reasons)
        return ("compressor_high_power", reasons)
    if bool(cycle.get("has_motor_pattern", False)):
        reasons.append("motor_like_shape")
        if normalized_variance <= 9.0:
            return ("pump_constant", reasons)
        return ("pump_variable", reasons)
    if bool(cycle.get("has_heating_pattern", False)) and normalized_variance <= 6.0:
        reasons.append("resistive_heating_profile")
        return ("heater_resistive", reasons)
    if bool(cycle.get("has_heating_pattern", False)) and bool(features.get("has_multi_stage_shape")):
        reasons.append("multistage_heating_profile")
        return ("multi_stage_heating", reasons)
    if duration_s <= 20.0:
        reasons.append("short_runtime")
        return ("unknown_short_pulse", reasons)
    if duration_s >= 1800.0 and avg_power <= 160.0:
        reasons.append("long_low_power_runtime")
        return ("unknown_low_power_long", reasons)
    if normalized_variance >= 12.0 or not bool(features.get("has_flat_plateau", False)):
        reasons.append("variable_power_shape")
        return ("unknown_variable_load", reasons)
    if bool(features.get("has_flat_plateau", False)):
        reasons.append("stable_plateau_without_device_match")
        return ("unknown_constant_load", reasons)
    reasons.append("fallback_unknown")
    return ("unknown_electronics", reasons)


def score_shape_match(cycle: Dict[str, Any], patterns: Sequence[Dict[str, Any]]) -> ShapeMatchScore:
    cycle_label = "unknown"
    cycle_phase = str(cycle.get("phase") or "L1")
    cycle_shape_status = str(cycle.get("shape_signature_status") or cycle.get("derived_features", {}).get("shape_signature_status") or "")
    cycle_signature = str(cycle.get("shape_signature") or "").strip()
    explicit_signature = parse_shape_signature(cycle_signature)
    signature_usable = len(explicit_signature) >= 4
    if cycle_shape_status != "valid" and not signature_usable:
        logger.debug("shape scoring skipped because shape_signature missing")
        return ShapeMatchScore(
            label=cycle_label,
            score=0.0,
            distance=1.0,
            euclidean=0.0,
            dtw=0.0,
            pattern_id=None,
            cluster_id=str(cycle.get("cluster_id") or ""),
            reasons=["shape scoring skipped because shape_signature missing"],
            valid=False,
        )
    cycle_vector = _resample_profile(
        cycle_signature,
        fallback_shape_signature=cycle.get("shape_signature"),
    )
    if not cycle_vector:
        return ShapeMatchScore(
            label=cycle_label,
            score=0.0,
            distance=1.0,
            euclidean=0.0,
            dtw=0.0,
            pattern_id=None,
            cluster_id=str(cycle.get("cluster_id") or ""),
            reasons=["no_cycle_shape_vector"],
            valid=False,
        )

    best: ShapeMatchScore | None = None
    for pattern in patterns:
        if str(pattern.get("phase") or cycle_phase) != cycle_phase:
            continue
        pattern_signature = str(pattern.get("shape_signature") or "").strip()
        if not pattern_signature:
            continue
        candidate_vector = _resample_profile(
            pattern_signature,
            fallback_shape_signature=pattern.get("shape_signature"),
        )
        if not candidate_vector:
            continue
        euclidean = euclidean_similarity(cycle_vector, candidate_vector)
        dtw = dtw_similarity(cycle_vector, candidate_vector)
        duration_delta = abs(safe_float(pattern.get("duration_s")) - safe_float(cycle.get("duration_s"))) / max(
            safe_float(pattern.get("duration_s"), 1.0),
            safe_float(cycle.get("duration_s"), 1.0),
            1.0,
        )
        power_delta = abs(safe_float(pattern.get("avg_power_w")) - safe_float(cycle.get("avg_power_w"))) / max(
            safe_float(pattern.get("avg_power_w"), 1.0),
            safe_float(cycle.get("avg_power_w"), 1.0),
            1.0,
        )
        score = clamp((0.48 * euclidean) + (0.42 * dtw) + (0.10 * (1.0 - min(duration_delta + power_delta, 1.0))))
        distance = 1.0 - score
        candidate = ShapeMatchScore(
            label=str(pattern.get("user_label") or pattern.get("suggestion_type") or "unknown"),
            score=score,
            distance=distance,
            euclidean=euclidean,
            dtw=dtw,
            pattern_id=int(pattern.get("id") or 0) or None,
            cluster_id=str(pattern.get("cluster_id") or pattern.get("device_group_id") or ""),
            reasons=[
                f"euclidean={euclidean:.3f}",
                f"dtw={dtw:.3f}",
                f"duration_delta={duration_delta:.3f}",
                f"power_delta={power_delta:.3f}",
            ],
            valid=True,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    if best is not None:
        return best
    return ShapeMatchScore(
        label=cycle_label,
        score=0.0,
        distance=1.0,
        euclidean=0.0,
        dtw=0.0,
        pattern_id=None,
        cluster_id=str(cycle.get("cluster_id") or ""),
        reasons=["no_pattern_shape_match"],
        valid=False,
    )


def score_temporal_context(cycle: Dict[str, Any], patterns: Sequence[Dict[str, Any]], preferred_label: str = "") -> TemporalContextScore:
    cycle_phase = str(cycle.get("phase") or "L1")
    target_label = str(preferred_label or cycle.get("suggestion_type") or "unknown")
    same_label = [
        pattern for pattern in patterns
        if str(pattern.get("phase") or cycle_phase) == cycle_phase
        and str(pattern.get("user_label") or pattern.get("suggestion_type") or "unknown") == target_label
    ]
    if not same_label:
        return TemporalContextScore(0.0, 0.0, 0.0, 0.0, 0, 0.0, ["no_temporal_history"])

    intervals = [safe_float(item.get("typical_interval_s")) for item in same_label if safe_float(item.get("typical_interval_s")) > 0.0]
    durations = [safe_float(item.get("duration_s")) for item in same_label if safe_float(item.get("duration_s")) > 0.0]
    occurrence_count = max(int(sum(int(item.get("seen_count", 0) or 0) for item in same_label)), 0)
    typical_interval_s = min(intervals) if intervals else 0.0
    typical_run_duration_s = sum(durations) / max(len(durations), 1) if durations else 0.0
    duration_match = 1.0
    if typical_run_duration_s > 0.0:
        duration_match = 1.0 - min(abs(typical_run_duration_s - safe_float(cycle.get("duration_s"))) / max(typical_run_duration_s, 1.0), 1.0)

    hour_score = 0.0
    cycle_end = None
    try:
        cycle_end = datetime.fromisoformat(str(cycle.get("end_ts") or ""))
    except Exception:
        cycle_end = None
    if cycle_end is not None:
        cycle_hour = float(cycle_end.hour) + (float(cycle_end.minute) / 60.0)
        hour_diffs: List[float] = []
        for pattern in same_label:
            expected_hour = safe_float(pattern.get("avg_hour_of_day"), 12.0)
            hour_diff = abs(cycle_hour - expected_hour)
            hour_diffs.append(min(hour_diff, 24.0 - hour_diff))
        if hour_diffs:
            mean_diff = sum(hour_diffs) / len(hour_diffs)
            hour_score = 1.0 - min(mean_diff / 12.0, 1.0)

    similarity_to_previous = clamp((0.65 * duration_match) + (0.35 * clamp(math.log1p(occurrence_count) / 4.0)))
    overall = clamp((0.45 * similarity_to_previous) + (0.35 * hour_score) + (0.20 * clamp(math.log1p(occurrence_count) / 4.0)))
    reasons = []
    if occurrence_count >= 6:
        reasons.append("recurring_cluster")
    if hour_score >= 0.55:
        reasons.append("hour_of_day_consistent")
    if duration_match >= 0.6:
        reasons.append("duration_matches_cluster")
    return TemporalContextScore(
        recurrence_interval_s=typical_interval_s,
        similarity_to_previous=similarity_to_previous,
        hour_of_day_score=hour_score,
        typical_run_duration_s=typical_run_duration_s,
        occurrence_count=occurrence_count,
        score=overall,
        reasons=reasons or ["weak_temporal_support"],
    )


def generate_heuristic_candidates(cycle: Dict[str, Any], temporal: TemporalContextScore) -> List[Dict[str, Any]]:
    features = dict(cycle.get("derived_features") or {})
    duration_s = safe_float(cycle.get("duration_s"))
    avg_power = safe_float(cycle.get("avg_power_w"))
    peak_power = safe_float(cycle.get("peak_power_w"))
    inrush_ratio = safe_float(features.get("inrush_ratio", cycle.get("inrush_ratio", 0.0)))
    plateau_stability = safe_float(features.get("plateau_stability"))
    has_flat_plateau = bool(features.get("has_flat_plateau", False))
    truncated = bool(cycle.get("truncated_start", False) or cycle.get("truncated_end", False))
    segmentation_confidence = safe_float(cycle.get("segmentation_confidence", features.get("segmentation_confidence", 0.0)))
    waveform_completeness = safe_float(cycle.get("waveform_completeness_score", features.get("waveform_completeness_score", 0.0)))
    normalized_variance = safe_float(features.get("normalized_variance", cycle.get("normalized_variance", 0.0)))
    has_motor = bool(cycle.get("has_motor_pattern", False)) or inrush_ratio >= 1.25
    candidates: List[Dict[str, Any]] = []

    if has_flat_plateau and normalized_variance <= 8.0 and duration_s >= 180.0:
        candidates.append({
            "label": "constant_load_pattern",
            "score": 0.62 if segmentation_confidence >= 0.4 else 0.52,
            "source": "heuristic",
            "reasons": ["stable_plateau_detected", f"normalized_variance={normalized_variance:.2f}", f"duration_s={duration_s:.1f}"],
        })

    if truncated and has_motor and duration_s <= 90.0:
        candidates.append({
            "label": "compressor_candidate" if avg_power <= 700.0 else "motor_candidate",
            "score": 0.66,
            "source": "heuristic",
            "reasons": ["startup-only event", "full-cycle evidence missing", "segmentation incomplete"],
        })

    if segmentation_confidence < 0.55 and has_motor and avg_power <= 900.0:
        candidates.append({
            "label": "pump_candidate" if has_flat_plateau else "motor_candidate",
            "score": 0.58,
            "source": "heuristic",
            "reasons": ["segmentation quality gate", f"segmentation_confidence={segmentation_confidence:.2f}"],
        })

    if has_motor and duration_s <= 45.0 and not has_flat_plateau:
        candidates.append({
            "label": "compressor_candidate",
            "score": 0.54,
            "source": "heuristic",
            "reasons": ["short_high_inrush_startup_without_plateau"],
        })

    if has_motor and has_flat_plateau and duration_s >= 90.0 and segmentation_confidence >= 0.55 and waveform_completeness >= 0.50:
        if avg_power <= 550.0:
            label = "compressor_small" if temporal.occurrence_count >= 4 else "small_pump_motor"
        else:
            label = "compressor_large" if temporal.occurrence_count >= 3 else "large_pump_motor"
        candidates.append({
            "label": label,
            "score": 0.60 if "compressor" in label else 0.56,
            "source": "heuristic",
            "reasons": ["motor_like_plateau", f"inrush_ratio={inrush_ratio:.2f}", f"plateau_stability={plateau_stability:.2f}"],
        })

    if (
        avg_power >= 80.0
        and avg_power <= 420.0
        and duration_s >= 240.0
        and duration_s <= 3600.0
        and has_flat_plateau
        and temporal.occurrence_count >= 5
        and temporal.score >= 0.55
        and not truncated
        and segmentation_confidence >= 0.7
    ):
        candidates.append({
            "label": "fridge",
            "score": 0.72,
            "source": "temporal_match",
            "reasons": ["recurring_compressor_plateau", f"occurrence_count={temporal.occurrence_count}"],
        })

    if (
        avg_power >= 80.0
        and avg_power <= 420.0
        and has_flat_plateau
        and temporal.occurrence_count >= 3
        and temporal.score >= 0.45
        and segmentation_confidence < 0.7
    ):
        candidates.append({
            "label": "fridge_candidate",
            "score": 0.60,
            "source": "temporal_match",
            "reasons": ["full-cycle evidence missing", "segmentation incomplete"],
        })

    if truncated and any(item["label"] == "fridge" for item in candidates):
        candidates = [item for item in candidates if item["label"] != "fridge"]
        candidates.append({
            "label": "compressor_candidate",
            "score": 0.48,
            "source": "heuristic",
            "reasons": ["downgraded_from_fridge_due_to_truncated_window"],
        })

    unknown_label, unknown_reasons = infer_unknown_subclass(cycle)
    candidates.append({
        "label": unknown_label,
        "score": 0.40,
        "source": "heuristic",
        "reasons": unknown_reasons,
    })
    return candidates


def resolve_final_decision(
    cycle: Dict[str, Any],
    heuristic_candidates: Sequence[Dict[str, Any]],
    shape_match: ShapeMatchScore,
    temporal: TemporalContextScore,
    fallback: str = "unknown",
) -> Dict[str, Any]:
    candidates = list(heuristic_candidates or [])
    segmentation_confidence = safe_float(cycle.get("segmentation_confidence", cycle.get("derived_features", {}).get("segmentation_confidence", 0.0)))
    waveform_completeness = safe_float(cycle.get("waveform_completeness_score", cycle.get("derived_features", {}).get("waveform_completeness_score", 0.0)))
    penalties = list(cycle.get("confidence_penalties") or cycle.get("derived_features", {}).get("confidence_penalties", []))
    learning_allowed = bool(cycle.get("learning_allowed", cycle.get("derived_features", {}).get("learning_allowed", False)))
    learning_tier = str(cycle.get("learning_tier", cycle.get("derived_features", {}).get("learning_tier", "blocked")))

    if shape_match.valid and shape_match.score >= 0.55 and shape_match.label not in {"", "unknown", "unbekannt"}:
        candidates.append(
            {
                "label": shape_match.label,
                "score": min(0.85, 0.35 + (shape_match.score * 0.55)),
                "source": "shape_match",
                "reasons": list(shape_match.reasons),
            }
        )

    best = max(candidates, key=lambda item: safe_float(item.get("score"), 0.0)) if candidates else {
        "label": fallback,
        "score": 0.0,
        "source": "fallback",
        "reasons": ["no_candidates"],
    }
    rule_confidence = clamp(safe_float(best.get("score"), 0.0))
    shape_confidence = clamp(shape_match.score if shape_match.valid else 0.0)
    temporal_confidence = clamp(temporal.score)
    final_confidence = clamp(
        (0.30 * rule_confidence)
        + (0.20 * shape_confidence)
        + (0.20 * temporal_confidence)
        + (0.30 * clamp((segmentation_confidence + waveform_completeness) / 2.0))
    )
    label = str(best.get("label") or fallback)
    reasons = list(best.get("reasons") or [])
    label_source = str(best.get("source") or "heuristic")

    if learning_tier != "stable" or waveform_completeness < 0.5:
        label_source = "heuristic"
        if label in {"fridge", "compressor_small", "compressor_large", "small_pump_motor", "large_pump_motor", "constant_load_pattern"}:
            if "fridge" in label:
                label = "fridge_candidate"
            elif "pump" in label:
                label = "pump_candidate"
            elif label == "constant_load_pattern" and learning_tier == "blocked":
                label = "unknown_constant_load"
            else:
                label = "compressor_candidate"
            reasons.append("full-cycle evidence missing")
            reasons.append("segmentation incomplete")

    if label == "fridge" and temporal.occurrence_count < 5:
        label = "compressor_candidate"
        final_confidence = min(final_confidence, 0.58)
        label_source = "hybrid"
        reasons.append("downgraded_from_fridge_due_to_weak_recurrence")

    if bool(cycle.get("truncated_start", False) or cycle.get("truncated_end", False)):
        final_confidence = max(0.2, final_confidence * 0.78)
        if "segmentation_truncated_confidence_penalty" not in penalties:
            penalties.append("segmentation_truncated_confidence_penalty")
        reasons.append("segmentation_truncated_confidence_penalty")

    if not shape_match.valid:
        shape_confidence = 0.0
        if "missing_shape_signature_penalty" not in penalties:
            penalties.append("missing_shape_signature_penalty")
        if label_source == "shape_match":
            label_source = "heuristic"

    if not learning_allowed:
        final_confidence = min(final_confidence, 0.64)
        reasons.append("learning_blocked_due_to_segmentation_quality")

    if label not in {"unknown", "unbekannt", "unknown_electronics"}:
        final_confidence = max(final_confidence, 0.35)

    if label in {"unknown", "unbekannt"}:
        fallback_unknown, fallback_reasons = infer_unknown_subclass(cycle)
        label = fallback_unknown
        reasons.extend(fallback_reasons)
        final_confidence = max(final_confidence, 0.35)

    return {
        "raw_label": str(best.get("label") or fallback),
        "refined_label": label,
        "candidate_labels": [
            {
                "label": str(item.get("label") or fallback),
                "score": round(clamp(safe_float(item.get("score"), 0.0)), 4),
                "source": str(item.get("source") or "heuristic"),
                "reasons": list(item.get("reasons") or []),
            }
            for item in sorted(candidates, key=lambda item: safe_float(item.get("score"), 0.0), reverse=True)
        ],
        "rule_confidence": round(rule_confidence, 4),
        "shape_confidence": round(shape_confidence, 4),
        "temporal_confidence": round(temporal_confidence, 4),
        "segmentation_confidence": round(segmentation_confidence, 4),
        "waveform_completeness_score": round(waveform_completeness, 4),
        "final_confidence": round(final_confidence, 4),
        "label_source": label_source,
        "learning_allowed": learning_allowed,
        "learning_tier": learning_tier,
        "confidence_penalties": penalties,
        "shape_signature_status": str(cycle.get("shape_signature_status") or cycle.get("derived_features", {}).get("shape_signature_status") or "missing"),
        "shape_signature_reason": str(cycle.get("shape_signature_reason") or cycle.get("derived_features", {}).get("shape_signature_reason") or "unknown"),
        "cluster_id": shape_match.cluster_id or f"{label}:{cycle.get('phase', 'L1')}:{cycle.get('derived_features', {}).get('duration_bucket', 'na')}",
        "reason": "; ".join(reasons[:4]) if reasons else "no_reason_recorded",
        "shape_match": {
            "label": shape_match.label,
            "score": round(shape_match.score, 4),
            "distance": round(shape_match.distance, 4),
            "euclidean": round(shape_match.euclidean, 4),
            "dtw": round(shape_match.dtw, 4),
            "pattern_id": shape_match.pattern_id,
            "reasons": list(shape_match.reasons),
            "valid": bool(shape_match.valid),
        },
        "temporal_features": {
            "recurrence_interval_s": round(temporal.recurrence_interval_s, 4),
            "similarity_to_previous": round(temporal.similarity_to_previous, 4),
            "hour_of_day_score": round(temporal.hour_of_day_score, 4),
            "typical_run_duration_s": round(temporal.typical_run_duration_s, 4),
            "cluster_occurrence_count": temporal.occurrence_count,
            "reasons": list(temporal.reasons),
        },
    }


def enrich_cycle_for_classification(cycle: Dict[str, Any], patterns: Sequence[Dict[str, Any]], fallback: str = "unknown") -> Dict[str, Any]:
    enriched = dict(cycle)
    derived = build_waveform_summary(enriched)
    enriched["derived_features"] = derived
    enriched["segmentation_confidence"] = safe_float(derived.get("segmentation_confidence"))
    enriched["waveform_completeness_score"] = safe_float(derived.get("waveform_completeness_score"))
    enriched["learning_allowed"] = bool(derived.get("learning_allowed", False))
    enriched["learning_tier"] = str(derived.get("learning_tier", "blocked"))
    enriched["confidence_penalties"] = list(derived.get("confidence_penalties", []))
    enriched["shape_signature_status"] = str(derived.get("shape_signature_status", "missing"))
    enriched["shape_signature_reason"] = str(derived.get("shape_signature_reason", "unknown"))
    shape_match = score_shape_match(enriched, patterns)
    temporal = score_temporal_context(enriched, patterns, preferred_label=shape_match.label if shape_match.score >= 0.55 else "")
    heuristic_candidates = generate_heuristic_candidates(enriched, temporal)
    decision = resolve_final_decision(enriched, heuristic_candidates, shape_match, temporal, fallback=fallback)
    enriched.update(decision)
    return enriched