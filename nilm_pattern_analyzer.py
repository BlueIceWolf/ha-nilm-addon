#!/usr/bin/env python3
"""NILM pattern analyzer.

Usage:
    python nilm_pattern_analyzer.py input.json --out out
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEVICE_CLASSES = ("fridge", "pump", "kettle", "microwave", "oven", "heater")
QUALITY_LABELS = ("sehr_gut", "brauchbar", "unsicher", "verwerfen")


@dataclass
class PatternFeatures:
    pattern_index: int
    pattern_id: str
    candidate_label: str
    suggestion_type: str
    phase: str
    seen_count: int
    avg_power_w: float
    peak_power_w: float
    duration_s: float
    energy_wh: float
    confidence_score: float
    power_variance: float
    power_std: float
    coefficient_of_variation: Optional[float]
    duty_cycle: Optional[float]
    peak_to_avg_ratio: Optional[float]
    stability_score: Optional[float]
    frequency_per_day: Optional[float]
    has_multiple_modes: bool
    operating_modes_count: int
    num_substates: int
    has_heating_pattern: bool
    has_motor_pattern: bool
    typical_interval_s: Optional[float]
    rise_rate_w_per_s: Optional[float]
    fall_rate_w_per_s: Optional[float]
    profile_point_count: int
    plateau_count: int
    dominant_levels_count: int
    dominant_levels_w: List[float]
    significant_jump_count: int
    largest_jump_w: float
    median_jump_w: float
    jump_density: float
    energy_duration_power_ratio: Optional[float]
    repeatability_score: float
    mixed_load_flag: bool
    segmentation_risk: bool


@dataclass
class PatternEvaluation:
    quality_label: str
    quality_score: float
    plausibility_by_type: Dict[str, float]
    best_type: str
    alternative_hints: List[str]
    adjusted_confidence: float
    label_plausibility: float
    reject_reasons: List[str]
    reasoning: str


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return default
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return default
        try:
            num = float(text)
        except ValueError:
            return default
        if math.isnan(num) or math.isinf(num):
            return default
        return num
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


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "ja", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "nein", "n", "off"}:
            return False
    return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize(values: Sequence[float]) -> List[float]:
    cleaned = [v for v in values if not math.isnan(v) and not math.isinf(v)]
    return cleaned


def _extract_profile_values(profile_points: Any) -> List[float]:
    if not isinstance(profile_points, list):
        return []

    values: List[float] = []
    for point in profile_points:
        if isinstance(point, (int, float, str)):
            values.append(_safe_float(point))
            continue
        if isinstance(point, dict):
            for key in ("power_w", "power", "value", "w", "watts", "p"):
                if key in point:
                    values.append(_safe_float(point.get(key)))
                    break
    return [v for v in values if v >= 0.0]


def _detect_plateaus_and_jumps(values: Sequence[float]) -> Dict[str, Any]:
    arr = _normalize(values)
    if len(arr) < 3:
        return {
            "plateau_count": 0,
            "dominant_levels": [],
            "jump_magnitudes": [],
            "largest_jump": 0.0,
            "median_jump": 0.0,
            "jump_density": 0.0,
        }

    median_value = statistics.median(arr)
    plateau_tol = max(15.0, abs(median_value) * 0.08)
    jump_threshold = max(40.0, max(arr) * 0.12)

    plateaus: List[Tuple[int, int, float]] = []
    start_idx = 0

    for idx in range(1, len(arr)):
        if abs(arr[idx] - arr[idx - 1]) <= plateau_tol:
            continue
        end_idx = idx - 1
        if end_idx - start_idx + 1 >= 2:
            segment = arr[start_idx : end_idx + 1]
            plateaus.append((start_idx, end_idx, statistics.mean(segment)))
        start_idx = idx

    if len(arr) - start_idx >= 2:
        tail = arr[start_idx:]
        plateaus.append((start_idx, len(arr) - 1, statistics.mean(tail)))

    jump_magnitudes: List[float] = []
    for idx in range(1, len(arr)):
        jump = abs(arr[idx] - arr[idx - 1])
        if jump >= jump_threshold:
            jump_magnitudes.append(jump)

    dominant_levels = _cluster_levels([p[2] for p in plateaus], tol=max(30.0, plateau_tol * 1.5))

    return {
        "plateau_count": len(plateaus),
        "dominant_levels": dominant_levels,
        "jump_magnitudes": jump_magnitudes,
        "largest_jump": max(jump_magnitudes) if jump_magnitudes else 0.0,
        "median_jump": statistics.median(jump_magnitudes) if jump_magnitudes else 0.0,
        "jump_density": len(jump_magnitudes) / max(1, len(arr) - 1),
    }


def _cluster_levels(levels: Sequence[float], tol: float) -> List[float]:
    if not levels:
        return []
    sorted_levels = sorted(levels)
    clusters: List[List[float]] = [[sorted_levels[0]]]
    for level in sorted_levels[1:]:
        if abs(level - statistics.mean(clusters[-1])) <= tol:
            clusters[-1].append(level)
        else:
            clusters.append([level])
    return [round(statistics.mean(cluster), 1) for cluster in clusters]


def _infer_candidate_label(pattern: Dict[str, Any]) -> str:
    raw = str(pattern.get("candidate_name") or pattern.get("suggestion_type") or "unknown")
    text = raw.strip().lower()
    if not text:
        return "unknown"

    aliases = {
        "kuehlschrank": "fridge",
        "kuhlschrank": "fridge",
        "kitchen_fridge": "fridge",
        "wasserkocher": "kettle",
        "mikrowelle": "microwave",
        "ofen": "oven",
        "heizung": "heater",
        "waermepumpe": "pump",
        "wärmepumpe": "pump",
    }
    if text in aliases:
        return aliases[text]

    for device_type in DEVICE_CLASSES:
        if device_type in text:
            return device_type

    return text


def _compute_repeatability(seen_count: int, stability_score: Optional[float], frequency_per_day: Optional[float]) -> float:
    seen_component = _clamp(seen_count / 12.0, 0.0, 1.0)
    stability_component = _clamp((stability_score or 0.0), 0.0, 1.0)
    frequency_component = _clamp((frequency_per_day or 0.0) / 8.0, 0.0, 1.0)
    return round((0.45 * seen_component) + (0.4 * stability_component) + (0.15 * frequency_component), 3)


def extract_features(pattern: Dict[str, Any], pattern_index: int) -> PatternFeatures:
    avg_power = _safe_float(pattern.get("avg_power_w"))
    peak_power = _safe_float(pattern.get("peak_power_w"))
    duration_s = _safe_float(pattern.get("duration_s"))
    energy_wh = _safe_float(pattern.get("energy_wh"))
    confidence_score = _clamp(_safe_float(pattern.get("confidence_score"), default=0.0), 0.0, 1.0)

    power_variance = max(0.0, _safe_float(pattern.get("power_variance")))
    power_std = math.sqrt(power_variance)
    cv = (power_std / avg_power) if avg_power > 1e-6 else None

    profile_values = _extract_profile_values(pattern.get("profile_points"))
    profile_analysis = _detect_plateaus_and_jumps(profile_values)

    operating_modes_raw = pattern.get("operating_modes")
    if isinstance(operating_modes_raw, list):
        operating_modes_count = len(operating_modes_raw)
    elif isinstance(operating_modes_raw, dict):
        operating_modes_count = len(operating_modes_raw.keys())
    elif operating_modes_raw is None:
        operating_modes_count = 0
    else:
        operating_modes_count = 1

    estimated_energy = (avg_power * duration_s) / 3600.0 if duration_s > 0 else None
    if estimated_energy and estimated_energy > 1e-9:
        energy_ratio = energy_wh / estimated_energy
    else:
        energy_ratio = None

    seen_count = max(0, _safe_int(pattern.get("seen_count")))
    stability_score = pattern.get("stability_score")
    stability_score_f = _safe_float(stability_score, default=-1.0)
    stability_opt = None if stability_score is None else _clamp(stability_score_f, 0.0, 1.0)

    frequency_per_day_raw = pattern.get("frequency_per_day")
    frequency_per_day = None
    if frequency_per_day_raw is not None:
        frequency_per_day = max(0.0, _safe_float(frequency_per_day_raw))

    repeatability = _compute_repeatability(seen_count, stability_opt, frequency_per_day)

    mixed_load = (
        profile_analysis["plateau_count"] >= 5
        and profile_analysis["jump_density"] > 0.22
        and (stability_opt is None or stability_opt < 0.55)
    )

    segmentation_risk = (
        profile_analysis["largest_jump"] > max(450.0, avg_power * 1.6)
        and profile_analysis["plateau_count"] >= 4
    )

    pattern_id = str(pattern.get("id") or pattern.get("pattern_id") or f"pattern_{pattern_index}")

    duty_cycle_raw = pattern.get("duty_cycle")
    duty_cycle = None if duty_cycle_raw is None else _clamp(_safe_float(duty_cycle_raw), 0.0, 1.0)

    peak_to_avg_raw = pattern.get("peak_to_avg_ratio")
    if peak_to_avg_raw is None:
        peak_to_avg = (peak_power / avg_power) if avg_power > 1e-9 else None
    else:
        peak_to_avg = max(0.0, _safe_float(peak_to_avg_raw))

    typical_interval_raw = pattern.get("typical_interval_s")
    typical_interval = None if typical_interval_raw is None else max(0.0, _safe_float(typical_interval_raw))

    rise_raw = pattern.get("rise_rate_w_per_s")
    rise_rate = None if rise_raw is None else _safe_float(rise_raw)

    fall_raw = pattern.get("fall_rate_w_per_s")
    fall_rate = None if fall_raw is None else _safe_float(fall_raw)

    return PatternFeatures(
        pattern_index=pattern_index,
        pattern_id=pattern_id,
        candidate_label=_infer_candidate_label(pattern),
        suggestion_type=str(pattern.get("suggestion_type") or "").strip().lower(),
        phase=str(pattern.get("phase") or "unknown"),
        seen_count=seen_count,
        avg_power_w=avg_power,
        peak_power_w=peak_power,
        duration_s=duration_s,
        energy_wh=energy_wh,
        confidence_score=confidence_score,
        power_variance=power_variance,
        power_std=power_std,
        coefficient_of_variation=cv,
        duty_cycle=duty_cycle,
        peak_to_avg_ratio=peak_to_avg,
        stability_score=stability_opt,
        frequency_per_day=frequency_per_day,
        has_multiple_modes=_safe_bool(pattern.get("has_multiple_modes")),
        operating_modes_count=operating_modes_count,
        num_substates=max(0, _safe_int(pattern.get("num_substates"))),
        has_heating_pattern=_safe_bool(pattern.get("has_heating_pattern")),
        has_motor_pattern=_safe_bool(pattern.get("has_motor_pattern")),
        typical_interval_s=typical_interval,
        rise_rate_w_per_s=rise_rate,
        fall_rate_w_per_s=fall_rate,
        profile_point_count=len(profile_values),
        plateau_count=profile_analysis["plateau_count"],
        dominant_levels_count=len(profile_analysis["dominant_levels"]),
        dominant_levels_w=profile_analysis["dominant_levels"],
        significant_jump_count=len(profile_analysis["jump_magnitudes"]),
        largest_jump_w=profile_analysis["largest_jump"],
        median_jump_w=profile_analysis["median_jump"],
        jump_density=profile_analysis["jump_density"],
        energy_duration_power_ratio=energy_ratio,
        repeatability_score=repeatability,
        mixed_load_flag=mixed_load,
        segmentation_risk=segmentation_risk,
    )


def _score_common_quality(features: PatternFeatures) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []

    if features.repeatability_score >= 0.72:
        score += 0.22
        reasons.append("Hohe Wiederholbarkeit")
    elif features.repeatability_score >= 0.45:
        score += 0.12
    else:
        reasons.append("Niedrige Wiederholbarkeit")

    if features.stability_score is not None:
        if features.stability_score >= 0.75:
            score += 0.20
            reasons.append("Hohe Stabilitaet")
        elif features.stability_score >= 0.5:
            score += 0.10
        else:
            reasons.append("Niedrige Stabilitaet")

    if features.seen_count >= 8:
        score += 0.16
        reasons.append(f"Viele Sichtungen ({features.seen_count})")
    elif features.seen_count >= 4:
        score += 0.08
    else:
        reasons.append("Zu wenige Sichtungen")

    if features.coefficient_of_variation is not None:
        cv = features.coefficient_of_variation
        if cv <= 0.15:
            score += 0.12
        elif cv <= 0.35:
            score += 0.07
        elif cv > 0.65:
            reasons.append("Sehr hohe Leistungsstreuung")

    if features.plateau_count >= 1:
        score += 0.08

    if features.significant_jump_count <= 4:
        score += 0.08
    else:
        reasons.append("Viele Lastspruenge")

    if features.mixed_load_flag:
        score -= 0.25
        reasons.append("Wahrscheinlich Mischlast")

    if features.segmentation_risk:
        score -= 0.15
        reasons.append("Moegliche Fehlsegmentierung")

    if features.energy_duration_power_ratio is not None:
        ratio = features.energy_duration_power_ratio
        if 0.75 <= ratio <= 1.3:
            score += 0.12
        elif ratio < 0.45 or ratio > 1.9:
            score -= 0.12
            reasons.append("Unplausibles Energie-Dauer-Leistungs-Verhaeltnis")

    score += (features.confidence_score - 0.5) * 0.18

    return _clamp(score, -1.0, 1.0), reasons


def _score_type_plausibility(features: PatternFeatures, device_type: str) -> Tuple[float, List[str]]:
    p = 0.5
    reasons: List[str] = []

    power = features.avg_power_w
    duration = features.duration_s
    repeatability = features.repeatability_score
    stable = features.stability_score if features.stability_score is not None else 0.5

    if device_type == "fridge":
        if 70 <= power <= 350:
            p += 0.2
        else:
            p -= 0.18
        if 300 <= duration <= 3600:
            p += 0.18
        else:
            p -= 0.15
        if repeatability >= 0.55:
            p += 0.1
        if stable >= 0.62:
            p += 0.1
        if features.has_heating_pattern:
            p -= 0.12
            reasons.append("Fridge unplausibel: Heizmuster erkannt")

    elif device_type == "pump":
        if 120 <= power <= 1800:
            p += 0.18
        else:
            p -= 0.15
        if 60 <= duration <= 5400:
            p += 0.16
        else:
            p -= 0.12
        if stable >= 0.58:
            p += 0.14
        if features.has_motor_pattern:
            p += 0.1
        if features.coefficient_of_variation is not None and features.coefficient_of_variation > 0.55:
            p -= 0.08

    elif device_type == "kettle":
        if 1200 <= power <= 3200:
            p += 0.24
        else:
            p -= 0.24
            reasons.append("Kettle unplausibel: Leistung ausserhalb typischem Bereich")
        if 20 <= duration <= 420:
            p += 0.22
        else:
            p -= 0.28
            reasons.append("Kettle unplausibel wegen zu langer/kurzer Laufzeit")
        if features.has_heating_pattern:
            p += 0.08
        if features.plateau_count > 3:
            p -= 0.1

    elif device_type == "microwave":
        if 700 <= power <= 2200:
            p += 0.2
        else:
            p -= 0.18
        if 30 <= duration <= 1800:
            p += 0.18
        else:
            p -= 0.2
            reasons.append("Microwave unplausibel wegen Dauer")
        if features.has_multiple_modes or features.num_substates >= 2:
            p += 0.08
        if features.has_heating_pattern and power < 700:
            p -= 0.1

    elif device_type == "oven":
        if 900 <= power <= 4200:
            p += 0.2
        else:
            p -= 0.16
        if 600 <= duration <= 14400:
            p += 0.2
        else:
            p -= 0.16
        if features.has_heating_pattern:
            p += 0.12
        if features.dominant_levels_count >= 2:
            p += 0.08

    elif device_type == "heater":
        if 400 <= power <= 3500:
            p += 0.2
        else:
            p -= 0.14
        if duration >= 300:
            p += 0.18
        else:
            p -= 0.18
        if features.has_heating_pattern:
            p += 0.15
        if features.repeatability_score < 0.25:
            p -= 0.08

    if features.mixed_load_flag:
        p -= 0.16
        reasons.append("Mischlast-Risiko reduziert Typ-Plausibilitaet")

    if features.segmentation_risk:
        p -= 0.1

    if features.significant_jump_count >= 7 and device_type in {"kettle", "fridge", "pump"}:
        p -= 0.09

    return _clamp(p, 0.0, 1.0), reasons


def evaluate_pattern(features: PatternFeatures) -> PatternEvaluation:
    quality_core, quality_reasons = _score_common_quality(features)

    plausibility_by_type: Dict[str, float] = {}
    plausibility_reasons: Dict[str, List[str]] = {}
    for dtype in DEVICE_CLASSES:
        score, reasons = _score_type_plausibility(features, dtype)
        plausibility_by_type[dtype] = round(score, 4)
        plausibility_reasons[dtype] = reasons

    best_type = max(plausibility_by_type, key=plausibility_by_type.get)
    label_plausibility = plausibility_by_type.get(features.candidate_label, 0.3)

    sorted_types = sorted(plausibility_by_type.items(), key=lambda x: x[1], reverse=True)
    alternative_hints = [dtype for dtype, score in sorted_types if score >= 0.6 and dtype != features.candidate_label][:3]

    adjusted_confidence = features.confidence_score
    adjusted_confidence *= 0.55 + (label_plausibility * 0.45)

    if features.mixed_load_flag:
        adjusted_confidence *= 0.72
    if features.segmentation_risk:
        adjusted_confidence *= 0.8
    if features.seen_count < 3:
        adjusted_confidence *= 0.75

    adjusted_confidence = round(_clamp(adjusted_confidence, 0.0, 1.0), 4)

    total_score = quality_core + ((best_type and plausibility_by_type[best_type] - 0.5) * 0.8)
    total_score += (adjusted_confidence - 0.5) * 0.6

    reject_reasons: List[str] = []

    label_is_known = features.candidate_label in DEVICE_CLASSES
    if label_is_known and label_plausibility < 0.42:
        reject_reasons.append(f"Label `{features.candidate_label}` ist unplausibel")
    if features.energy_duration_power_ratio is not None:
        ratio = features.energy_duration_power_ratio
        if ratio < 0.42 or ratio > 2.1:
            reject_reasons.append("Energie-/Dauer-/Leistungs-Kombination unstimmig")
    if features.mixed_load_flag:
        reject_reasons.append("Hinweis auf Mischlast")
    if features.significant_jump_count >= 9:
        reject_reasons.append("Zu viele Lastspruenge")

    total_score = _clamp(total_score, -1.0, 1.0)

    if total_score >= 0.55 and adjusted_confidence >= 0.65 and not reject_reasons:
        quality_label = "sehr_gut"
    elif total_score >= 0.2 and adjusted_confidence >= 0.45 and len(reject_reasons) <= 1:
        quality_label = "brauchbar"
    elif total_score >= -0.15 and adjusted_confidence >= 0.25:
        quality_label = "unsicher"
    else:
        quality_label = "verwerfen"

    if label_is_known and quality_label in {"sehr_gut", "brauchbar"} and label_plausibility < 0.5:
        quality_label = "unsicher"

    reasoning_parts: List[str] = []
    reasoning_parts.extend(quality_reasons[:3])

    if label_is_known and label_plausibility < 0.5:
        reasoning_parts.append(f"Label `{features.candidate_label}` wirkt unplausibel")
    elif label_is_known and label_plausibility >= 0.72:
        reasoning_parts.append(f"Label `{features.candidate_label}` passt gut")

    for reason in plausibility_reasons.get(features.candidate_label, [])[:2]:
        if reason not in reasoning_parts:
            reasoning_parts.append(reason)

    if alternative_hints:
        reasoning_parts.append("Alternative Hinweise: " + ", ".join(alternative_hints))

    if not reasoning_parts:
        reasoning_parts.append("Keine starken Indizien, vorsichtige Bewertung")

    reasoning = "; ".join(reasoning_parts)

    return PatternEvaluation(
        quality_label=quality_label,
        quality_score=round((total_score + 1.0) / 2.0, 4),
        plausibility_by_type=plausibility_by_type,
        best_type=best_type,
        alternative_hints=alternative_hints,
        adjusted_confidence=adjusted_confidence,
        label_plausibility=round(label_plausibility, 4),
        reject_reasons=reject_reasons,
        reasoning=reasoning,
    )


def _flatten_for_csv(features: PatternFeatures, evaluation: PatternEvaluation) -> Dict[str, Any]:
    row = {
        "pattern_index": features.pattern_index,
        "pattern_id": features.pattern_id,
        "candidate_label": features.candidate_label,
        "best_type": evaluation.best_type,
        "quality_label": evaluation.quality_label,
        "quality_score": evaluation.quality_score,
        "adjusted_confidence": evaluation.adjusted_confidence,
        "label_plausibility": evaluation.label_plausibility,
        "seen_count": features.seen_count,
        "avg_power_w": round(features.avg_power_w, 3),
        "peak_power_w": round(features.peak_power_w, 3),
        "duration_s": round(features.duration_s, 3),
        "energy_wh": round(features.energy_wh, 3),
        "power_variance": round(features.power_variance, 5),
        "power_std": round(features.power_std, 5),
        "coefficient_of_variation": None if features.coefficient_of_variation is None else round(features.coefficient_of_variation, 5),
        "peak_to_avg_ratio": None if features.peak_to_avg_ratio is None else round(features.peak_to_avg_ratio, 5),
        "stability_score": features.stability_score,
        "repeatability_score": features.repeatability_score,
        "frequency_per_day": features.frequency_per_day,
        "duty_cycle": features.duty_cycle,
        "plateau_count": features.plateau_count,
        "dominant_levels_count": features.dominant_levels_count,
        "dominant_levels_w": "|".join(str(x) for x in features.dominant_levels_w),
        "significant_jump_count": features.significant_jump_count,
        "largest_jump_w": round(features.largest_jump_w, 3),
        "median_jump_w": round(features.median_jump_w, 3),
        "jump_density": round(features.jump_density, 5),
        "energy_duration_power_ratio": None
        if features.energy_duration_power_ratio is None
        else round(features.energy_duration_power_ratio, 5),
        "has_multiple_modes": features.has_multiple_modes,
        "operating_modes_count": features.operating_modes_count,
        "num_substates": features.num_substates,
        "has_heating_pattern": features.has_heating_pattern,
        "has_motor_pattern": features.has_motor_pattern,
        "mixed_load_flag": features.mixed_load_flag,
        "segmentation_risk": features.segmentation_risk,
        "alternative_hints": "|".join(evaluation.alternative_hints),
        "reject_reasons": "|".join(evaluation.reject_reasons),
        "reasoning": evaluation.reasoning,
    }
    for dtype, score in evaluation.plausibility_by_type.items():
        row[f"plausibility_{dtype}"] = score
    return row


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Input-Datei nicht gefunden: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungueltiges JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("JSON muss ein Objekt auf Root-Ebene enthalten")
    if "patterns" not in data:
        raise ValueError("JSON enthaelt kein Feld `patterns`")
    if not isinstance(data.get("patterns"), list):
        raise ValueError("Feld `patterns` muss eine Liste sein")
    return data


def _to_dict(features: PatternFeatures, evaluation: PatternEvaluation, original_pattern: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pattern_index": features.pattern_index,
        "pattern_id": features.pattern_id,
        "quality": {
            "label": evaluation.quality_label,
            "score": evaluation.quality_score,
            "adjusted_confidence": evaluation.adjusted_confidence,
            "label_plausibility": evaluation.label_plausibility,
        },
        "classification": {
            "candidate_label": features.candidate_label,
            "best_type": evaluation.best_type,
            "alternative_hints": evaluation.alternative_hints,
            "plausibility_by_type": evaluation.plausibility_by_type,
        },
        "features": {
            "seen_count": features.seen_count,
            "avg_power_w": features.avg_power_w,
            "peak_power_w": features.peak_power_w,
            "duration_s": features.duration_s,
            "energy_wh": features.energy_wh,
            "power_variance": features.power_variance,
            "power_std": features.power_std,
            "coefficient_of_variation": features.coefficient_of_variation,
            "duty_cycle": features.duty_cycle,
            "peak_to_avg_ratio": features.peak_to_avg_ratio,
            "stability_score": features.stability_score,
            "frequency_per_day": features.frequency_per_day,
            "repeatability_score": features.repeatability_score,
            "plateau_count": features.plateau_count,
            "dominant_levels_count": features.dominant_levels_count,
            "dominant_levels_w": features.dominant_levels_w,
            "significant_jump_count": features.significant_jump_count,
            "largest_jump_w": features.largest_jump_w,
            "median_jump_w": features.median_jump_w,
            "jump_density": features.jump_density,
            "energy_duration_power_ratio": features.energy_duration_power_ratio,
            "operating_modes_count": features.operating_modes_count,
            "has_multiple_modes": features.has_multiple_modes,
            "num_substates": features.num_substates,
            "has_heating_pattern": features.has_heating_pattern,
            "has_motor_pattern": features.has_motor_pattern,
            "typical_interval_s": features.typical_interval_s,
            "rise_rate_w_per_s": features.rise_rate_w_per_s,
            "fall_rate_w_per_s": features.fall_rate_w_per_s,
            "mixed_load_flag": features.mixed_load_flag,
            "segmentation_risk": features.segmentation_risk,
        },
        "reasons": {
            "reject_reasons": evaluation.reject_reasons,
            "summary": evaluation.reasoning,
        },
        "original_pattern": original_pattern,
    }


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def analyze_patterns(data: Dict[str, Any]) -> Dict[str, Any]:
    patterns: List[Dict[str, Any]] = [p for p in data.get("patterns", []) if isinstance(p, dict)]

    results: List[Dict[str, Any]] = []
    csv_rows: List[Dict[str, Any]] = []

    for idx, pattern in enumerate(patterns):
        features = extract_features(pattern, pattern_index=idx)
        evaluation = evaluate_pattern(features)

        results.append(_to_dict(features, evaluation, pattern))
        csv_rows.append(_flatten_for_csv(features, evaluation))

    quality_counts = Counter(item["quality"]["label"] for item in results)
    best_type_counts = Counter(item["classification"]["best_type"] for item in results)

    summary = {
        "pattern_count": len(results),
        "quality_counts": dict(quality_counts),
        "best_type_counts": dict(best_type_counts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assumptions": [
            "profile_points can contain numeric values or dicts with common power keys",
            "confidence_score is expected in [0..1]; values outside are clamped",
            "unknown candidate labels are treated conservatively",
        ],
        "next_stage_recommendation": {
            "title": "Stufe 2: ML-Klassifikation vorbereiten",
            "steps": [
                "Manuell validierte Labels pro Pattern sammeln",
                "Feature-Tabelle aus CSV als Trainingsmatrix nutzen",
                "Baseline mit sklearn (RandomForest / GradientBoosting) trainieren",
                "spaeter XGBoost/LightGBM mit Class-Weights fuer Imbalance testen",
                "Konfidenzkalibrierung und Reject-Option beibehalten",
            ],
        },
    }

    return {
        "summary": summary,
        "results": results,
        "csv_rows": csv_rows,
    }


def _print_console_summary(analysis: Dict[str, Any], output_dir: Path) -> None:
    summary = analysis["summary"]
    print(f"Patterns analysiert: {summary['pattern_count']}")
    print("Bewertungsverteilung:")
    for label in QUALITY_LABELS:
        print(f"  - {label}: {summary['quality_counts'].get(label, 0)}")

    print("Top Gerätetypen:")
    best_type_counts = summary.get("best_type_counts", {})
    for dtype, count in sorted(best_type_counts.items(), key=lambda x: x[1], reverse=True)[:6]:
        print(f"  - {dtype}: {count}")

    print(f"Ausgabeverzeichnis: {output_dir}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NILM Pattern Analyzer")
    parser.add_argument("input", type=Path, help="Pfad zur Export-JSON Datei")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Ausgabeordner")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        data = _read_json(args.input)
    except ValueError as exc:
        print(f"Fehler: {exc}")
        return 2

    analysis = analyze_patterns(data)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "pattern_features.csv"
    json_path = out_dir / "pattern_analysis.json"
    jsonl_path = out_dir / "pattern_analysis.jsonl"

    _write_csv(csv_path, analysis["csv_rows"])
    _write_json(
        json_path,
        {
            "summary": analysis["summary"],
            "results": analysis["results"],
        },
    )
    _write_jsonl(jsonl_path, analysis["results"])

    _print_console_summary(analysis, out_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
