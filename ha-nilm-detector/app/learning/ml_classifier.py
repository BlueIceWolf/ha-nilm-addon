"""Self-contained champion/challenger ML classifier for NILM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from app.learning.feature_vector_v2 import FEATURE_NAMES, build_feature_vector_v2
from app.learning.model_lifecycle import RandomForestLifecycle
from app.utils.logging import get_logger

logger = get_logger(__name__)

_ALIAS_MAP = {
    "kuehlschrank": "fridge",
    "kuhlschrank": "fridge",
    "wasserkocher": "kettle",
    "mikrowelle": "microwave",
    "heizung": "heater",
    "waermepumpe": "pump",
    "space_heater": "heater",
}


@dataclass
class MLPrediction:
    label: str
    confidence: float
    top_n: List[Dict[str, float]]
    source: str
    model_info: Dict[str, Any] | None = None


class LocalMLClassifier:
    """Local RandomForest with shadow evaluation and guarded promotion."""

    def __init__(self) -> None:
        self._model: Any = None
        self._labels: List[str] = []
        self._trained = False
        self._fingerprint: Tuple[int, str, int] = (0, "", 0)
        self._lifecycle = RandomForestLifecycle()

    @staticmethod
    def _normalize_label(label: object) -> str:
        raw = str(label or "").strip().lower().replace(" ", "_")
        if not raw:
            return "unknown"
        return _ALIAS_MAP.get(raw, raw)

    @staticmethod
    def _to_features(row: Dict[str, Any]) -> List[float]:
        return build_feature_vector_v2(row)

    def _ensure_trained(self, patterns: Sequence[Dict[str, Any]]) -> bool:
        confirmed = sum(
            1 for p in patterns
            if bool(p.get("is_confirmed")) or bool(p.get("user_label"))
        )
        fingerprint = (
            len(patterns),
            max((str(p.get("updated_at") or "") for p in patterns), default=""),
            confirmed,
        )
        if self._trained and fingerprint == self._fingerprint:
            return True

        model = self._lifecycle.train_select(patterns)
        if model is None:
            self._model = None
            self._labels = []
            self._trained = False
            self._fingerprint = fingerprint
            return False

        self._model = model
        self._labels = list(model.classes_)
        self._trained = True
        self._fingerprint = fingerprint
        return True

    def predict(
        self,
        patterns: Sequence[Dict[str, Any]],
        cycle: Dict[str, Any],
        confidence_threshold: float = 0.55,
    ) -> MLPrediction:
        if not self._ensure_trained(patterns):
            return MLPrediction(
                label="unknown",
                confidence=0.0,
                top_n=[],
                source="ml_unavailable",
                model_info={
                    "champion_score": self._lifecycle.status.champion_score,
                    "challenger_score": self._lifecycle.status.challenger_score,
                    "promoted": self._lifecycle.status.promoted,
                },
            )

        assert self._model is not None
        probs = self._model.predict_proba([self._to_features(cycle)])[0]
        indexed = sorted(zip(self._labels, probs), key=lambda item: item[1], reverse=True)
        top_n = [{"label": str(label), "score": float(score)} for label, score in indexed[:5]]
        best_label, best_score = indexed[0]
        status = self._lifecycle.status
        importances = []
        try:
            raw_importances = list(getattr(self._model, "feature_importances_", []) or [])
            importances = sorted(
                (
                    {"feature": FEATURE_NAMES[idx], "importance": round(float(value), 4)}
                    for idx, value in enumerate(raw_importances)
                    if idx < len(FEATURE_NAMES)
                ),
                key=lambda item: item["importance"],
                reverse=True,
            )[:8]
        except Exception:
            importances = []

        info = {
            "champion_score": round(float(status.champion_score), 4),
            "challenger_score": round(float(status.challenger_score), 4),
            "promoted": bool(status.promoted),
            "active_model": status.champion_name,
            "feature_importance": importances,
        }

        if float(best_score) < confidence_threshold:
            return MLPrediction(
                label="unknown",
                confidence=float(best_score),
                top_n=top_n,
                source="ml_low_confidence",
                model_info=info,
            )

        return MLPrediction(
            label=self._normalize_label(best_label),
            confidence=float(best_score),
            top_n=top_n,
            source="ml_random_forest_shadow_promoted" if status.promoted else "ml_random_forest",
            model_info=info,
        )
