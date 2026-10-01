"""Fully local attention reviewer for NILM reasoning.

Despite the historic class name, this module performs no HTTP requests and has
no external model dependency. It wraps the built-in attention classifier so
older storage code can keep the same interface while remaining standalone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.learning.attention_classifier import LocalAttentionClassifier


@dataclass
class AttentionReviewResult:
    label: str
    confidence: float
    device_family: str
    evidence: List[str]
    source: str = "local_attention"


class AttentionReviewer:
    """Local attention reviewer with zero network access."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        base_url: str = "",
        model: str = "",
        timeout_seconds: int = 20,
        min_confidence: float = 0.65,
        review_below_confidence: float = 0.78,
    ) -> None:
        self.enabled = bool(enabled)
        self.min_confidence = max(0.0, min(float(min_confidence), 1.0))
        self.review_below_confidence = max(0.0, min(float(review_below_confidence), 1.0))
        self._attention = LocalAttentionClassifier()

    @property
    def ready(self) -> bool:
        return self.enabled

    def should_review(self, *, current_label: str, current_confidence: float) -> bool:
        label = str(current_label or "").strip().lower()
        return self.enabled and (
            label in {"", "unknown", "unbekannt"}
            or float(current_confidence) < self.review_below_confidence
        )

    @staticmethod
    def _label_for_pattern(pattern: Dict[str, Any]) -> str:
        return str(
            pattern.get("user_label")
            or pattern.get("device_name")
            or pattern.get("suggestion_type")
            or pattern.get("label")
            or "unknown"
        ).strip()

    @staticmethod
    def _family(label: str) -> str:
        value = str(label or "").lower()
        if any(token in value for token in ("fridge", "freezer", "compressor", "kuehl", "kühl")):
            return "compressor"
        if "pump" in value or "pumpe" in value:
            return "pump"
        if any(token in value for token in ("motor", "fan", "luefter", "lüfter")):
            return "motor"
        if any(token in value for token in ("heater", "heiz", "boiler", "kettle")):
            return "resistive_heater"
        if any(token in value for token in ("oven", "koch", "stove")):
            return "cooking"
        if any(token in value for token in ("light", "lamp", "licht")):
            return "lighting"
        if value and value not in {"unknown", "unbekannt"}:
            return "electronics"
        return "unknown"

    def classify(
        self,
        *,
        cycle: Dict[str, Any],
        candidate_labels: Sequence[Any],
        similar_patterns: Sequence[Dict[str, Any]],
    ) -> Optional[AttentionReviewResult]:
        if not self.enabled:
            return None

        allowed = {
            str(label or "").strip()
            for label in candidate_labels
            if str(label or "").strip()
        }
        allowed.add("unknown")

        result = self._attention.predict(
            cycle=cycle,
            patterns=similar_patterns,
            label_fn=self._label_for_pattern,
            phase=str(cycle.get("phase") or ""),
        )
        if result is None:
            return None

        label = result.label if result.label in allowed else "unknown"
        evidence = [
            f"attention:{candidate}={score:.3f}"
            for candidate, score in result.top_n[:5]
        ]
        return AttentionReviewResult(
            label=label,
            confidence=float(result.confidence),
            device_family=self._family(label),
            evidence=evidence,
        )
