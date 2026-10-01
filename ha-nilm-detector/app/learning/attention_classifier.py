"""Self-contained attention-style classifier for NILM patterns.

This module implements a lightweight query/key/value style classifier over
learned event prototypes. It is inspired by attention mechanisms but requires
no external model, service or network access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple


@dataclass
class AttentionResult:
    label: str
    confidence: float
    top_n: List[Tuple[str, float]]
    source: str = "local_attention"


class LocalAttentionClassifier:
    """Classify events by attention-weighted similarity to learned patterns."""

    FEATURE_KEYS = (
        "avg_power_w",
        "peak_power_w",
        "duration_s",
        "energy_wh",
        "rise_rate_w_per_s",
        "fall_rate_w_per_s",
        "inrush_ratio",
        "normalized_variance",
        "num_substates",
        "step_count",
    )

    def __init__(self, temperature: float = 0.18, min_similarity: float = 0.35) -> None:
        self.temperature = max(0.03, min(float(temperature), 1.0))
        self.min_similarity = max(0.0, min(float(min_similarity), 1.0))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
            return out if math.isfinite(out) else float(default)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _feature_value(cls, item: Dict[str, Any], key: str) -> float:
        derived = dict(item.get("derived_features") or {})
        if key in derived:
            return cls._safe_float(derived.get(key))
        if key == "inrush_ratio":
            avg = max(cls._safe_float(item.get("avg_power_w")), 1.0)
            peak = cls._safe_float(item.get("peak_power_w"), avg)
            return cls._safe_float(item.get("peak_to_avg_ratio"), peak / avg)
        if key == "normalized_variance":
            return cls._safe_float(item.get("power_variance")) / max(
                cls._safe_float(item.get("avg_power_w")), 1.0
            )
        return cls._safe_float(item.get(key))

    @classmethod
    def _vector(cls, item: Dict[str, Any]) -> List[float]:
        raw = [cls._feature_value(item, key) for key in cls.FEATURE_KEYS]

        # Log scaling makes watts, duration and energy comparable while keeping
        # the classifier robust across small and large household loads.
        scaled = [
            math.copysign(math.log1p(abs(value)), value)
            for value in raw
        ]
        norm = math.sqrt(sum(value * value for value in scaled))
        if norm <= 1e-9:
            return [0.0 for _ in scaled]
        return [value / norm for value in scaled]

    @staticmethod
    def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        return max(-1.0, min(1.0, dot))

    @staticmethod
    def _softmax(values: Sequence[float], temperature: float) -> List[float]:
        if not values:
            return []
        peak = max(values)
        exps = [math.exp((value - peak) / temperature) for value in values]
        total = sum(exps)
        if total <= 0.0:
            return [0.0 for _ in values]
        return [value / total for value in exps]

    def predict(
        self,
        *,
        cycle: Dict[str, Any],
        patterns: Sequence[Dict[str, Any]],
        label_fn: Callable[[Dict[str, Any]], str],
        phase: str = "",
    ) -> AttentionResult | None:
        query = self._vector(cycle)
        if not any(query):
            return None

        candidates: List[Tuple[str, float, int]] = []
        for pattern in patterns:
            label = str(label_fn(pattern) or "").strip()
            if not label or label.lower() in {"unknown", "unbekannt"}:
                continue

            pattern_phase = str(pattern.get("phase") or "")
            if phase and pattern_phase in {"L1", "L2", "L3"} and pattern_phase != phase:
                continue

            similarity = self._cosine(query, self._vector(pattern))
            if similarity < self.min_similarity:
                continue

            seen_count = max(1, int(self._safe_float(pattern.get("seen_count"), 1)))
            candidates.append((label, similarity, seen_count))

        if not candidates:
            return None

        attention_logits = [
            similarity + min(math.log1p(seen_count) / 20.0, 0.15)
            for _, similarity, seen_count in candidates
        ]
        weights = self._softmax(attention_logits, self.temperature)

        label_scores: Dict[str, float] = {}
        for (label, _, _), weight in zip(candidates, weights):
            label_scores[label] = label_scores.get(label, 0.0) + weight

        ranked = sorted(label_scores.items(), key=lambda item: item[1], reverse=True)
        best_label, best_score = ranked[0]

        # Margin matters: two near-equal labels should remain uncertain.
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, best_score - second_score)
        confidence = max(0.0, min(1.0, (0.72 * best_score) + (0.28 * margin)))

        return AttentionResult(
            label=best_label,
            confidence=confidence,
            top_n=[(label, round(score, 4)) for label, score in ranked[:5]],
        )
