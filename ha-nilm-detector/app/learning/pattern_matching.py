"""Hybrid pattern matching and scoring utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.learning.shape_similarity import blended_shape_similarity

# Minimum aggregate confidence to emit a definitive label.
# Results below this threshold are down-graded to "unknown".
CONFIDENCE_UNKNOWN_THRESHOLD = 0.60


@dataclass
class ConfidenceBreakdown:
    """Structured per-component confidence as required by the spec."""
    shape: float = 0.0
    duration: float = 0.0
    repeatability: float = 0.0
    ml: float = 0.0

    @property
    def total(self) -> float:
        # Weighted combination: shape 35%, duration 20%, repeatability 25%, ml 20%
        return min(
            0.35 * self.shape
            + 0.20 * self.duration
            + 0.25 * self.repeatability
            + 0.20 * self.ml,
            1.0,
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "shape": round(self.shape, 4),
            "duration": round(self.duration, 4),
            "repeatability": round(self.repeatability, 4),
            "ml": round(self.ml, 4),
            "total": round(self.total, 4),
        }


@dataclass
class HybridMatchResult:
    best_group: str
    best_label: str
    confidence: float
    prototype_confidence: float
    shape_confidence: float
    repeatability: float
    best_distance: Optional[float]
    explain: Dict[str, Any]
    # Structured breakdown – new field; always populated
    confidence_breakdown: ConfidenceBreakdown = field(default_factory=ConfidenceBreakdown)
    # Label before unknown-threshold downgrade (None if no downgrade happened)
    original_label: Optional[str] = None


class HybridPatternMatcher:
    """Combines prototype distance with shape and temporal similarity."""

    def __init__(self, match_threshold: float = 0.45, shape_matching_enabled: bool = True):
        self.match_threshold = max(0.05, min(float(match_threshold), 0.95))
        self.shape_matching_enabled = bool(shape_matching_enabled)

    @staticmethod
    def _rel(a: float, b: float) -> float:
        base = max(abs(a), abs(b), 1.0)
        return abs(a - b) / base

    def match(
        self,
        cycle: Dict[str, Any],
        patterns: Sequence[Dict[str, Any]],
        distance_fn,
        group_key_fn,
    ) -> Optional[HybridMatchResult]:
        score_by_group: Dict[str, float] = {}
        shape_by_group: Dict[str, float] = {}
        group_display_label: Dict[str, str] = {}
        best_item_by_group: Dict[str, Dict[str, Any]] = {}
        total_score = 0.0

        cycle_phase_mode = str(cycle.get("phase_mode") or "unknown")
        cycle_phase = str(cycle.get("phase") or "L1")

        best_distance_overall: Optional[float] = None
        cycle_hour: Optional[float] = None
        try:
            cycle_end_dt = datetime.fromisoformat(str(cycle.get("end_ts") or ""))
            cycle_hour = float(cycle_end_dt.hour) + (float(cycle_end_dt.minute) / 60.0)
        except (TypeError, ValueError):
            cycle_hour = None

        for item in patterns:
            if item.get("status") != "active":
                continue

            item_phase_mode = str(item.get("phase_mode") or "unknown")
            item_phase = str(item.get("phase") or "L1")
            if cycle_phase_mode == "single_phase" and item_phase_mode == "single_phase" and item_phase != cycle_phase:
                continue

            label_raw = str(item.get("user_label") or item.get("suggestion_type") or "").strip()
            if not label_raw:
                continue

            group_key = str(group_key_fn(item))
            if group_key not in group_display_label or str(item.get("user_label") or "").strip():
                group_display_label[group_key] = str(item.get("user_label") or "").strip() or group_key

            distance = float(distance_fn(item, cycle))
            if best_distance_overall is None or distance < best_distance_overall:
                best_distance_overall = distance

            similarity = math.exp(-4.0 * max(distance, 0.0))
            seen_weight = 1.0 + math.log1p(max(int(item.get("seen_count", 1)), 1))
            quality_weight = 0.6 + (max(0.0, min(1.0, float(item.get("quality_score_avg", 0.5)))) * 0.8)

            runtime_weight = 1.0
            try:
                runtime_dist = self._rel(float(item.get("duration_s", 0.0)), float(cycle.get("duration_s", 0.0)))
                runtime_weight = max(0.75, 1.0 - min(runtime_dist, 1.0) * 0.25)
            except (TypeError, ValueError):
                runtime_weight = 1.0

            spike_weight = 1.0
            try:
                item_ratio = float(item.get("peak_to_avg_ratio", 1.0))
                cycle_ratio = float(cycle.get("peak_to_avg_ratio", 1.0))
                spike_dist = self._rel(item_ratio, cycle_ratio)
                spike_weight = max(0.75, 1.0 - min(spike_dist, 1.0) * 0.25)
            except (TypeError, ValueError):
                spike_weight = 1.0

            temporal_weight = 1.0
            if cycle_hour is not None:
                try:
                    expected_hour = float(item.get("avg_hour_of_day", 12.0))
                    hour_diff = abs(cycle_hour - expected_hour)
                    hour_diff = min(hour_diff, 24.0 - hour_diff)
                    temporal_weight = max(0.75, 1.0 - ((hour_diff / 12.0) * 0.25))
                except (TypeError, ValueError):
                    temporal_weight = 1.0

            shape_score = 0.0
            if self.shape_matching_enabled:
                shape_score = blended_shape_similarity(cycle.get("profile_points", []), item.get("profile_points", []))
                shape_by_group[group_key] = max(shape_by_group.get(group_key, 0.0), shape_score)

            similarity_hybrid = (0.72 * similarity) + (0.28 * shape_score if self.shape_matching_enabled else 0.0)
            vote = similarity_hybrid * seen_weight * quality_weight * temporal_weight * runtime_weight * spike_weight
            if vote <= 0.0:
                continue

            score_by_group[group_key] = score_by_group.get(group_key, 0.0) + vote
            total_score += vote

            best_existing = best_item_by_group.get(group_key)
            if best_existing is None or distance < float(best_existing.get("distance", 999.0)):
                best_item_by_group[group_key] = {
                    "distance": distance,
                    "shape_score": shape_score,
                    "seen_count": int(item.get("seen_count", 0) or 0),
                }

        if not score_by_group or total_score <= 0.0:
            return None

        best_group, best_score = max(score_by_group.items(), key=lambda pair: pair[1])
        best_label = group_display_label.get(best_group, best_group)
        prototype_confidence = float(best_score / total_score)
        best_meta = best_item_by_group.get(best_group, {})
        repeatability = min(1.0, math.log1p(float(best_meta.get("seen_count", 1))) / 3.0)
        shape_confidence = float(shape_by_group.get(best_group, 0.0))

        confidence = (
            (0.62 * prototype_confidence)
            + (0.23 * shape_confidence if self.shape_matching_enabled else 0.0)
            + (0.15 * repeatability)
        )
        confidence = max(0.0, min(1.0, confidence))

        # Duration confidence: how close is the cycle duration to the pattern's?
        duration_confidence = 1.0 - min(
            float(best_item_by_group.get(best_group, {}).get("distance", 0.0)), 1.0
        )

        breakdown = ConfidenceBreakdown(
            shape=shape_confidence,
            duration=duration_confidence,
            repeatability=repeatability,
            ml=prototype_confidence,
        )

        # Down-grade to "unknown" when aggregate confidence is below threshold
        original_label: Optional[str] = None
        effective_label = best_label
        if confidence < CONFIDENCE_UNKNOWN_THRESHOLD and best_label.lower() not in ("unknown", "unbekannt"):
            original_label = best_label
            effective_label = "unknown"

        return HybridMatchResult(
            best_group=best_group,
            best_label=effective_label,
            confidence=confidence,
            prototype_confidence=prototype_confidence,
            shape_confidence=shape_confidence,
            repeatability=repeatability,
            best_distance=best_distance_overall,
            confidence_breakdown=breakdown,
            original_label=original_label,
            explain={
                "best_group": best_group,
                "prototype_confidence": round(prototype_confidence, 4),
                "shape_confidence": round(shape_confidence, 4),
                "repeatability": round(repeatability, 4),
                "best_distance": round(float(best_distance_overall or 0.0), 4),
                "match_threshold": self.match_threshold,
                "confidence_breakdown": breakdown.as_dict(),
                "original_label": original_label,
                "downgraded_to_unknown": original_label is not None,
            },
        )

