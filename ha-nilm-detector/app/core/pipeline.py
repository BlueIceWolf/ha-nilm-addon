"""Modular NILM processing pipeline.

Each stage returns its result plus debug data so every decision is traceable.
The pipeline orchestrates existing components (ProcessingPipeline,
PatternLearner, storage) without duplicating their logic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.models import PowerReading
from app.core.overlap import estimate_overlap_score, process_signal
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.processing.pipeline import ProcessingPipeline
    from app.learning.pattern_learner import PatternLearner, LearnedCycle
    from app.storage.sqlite_store import SQLiteStore

logger = get_logger(__name__)


def _json_safe(value: Any) -> Any:
    """Best-effort conversion to JSON-serializable values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


@dataclass
class StageResult:
    """Result from a single pipeline stage."""
    stage: str
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def __repr__(self) -> str:
        return f"<StageResult stage={self.stage!r} ok={self.ok} data_keys={list(self.data)}>"


@dataclass
class PipelineResult:
    """Aggregated output from one ``process_sample`` call."""
    timestamp: datetime
    phase: str

    # Stage outputs – always present; data may be empty if stage was skipped
    baseline: StageResult
    edges: StageResult
    events: StageResult
    cycles: StageResult
    features: StageResult
    classification: StageResult
    persistence: StageResult

    @property
    def cycle_completed(self) -> bool:
        return bool(self.cycles.data.get("cycle_completed"))

    @property
    def label(self) -> Optional[str]:
        return self.classification.data.get("label")

    @property
    def confidence(self) -> float:
        return float(self.classification.data.get("confidence", 0.0))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "phase": self.phase,
            "cycle_completed": self.cycle_completed,
            "label": self.label,
            "confidence": self.confidence,
            "stages": {
                "baseline": _json_safe(self.baseline.data),
                "edges": _json_safe(self.edges.data),
                "events": _json_safe(self.events.data),
                "cycles": _json_safe(self.cycles.data),
                "features": _json_safe(self.features.data),
                "classification": _json_safe(self.classification.data),
                "persistence": _json_safe(self.persistence.data),
            },
            "errors": {
                k: v
                for k, v in {
                    "baseline": self.baseline.error,
                    "edges": self.edges.error,
                    "events": self.events.error,
                    "cycles": self.cycles.error,
                    "features": self.features.error,
                    "classification": self.classification.error,
                    "persistence": self.persistence.error,
                }.items()
                if v is not None
            },
        }


class NILMPipeline:
    """Orchestrates the full NILM processing chain for one phase.

    Usage::

        pipeline = NILMPipeline(
            processing_pipeline=...,
            learner=...,
            storage=...,
        )
        result: PipelineResult = pipeline.process_sample(reading)
        print(result.as_dict())

    Each stage produces a :class:`StageResult` with a ``data`` dict containing
    all intermediate values so the Web UI / debug tab can expose them without
    touching the underlying components.
    """

    def __init__(
        self,
        processing_pipeline: "ProcessingPipeline",
        learner: "PatternLearner",
        storage: Optional["SQLiteStore"] = None,
        heuristic_suggest_fn=None,
    ):
        self._processing = processing_pipeline
        self._learner = learner
        self._storage = storage
        self._heuristic_suggest_fn = heuristic_suggest_fn

        # Rolling debug buffer: last N results available for the debug tab
        self._debug_buffer: List[Dict[str, Any]] = []
        self._debug_buffer_size = 200

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_sample(self, reading: PowerReading) -> PipelineResult:
        """Run one power sample through the full pipeline.

        Never raises – all exceptions are caught per stage and recorded in
        the ``StageResult.error`` field so callers always get a result.
        """
        phase = str(reading.phase or "L1")

        # Stage 1 – Baseline / smoothing
        baseline_stage = self._stage_baseline(reading)

        # Stage 2 – Edge / threshold detection (reported from learner state)
        smoothed_reading = baseline_stage.data.get("smoothed_reading", reading)
        edges_stage = self._stage_edges(smoothed_reading, baseline_stage.data.get("baseline_w", 0.0))

        # Stage 3 – Event segmentation (learner ingests sample, may emit cycle)
        events_stage, completed_cycle = self._stage_events(smoothed_reading)

        # Stage 4 – Cycle builder result
        cycles_stage = self._stage_cycles(completed_cycle)

        # Stage 5 – Feature extraction
        features_stage = self._stage_features(completed_cycle)

        # Stage 6 – Classification
        classification_stage = self._stage_classification(completed_cycle, features_stage)

        # Stage 7 – Persistence
        persistence_stage = self._stage_persistence(completed_cycle, classification_stage, phase)

        result = PipelineResult(
            timestamp=reading.timestamp,
            phase=phase,
            baseline=baseline_stage,
            edges=edges_stage,
            events=events_stage,
            cycles=cycles_stage,
            features=features_stage,
            classification=classification_stage,
            persistence=persistence_stage,
        )

        self._append_debug(result)
        return result

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def _stage_baseline(self, reading: PowerReading) -> StageResult:
        """Apply smoothing and adaptive baseline correction."""
        try:
            smoothed = self._processing.process(reading)
            baseline_w = float(getattr(self._processing, "_baseline_power", 0.0))
            return StageResult(
                stage="baseline",
                ok=True,
                data={
                    "raw_power_w": float(reading.power_w),
                    "smoothed_power_w": float(smoothed.power_w),
                    "baseline_w": baseline_w,
                    "delta_w": float(smoothed.power_w) - baseline_w,
                    "smoothed_reading": smoothed,
                },
            )
        except Exception as exc:
            logger.warning("baseline stage error: %s", exc)
            return StageResult(stage="baseline", ok=False, data={
                "raw_power_w": float(reading.power_w),
                "smoothed_reading": reading,
            }, error=str(exc))

    def _stage_edges(self, reading: PowerReading, baseline_w: float) -> StageResult:
        """Report current edge-detection state from the learner."""
        try:
            learner = self._learner
            is_on = getattr(learner, "_is_on", None)
            if is_on is None:
                # Check inside the adaptive detector if available
                aed = getattr(learner, "_adaptive_detector", None)
                is_on = bool(getattr(aed, "_is_on", False)) if aed else False

            on_threshold_w = baseline_w + float(getattr(learner, "adaptive_on_offset_w", 30.0))
            off_threshold_w = baseline_w + float(getattr(learner, "adaptive_off_offset_w", 10.0))

            above_on = float(reading.power_w) >= on_threshold_w
            below_off = float(reading.power_w) <= off_threshold_w

            return StageResult(
                stage="edges",
                ok=True,
                data={
                    "power_w": float(reading.power_w),
                    "baseline_w": baseline_w,
                    "on_threshold_w": on_threshold_w,
                    "off_threshold_w": off_threshold_w,
                    "above_on_threshold": above_on,
                    "below_off_threshold": below_off,
                    "detector_is_on": bool(is_on),
                },
            )
        except Exception as exc:
            logger.warning("edges stage error: %s", exc)
            return StageResult(stage="edges", ok=False, error=str(exc))

    def _stage_events(self, reading: PowerReading):  # -> Tuple[StageResult, Optional[LearnedCycle]]
        """Feed sample to the pattern learner; detect cycle completion."""
        try:
            was_on_before = self._learner_is_on()
            cycle = self._learner.ingest(reading)
            is_on_after = self._learner_is_on()

            transition = "none"
            if not was_on_before and is_on_after:
                transition = "started"
            elif was_on_before and not is_on_after:
                transition = "ended"

            return (
                StageResult(
                    stage="events",
                    ok=True,
                    data={
                        "transition": transition,
                        "detector_is_on": is_on_after,
                        "cycle_emitted": cycle is not None,
                        "buffer_depth": len(getattr(self._learner, "_current_samples", [])),
                    },
                ),
                cycle,
            )
        except Exception as exc:
            logger.warning("events stage error: %s", exc)
            return (StageResult(stage="events", ok=False, error=str(exc)), None)

    def _stage_cycles(self, cycle) -> StageResult:
        """Report cycle metadata if a cycle was completed."""
        if cycle is None:
            return StageResult(stage="cycles", ok=True, data={"cycle_completed": False})
        try:
            return StageResult(
                stage="cycles",
                ok=True,
                data={
                    "cycle_completed": True,
                    "start_ts": cycle.start_ts.isoformat(),
                    "end_ts": cycle.end_ts.isoformat(),
                    "duration_s": float(cycle.duration_s),
                    "avg_power_w": float(cycle.avg_power_w),
                    "peak_power_w": float(cycle.peak_power_w),
                    "energy_wh": float(cycle.energy_wh),
                    "phase_mode": str(cycle.phase_mode),
                    "sample_count": int(cycle.sample_count),
                    "has_multiple_modes": bool(cycle.has_multiple_modes),
                    "operating_modes_count": len(cycle.operating_modes or []),
                },
            )
        except Exception as exc:
            logger.warning("cycles stage error: %s", exc)
            return StageResult(stage="cycles", ok=False, error=str(exc), data={"cycle_completed": True})

    def _stage_features(self, cycle) -> StageResult:
        """Extract / report CycleFeatures from a completed cycle."""
        if cycle is None:
            return StageResult(stage="features", ok=True, data={})
        try:
            f = cycle.features
            if f is None:
                return StageResult(stage="features", ok=True, data={"features_available": False})
            return StageResult(
                stage="features",
                ok=True,
                data={
                    "features_available": True,
                    "power_variance": float(f.power_variance),
                    "rise_rate_w_per_s": float(f.rise_rate_w_per_s),
                    "fall_rate_w_per_s": float(f.fall_rate_w_per_s),
                    "duty_cycle": float(f.duty_cycle),
                    "peak_to_avg_ratio": float(f.peak_to_avg_ratio),
                    "num_substates": int(f.num_substates),
                    "step_count": int(f.step_count),
                    "has_heating_pattern": bool(f.has_heating_pattern),
                    "has_motor_pattern": bool(f.has_motor_pattern),
                },
            )
        except Exception as exc:
            logger.warning("features stage error: %s", exc)
            return StageResult(stage="features", ok=False, error=str(exc))

    def _stage_classification(self, cycle, features_stage: StageResult) -> StageResult:
        """Run heuristic + storage-based classification on a completed cycle."""
        if cycle is None:
            return StageResult(stage="classification", ok=True, data={})
        try:
            heuristic_label = "unknown"
            if self._heuristic_suggest_fn:
                try:
                    heuristic_label = str(self._heuristic_suggest_fn(cycle) or "unknown")
                except Exception as h_exc:
                    logger.debug("heuristic classify error: %s", h_exc)

            cycle_features = cycle.features
            cycle_payload = {
                "start_ts": cycle.start_ts.isoformat(),
                "end_ts": cycle.end_ts.isoformat(),
                "duration_s": cycle.duration_s,
                "avg_power_w": cycle.avg_power_w,
                "peak_power_w": cycle.peak_power_w,
                "energy_wh": cycle.energy_wh,
                "operating_modes": cycle.operating_modes,
                "has_multiple_modes": cycle.has_multiple_modes,
                "phase_mode": cycle.phase_mode,
                "phase": str(getattr(cycle, "phase", "L1") or "L1"),
                "power_variance": float(cycle_features.power_variance) if cycle_features else 0.0,
                "rise_rate_w_per_s": float(cycle_features.rise_rate_w_per_s) if cycle_features else 0.0,
                "fall_rate_w_per_s": float(cycle_features.fall_rate_w_per_s) if cycle_features else 0.0,
                "duty_cycle": float(cycle_features.duty_cycle) if cycle_features else 0.0,
                "peak_to_avg_ratio": float(cycle_features.peak_to_avg_ratio) if cycle_features else 1.0,
                "num_substates": int(cycle_features.num_substates) if cycle_features else 0,
                "step_count": int(cycle_features.step_count) if cycle_features else 0,
                "has_heating_pattern": bool(cycle_features.has_heating_pattern) if cycle_features else False,
                "has_motor_pattern": bool(cycle_features.has_motor_pattern) if cycle_features else False,
                "profile_points": list(cycle.profile_points or []),
                "active_phase_count": 1,
            }

            overlap_events = process_signal(cycle_payload.get("profile_points") or [])
            overlap_score = estimate_overlap_score(cycle_payload.get("profile_points") or [])
            cycle_payload["overlap_score"] = float(overlap_score)
            cycle_payload["overlap_events_count"] = int(len(overlap_events))

            if self._storage:
                model_result = self._storage.suggest_cycle_label(cycle_payload, fallback=heuristic_label)
                label = str(model_result.get("label") or heuristic_label)
                confidence = float(model_result.get("confidence", 0.0))
                explain = dict(model_result.get("explain") or {})
                decision_path = list(model_result.get("decision_path") or [])
            else:
                label = heuristic_label
                confidence = 0.3
                explain = {"source": "heuristic_only"}
                decision_path = ["heuristic"]

            # Downgrade to "unknown" when confidence is too low
            if confidence < 0.6 and label not in ("unknown", "unbekannt"):
                decision_path.append(f"downgraded_from={label!r} (confidence={confidence:.2f}<0.6)")
                label = "unknown"

            return StageResult(
                stage="classification",
                ok=True,
                data={
                    "label": label,
                    "confidence": confidence,
                    "heuristic_label": heuristic_label,
                    "explain": explain,
                    "decision_path": decision_path,
                    "overlap_score": overlap_score,
                    "overlap_events_count": len(overlap_events),
                    "cycle_payload": cycle_payload,
                },
            )
        except Exception as exc:
            logger.warning("classification stage error: %s", exc)
            return StageResult(stage="classification", ok=False, error=str(exc),
                               data={"label": "unknown", "confidence": 0.0})

    def _stage_persistence(
        self,
        cycle,
        classification_stage: StageResult,
        phase: str,
    ) -> StageResult:
        """Store cycle + classification result in the database."""
        if cycle is None or not self._storage:
            return StageResult(stage="persistence", ok=True, data={"stored": False})
        try:
            cycle_payload = classification_stage.data.get("cycle_payload", {})
            label = classification_stage.data.get("label", "unknown")

            if cycle_payload:
                self._storage.learn_cycle_pattern(cycle=cycle_payload, suggestion_type=label)
                return StageResult(
                    stage="persistence",
                    ok=True,
                    data={"stored": True, "label": label, "phase": phase},
                )
            return StageResult(stage="persistence", ok=True, data={"stored": False, "reason": "empty_payload"})
        except Exception as exc:
            logger.warning("persistence stage error: %s", exc)
            return StageResult(stage="persistence", ok=False, error=str(exc), data={"stored": False})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _learner_is_on(self) -> bool:
        is_on = getattr(self._learner, "_is_on", None)
        if is_on is not None:
            return bool(is_on)
        aed = getattr(self._learner, "_adaptive_detector", None)
        return bool(getattr(aed, "_is_on", False)) if aed else False

    def _append_debug(self, result: PipelineResult) -> None:
        try:
            self._debug_buffer.append(result.as_dict())
            if len(self._debug_buffer) > self._debug_buffer_size:
                self._debug_buffer.pop(0)
        except Exception:
            pass

    def get_debug_buffer(self) -> List[Dict[str, Any]]:
        """Return recent pipeline results for the debug tab."""
        return list(self._debug_buffer)
