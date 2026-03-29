"""Optional local ML classifier for NILM pattern/event labeling.

Phase 1 hybrid-ML kickoff:
- Prefer gradient boosting (tabular features)
- Keep safe RandomForest fallback
- Prioritize confirmed/user-labeled patterns for cleaner training
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.utils.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_CLASSES = {
    "fridge",
    "pump",
    "heater",
    "kettle",
    "microwave",
    "washing_machine",
    "dishwasher",
    "unknown",
}

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


class LocalMLClassifier:
    """Local optional boosting-first classifier with safe fallbacks."""

    def __init__(self) -> None:
        self._model: Any = None
        self._labels: List[str] = []
        self._trained = False
        self._fingerprint: Tuple[int, str] = (0, "")
        self._model_source = "ml_unavailable"

    @staticmethod
    def _normalize_label(label: object) -> str:
        raw = str(label or "").strip().lower().replace(" ", "_")
        if not raw:
            return "unknown"
        if raw in _ALIAS_MAP:
            return _ALIAS_MAP[raw]
        if raw not in SUPPORTED_CLASSES:
            return "unknown"
        return raw

    @staticmethod
    def _to_features(row: Dict[str, Any]) -> List[float]:
        def f(key: str, default: float = 0.0) -> float:
            try:
                return float(row.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return default

        def b(key: str) -> float:
            return 1.0 if bool(row.get(key, False)) else 0.0

        return [
            f("avg_power_w"),
            f("peak_power_w"),
            f("duration_s"),
            f("energy_wh"),
            f("power_variance"),
            f("rise_rate_w_per_s"),
            f("fall_rate_w_per_s"),
            f("duty_cycle"),
            f("peak_to_avg_ratio", 1.0),
            f("num_substates"),
            f("avg_active_phases", 1.0),
            b("has_heating_pattern"),
            b("has_motor_pattern"),
        ]

    def _ensure_trained(self, patterns: Sequence[Dict[str, Any]]) -> bool:
        fingerprint = (len(patterns), max((str(p.get("updated_at") or "") for p in patterns), default=""))
        if self._trained and fingerprint == self._fingerprint:
            return True

        try:
            from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # type: ignore
        except Exception:
            self._model = None
            self._labels = []
            self._trained = False
            self._model_source = "ml_unavailable"
            return False

        x_train: List[List[float]] = []
        y_train: List[str] = []

        for pattern in patterns:
            label = self._normalize_label(pattern.get("user_label") or pattern.get("suggestion_type") or "unknown")
            if label == "unknown":
                continue

            # Prefer trustworthy labels for online training.
            has_user_label = bool(str(pattern.get("user_label") or "").strip())
            is_confirmed = bool(pattern.get("is_confirmed"))
            if not (has_user_label or is_confirmed):
                continue

            seen_count = int(pattern.get("seen_count", 0) or 0)
            if seen_count < 2:
                continue
            x_train.append(self._to_features(pattern))
            y_train.append(label)

        if len(x_train) < 8 or len(set(y_train)) < 2:
            self._trained = False
            self._model = None
            self._labels = []
            self._fingerprint = fingerprint
            self._model_source = "ml_insufficient_data"
            return False

        model: Any = None
        model_source = "ml_boosting"
        try:
            model = HistGradientBoostingClassifier(
                max_depth=6,
                max_iter=180,
                learning_rate=0.08,
                min_samples_leaf=4,
                random_state=42,
            )
            model.fit(x_train, y_train)
        except Exception:
            # Conservative fallback when boosting fails on edge environments.
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=1,
            )
            model.fit(x_train, y_train)
            model_source = "ml_random_forest_fallback"

        self._model = model
        self._labels = list(model.classes_)
        self._trained = True
        self._fingerprint = fingerprint
        self._model_source = model_source
        return True

    def predict(self, patterns: Sequence[Dict[str, Any]], cycle: Dict[str, Any], confidence_threshold: float = 0.55) -> MLPrediction:
        if not self._ensure_trained(patterns):
            return MLPrediction(label="unknown", confidence=0.0, top_n=[], source=self._model_source)

        assert self._model is not None
        vec = [self._to_features(cycle)]
        probs = self._model.predict_proba(vec)[0]
        indexed = sorted(zip(self._labels, probs), key=lambda item: item[1], reverse=True)
        top_n = [{"label": str(label), "score": float(score)} for label, score in indexed[:3]]

        best_label, best_score = indexed[0]
        if float(best_score) < confidence_threshold:
            return MLPrediction(label="unknown", confidence=float(best_score), top_n=top_n, source="ml_low_confidence")

        return MLPrediction(
            label=self._normalize_label(best_label),
            confidence=float(best_score),
            top_n=top_n,
            source=self._model_source,
        )
