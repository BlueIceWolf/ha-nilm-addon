"""Explainable local NILM ensemble fusion."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class EnsembleResult:
    label: str
    confidence: float
    ranking: List[Tuple[str, float]]
    agreement: float


class EnsembleClassifier:
    WEIGHTS = {
        "prototype": 0.22,
        "shape": 0.20,
        "ml": 0.24,
        "attention": 0.18,
        "temporal": 0.10,
        "rule": 0.06,
    }

    def combine(self, votes: Dict[str, Tuple[str, float]]) -> EnsembleResult | None:
        scores: Dict[str, float] = {}
        total_weight = 0.0
        for source, (label, confidence) in votes.items():
            label = str(label or "").strip()
            if not label or label.lower() in {"unknown", "unbekannt"}:
                continue
            weight = self.WEIGHTS.get(source, 0.0)
            if weight <= 0.0:
                continue
            c = max(0.0, min(float(confidence), 1.0))
            scores[label] = scores.get(label, 0.0) + weight * c
            total_weight += weight
        if not scores or total_weight <= 0.0:
            return None
        normalized = {k: v / total_weight for k, v in scores.items()}
        ranking = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
        best_label, best_score = ranking[0]
        second = ranking[1][1] if len(ranking) > 1 else 0.0
        agreement = max(0.0, min(1.0, best_score - second + 0.5))
        confidence = max(0.0, min(0.99, best_score * (0.75 + 0.25 * agreement)))
        return EnsembleResult(best_label, confidence, ranking[:5], agreement)
