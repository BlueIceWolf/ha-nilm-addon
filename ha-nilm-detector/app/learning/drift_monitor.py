"""Pattern drift detection for long-term NILM learning."""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List

from app.learning.feature_vector_v2 import build_feature_vector_v2


@dataclass
class DriftResult:
    score: float
    level: str
    changed_features: List[str]


class DriftMonitor:
    def __init__(self, warning_threshold: float = 0.18, critical_threshold: float = 0.34):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold

    def compare(self, pattern: Dict[str, Any], event: Dict[str, Any]) -> DriftResult:
        a = build_feature_vector_v2(pattern)
        b = build_feature_vector_v2(event)
        if not a or len(a) != len(b):
            return DriftResult(0.0, "unknown", [])
        distances = [abs(x - y) / max(abs(x), abs(y), 1.0) for x, y in zip(a, b)]
        score = math.sqrt(sum(d * d for d in distances) / len(distances))
        ranked = sorted(range(len(distances)), key=lambda i: distances[i], reverse=True)[:5]
        from app.learning.feature_vector_v2 import FEATURE_NAMES
        changed = [FEATURE_NAMES[i] for i in ranked if distances[i] >= 0.12]
        if score >= self.critical_threshold:
            level = "critical"
        elif score >= self.warning_threshold:
            level = "warning"
        else:
            level = "normal"
        return DriftResult(min(score, 1.0), level, changed)
