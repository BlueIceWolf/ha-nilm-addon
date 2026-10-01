"""Champion/challenger lifecycle for local NILM classifiers."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from app.learning.feature_vector_v2 import build_feature_vector_v2


@dataclass
class ModelLifecycleStatus:
    champion_score: float = 0.0
    challenger_score: float = 0.0
    promoted: bool = False
    champion_name: str = "rf_default"
    challenger_name: str = "rf_candidate"


class RandomForestLifecycle:
    """Train a stable champion and evaluate lightweight challenger candidates."""

    CANDIDATES = (
        {"n_estimators": 100, "max_depth": 8, "min_samples_leaf": 2},
        {"n_estimators": 140, "max_depth": 12, "min_samples_leaf": 2},
        {"n_estimators": 120, "max_depth": None, "min_samples_leaf": 3},
    )

    def __init__(self) -> None:
        self.status = ModelLifecycleStatus()

    @staticmethod
    def _label(row: Dict[str, Any]) -> str:
        return str(row.get("user_label") or row.get("suggestion_type") or "").strip().lower()

    def train_select(self, rows: Sequence[Dict[str, Any]]):
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.model_selection import StratifiedKFold, cross_val_score
        except Exception:
            return None

        usable = [r for r in rows if self._label(r) not in {"", "unknown", "unbekannt"} and int(r.get("seen_count", 0) or 0) >= 2]
        labels = [self._label(r) for r in usable]
        if len(usable) < 10 or len(set(labels)) < 2:
            return None

        x = [build_feature_vector_v2(r) for r in usable]
        min_class = min(labels.count(label) for label in set(labels))
        folds = min(4, min_class)
        if folds < 2:
            return None
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)

        champion_params = {"n_estimators": 100, "max_depth": 10, "min_samples_leaf": 2}
        champion = RandomForestClassifier(random_state=42, n_jobs=1, class_weight="balanced_subsample", **champion_params)
        champion_score = float(cross_val_score(champion, x, labels, cv=cv, scoring="balanced_accuracy").mean())

        best_model = champion
        best_score = champion_score
        best_name = "rf_default"
        challenger_score = 0.0
        for idx, params in enumerate(self.CANDIDATES, start=1):
            candidate = RandomForestClassifier(random_state=42, n_jobs=1, class_weight="balanced_subsample", **params)
            score = float(cross_val_score(candidate, x, labels, cv=cv, scoring="balanced_accuracy").mean())
            challenger_score = max(challenger_score, score)
            if score >= best_score + 0.02:
                best_model, best_score, best_name = candidate, score, f"rf_candidate_{idx}"

        best_model.fit(x, labels)
        self.status = ModelLifecycleStatus(
            champion_score=champion_score,
            challenger_score=challenger_score,
            promoted=best_name != "rf_default",
            champion_name=best_name,
            challenger_name="grid_search_candidates",
        )
        return best_model
