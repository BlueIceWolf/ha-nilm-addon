"""Unified learning quality filter for NILM events."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class LearningDecision:
    tier: str
    score: float
    accepted: bool
    reasons: List[str] = field(default_factory=list)


class LearningFilterV2:
    def __init__(self, provisional_threshold: float = 0.45, stable_threshold: float = 0.72):
        self.provisional_threshold = provisional_threshold
        self.stable_threshold = stable_threshold

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(self, event: Dict[str, Any]) -> LearningDecision:
        score = 1.0
        reasons: List[str] = []
        sample_count = int(self._f(event.get("sample_count", len(event.get("waveform_points") or event.get("profile_points") or []))))
        seg = self._f(event.get("segmentation_confidence"), 0.0)
        wave = self._f(event.get("waveform_completeness_score"), 0.0)
        baseline = self._f(event.get("baseline_quality_score"), 0.5)
        overlap = self._f(event.get("overlap_score"), 0.0)

        checks = [
            (bool(event.get("truncated_start")), 0.24, "truncated_start"),
            (bool(event.get("truncated_end")), 0.20, "truncated_end"),
            (sample_count < 4, 0.22, "too_few_samples"),
            (seg < 0.40, 0.30, "weak_segmentation"),
            (wave < 0.35, 0.22, "incomplete_waveform"),
            (baseline < 0.25, 0.24, "unstable_baseline"),
            (overlap >= 0.65, 0.32, "probable_multi_device_overlap"),
        ]
        for failed, penalty, reason in checks:
            if failed:
                score -= penalty
                reasons.append(reason)

        duration = self._f(event.get("duration_s"))
        avg = self._f(event.get("avg_power_w"))
        if duration <= 0.0 or avg <= 0.0:
            score -= 0.35
            reasons.append("invalid_event_metrics")

        score = max(0.0, min(score, 1.0))
        if score >= self.stable_threshold:
            return LearningDecision("stable", score, True, reasons or ["clean_event"])
        if score >= self.provisional_threshold:
            return LearningDecision("provisional", score, True, reasons or ["medium_quality"])
        return LearningDecision("blocked", score, False, reasons or ["quality_below_threshold"])
