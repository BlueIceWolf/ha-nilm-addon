"""Optional local LLM reviewer for NILM event classification.

The deterministic NILM pipeline remains responsible for segmentation, feature
extraction and pattern matching. This module only reviews ambiguous completed
events using a local Ollama-compatible HTTP API and structured JSON output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LocalLLMResult:
    label: str
    confidence: float
    device_family: str
    evidence: List[str]
    source: str = "local_llm"


class LocalLLMClassifier:
    """Review ambiguous NILM events with a local Ollama model."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "",
        model: str = "",
        timeout_seconds: int = 20,
        min_confidence: float = 0.65,
        review_below_confidence: float = 0.78,
    ) -> None:
        self.enabled = bool(enabled)
        self.base_url = str(base_url or "").rstrip("/")
        self.model = str(model or "").strip()
        self.timeout_seconds = max(2, min(int(timeout_seconds), 120))
        self.min_confidence = max(0.0, min(float(min_confidence), 1.0))
        self.review_below_confidence = max(0.0, min(float(review_below_confidence), 1.0))
        self._cache: Dict[str, LocalLLMResult] = {}

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.base_url) and bool(self.model)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _normalize_labels(labels: Iterable[Any]) -> List[str]:
        out: List[str] = []
        seen = set()
        for value in labels:
            label = str(value or "").strip()
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(label)
        if "unknown" not in seen:
            out.append("unknown")
        return out[:24]

    def should_review(self, *, current_label: str, current_confidence: float) -> bool:
        if not self.ready:
            return False
        label = str(current_label or "").strip().lower()
        return label in {"", "unknown", "unbekannt"} or float(current_confidence) < self.review_below_confidence

    def _compact_event(
        self,
        cycle: Dict[str, Any],
        candidates: Sequence[str],
        similar_patterns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        derived = dict(cycle.get("derived_features") or {})
        temporal = dict(cycle.get("temporal_features") or {})
        compact_patterns: List[Dict[str, Any]] = []
        for pattern in list(similar_patterns)[:8]:
            compact_patterns.append(
                {
                    "label": str(
                        pattern.get("user_label")
                        or pattern.get("device_name")
                        or pattern.get("suggestion_type")
                        or pattern.get("label")
                        or "unknown"
                    ),
                    "phase": str(pattern.get("phase") or ""),
                    "avg_power_w": round(self._safe_float(pattern.get("avg_power_w")), 2),
                    "peak_power_w": round(self._safe_float(pattern.get("peak_power_w")), 2),
                    "duration_s": round(self._safe_float(pattern.get("avg_duration_s", pattern.get("duration_s"))), 2),
                    "seen_count": int(self._safe_float(pattern.get("seen_count"), 0)),
                }
            )

        return {
            "phase": str(cycle.get("phase") or ""),
            "avg_power_w": round(self._safe_float(cycle.get("avg_power_w")), 2),
            "peak_power_w": round(self._safe_float(cycle.get("peak_power_w")), 2),
            "duration_s": round(self._safe_float(cycle.get("duration_s")), 2),
            "energy_wh": round(self._safe_float(cycle.get("energy_wh")), 4),
            "rise_rate_w_per_s": round(self._safe_float(cycle.get("rise_rate_w_per_s")), 2),
            "fall_rate_w_per_s": round(self._safe_float(cycle.get("fall_rate_w_per_s")), 2),
            "num_substates": int(self._safe_float(cycle.get("num_substates"), 0)),
            "step_count": int(self._safe_float(cycle.get("step_count"), 0)),
            "segmentation_confidence": round(self._safe_float(cycle.get("segmentation_confidence")), 4),
            "inrush_ratio": round(
                self._safe_float(derived.get("inrush_ratio", cycle.get("peak_to_avg_ratio"))),
                4,
            ),
            "normalized_variance": round(self._safe_float(derived.get("normalized_variance")), 4),
            "has_flat_plateau": bool(derived.get("has_flat_plateau", False)),
            "has_inrush_spike": bool(derived.get("has_inrush_spike", False)),
            "has_multi_stage_shape": bool(derived.get("has_multi_stage_shape", False)),
            "recurrence_interval_s": round(self._safe_float(temporal.get("recurrence_interval_s")), 2),
            "candidate_labels": list(candidates),
            "similar_known_patterns": compact_patterns,
        }

    @staticmethod
    def _response_schema(labels: Sequence[str]) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": list(labels)},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "device_family": {
                    "type": "string",
                    "enum": [
                        "compressor",
                        "pump",
                        "motor",
                        "resistive_heater",
                        "electronics",
                        "lighting",
                        "cooking",
                        "unknown",
                    ],
                },
                "evidence": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
            },
            "required": ["label", "confidence", "device_family", "evidence"],
            "additionalProperties": False,
        }

    def classify(
        self,
        *,
        cycle: Dict[str, Any],
        candidate_labels: Sequence[Any],
        similar_patterns: Sequence[Dict[str, Any]],
    ) -> Optional[LocalLLMResult]:
        if not self.ready:
            return None

        labels = self._normalize_labels(candidate_labels)
        event = self._compact_event(cycle, labels, similar_patterns)
        cache_key = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        schema = self._response_schema(labels)
        system_prompt = (
            "You classify electrical NILM events. Use only the provided measured "
            "features, candidate labels and similar learned patterns. Never invent "
            "a label outside the allowed list. Prefer unknown when evidence is "
            "ambiguous. Confidence must reflect evidence quality. Return only the "
            "requested structured JSON."
        )
        user_prompt = (
            "Review this completed NILM event and choose the most plausible allowed "
            "label. Treat phase, power, runtime, inrush, variance, substates and "
            "recurrence as evidence. Do not assume a specific appliance when the "
            "signature is not distinctive.\n\nEVENT:\n"
            + json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        )

        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": schema,
            "options": {"temperature": 0},
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            raw_content = ((body.get("message") or {}).get("content") or "").strip()
            parsed = json.loads(raw_content)
        except Exception as exc:
            logger.warning("Local LLM review failed: %s", exc)
            return None

        label = str(parsed.get("label") or "unknown").strip()
        if label not in labels:
            label = "unknown"
        confidence = max(0.0, min(self._safe_float(parsed.get("confidence")), 1.0))
        evidence = [str(item)[:160] for item in list(parsed.get("evidence") or [])[:5]]
        result = LocalLLMResult(
            label=label,
            confidence=confidence,
            device_family=str(parsed.get("device_family") or "unknown"),
            evidence=evidence,
        )

        if len(self._cache) >= 256:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = result
        return result
