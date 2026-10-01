"""Feature Vector v2 for self-contained NILM learning."""

from __future__ import annotations
import math
from typing import Any, Dict, List, Sequence


FEATURE_NAMES = (
    "avg_power_log", "peak_power_log", "duration_log", "energy_log",
    "power_std_ratio", "rise_rate_log", "fall_rate_log", "duty_cycle",
    "inrush_ratio", "num_substates", "step_count", "load_factor",
    "baseline_delta_ratio", "peak_delta_ratio", "segmentation_confidence",
    "waveform_completeness", "overlap_score", "plateau_stability",
    "shape_peak_position", "shape_tail_slope", "recurrence_log",
    "hour_sin", "hour_cos", "phase_index",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _log(value: Any) -> float:
    v = _f(value)
    return math.copysign(math.log1p(abs(v)), v)


def _phase_index(value: Any) -> float:
    return {"L1": 0.0, "L2": 0.5, "L3": 1.0}.get(str(value or "").upper(), 0.0)


def build_feature_vector_v2(row: Dict[str, Any]) -> List[float]:
    d = dict(row.get("derived_features") or {})
    t = dict(row.get("temporal_features") or {})
    avg = max(_f(row.get("avg_power_w")), 1.0)
    peak = max(_f(row.get("peak_power_w")), avg)
    variance = max(_f(row.get("power_variance", d.get("power_variance"))), 0.0)
    std_ratio = math.sqrt(variance) / avg if variance > 0 else _f(d.get("normalized_variance")) / max(avg, 1.0)
    baseline = _f(row.get("baseline_before_w", d.get("baseline_before")))
    delta_avg = _f(row.get("delta_avg_power_w"), max(avg - baseline, 0.0))
    delta_peak = _f(row.get("delta_peak_power_w"), max(peak - baseline, 0.0))
    hour = _f(t.get("hour_of_day", row.get("avg_hour_of_day", 12.0)), 12.0) % 24.0
    angle = (hour / 24.0) * 2.0 * math.pi

    return [
        _log(avg),
        _log(peak),
        _log(row.get("duration_s", row.get("avg_duration_s"))),
        _log(row.get("energy_wh")),
        min(max(std_ratio, 0.0), 10.0),
        _log(row.get("rise_rate_w_per_s")),
        _log(row.get("fall_rate_w_per_s")),
        min(max(_f(row.get("duty_cycle")), 0.0), 1.0),
        min(max(_f(d.get("inrush_ratio", row.get("peak_to_avg_ratio", peak / avg))), 0.0), 12.0),
        min(_f(row.get("num_substates")), 20.0) / 20.0,
        min(_f(row.get("step_count")), 30.0) / 30.0,
        min(max(avg / peak, 0.0), 1.0),
        min(max(delta_avg / avg, -2.0), 2.0),
        min(max(delta_peak / peak, -2.0), 2.0),
        min(max(_f(row.get("segmentation_confidence", d.get("segmentation_confidence"))), 0.0), 1.0),
        min(max(_f(row.get("waveform_completeness_score", d.get("waveform_completeness_score"))), 0.0), 1.0),
        min(max(_f(row.get("overlap_score")), 0.0), 1.0),
        _log(d.get("plateau_stability")),
        min(max(_f(d.get("shape_peak_position")), 0.0), 1.0),
        max(min(_f(d.get("shape_tail_slope")), 1000.0), -1000.0) / 1000.0,
        _log(t.get("recurrence_interval_s", row.get("typical_interval_s"))),
        math.sin(angle),
        math.cos(angle),
        _phase_index(row.get("phase")),
    ]


def robust_scale_matrix(rows: Sequence[Dict[str, Any]]) -> List[List[float]]:
    matrix = [build_feature_vector_v2(row) for row in rows]
    if not matrix:
        return []
    cols = list(zip(*matrix))
    medians: List[float] = []
    scales: List[float] = []
    for col in cols:
        vals = sorted(float(v) for v in col)
        mid = len(vals) // 2
        med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
        devs = sorted(abs(v - med) for v in vals)
        mad = devs[len(devs) // 2] if devs else 0.0
        medians.append(med)
        scales.append(max(mad * 1.4826, 1e-6))
    return [[(v - medians[i]) / scales[i] for i, v in enumerate(row)] for row in matrix]
