"""Training filter – gates which events/cycles may enter the learned pattern DB.

Only events that pass all quality checks are used for training.
Every rejection records a human-readable reason so the debug tab can show
exactly why an event was discarded.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def is_valid_training_event(event: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return ``(True, None)`` when the event is suitable for training.

    Returns ``(False, reason)`` otherwise.  ``reason`` is a short English
    string suitable for logging / storing in the DB.

    Parameters
    ----------
    event:
        Dict representation of a cycle/event as produced by the pipeline or
        as stored in the events table.  Required keys mirror the cycle_payload
        used in ``NILMPipeline._stage_classification``.
    """
    # --- Power guard --------------------------------------------------------
    delta_power = float(event.get("avg_power_w") or event.get("delta_avg_power_w") or 0.0)
    if delta_power < 30.0:
        return False, "delta_power_too_small"

    # --- Duration guard -----------------------------------------------------
    duration = float(event.get("duration_s") or 0.0)
    if duration < 10.0:
        return False, "duration_too_short"

    # --- Overlap guard -------------------------------------------------------
    overlap_score = float(event.get("overlap_score") or 0.0)
    if overlap_score > 0.3:
        return False, "overlapping_events"

    # --- Quality guard -------------------------------------------------------
    quality_score = float(event.get("quality_score") or event.get("quality_score_avg") or 1.0)
    if quality_score < 0.7:
        return False, "low_quality_score"

    # --- Sample density guard ------------------------------------------------
    sample_count = int(event.get("sample_count") or 0)
    if sample_count > 0 and (duration / max(sample_count, 1)) > 120.0:
        # Average sample spacing > 2 min → data too sparse to learn reliably
        return False, "sparse_samples"

    # --- Already rejected by upstream ----------------------------------------
    rejection_reason = event.get("rejection_reason") or event.get("rejected_reason")
    if rejection_reason:
        return False, str(rejection_reason)

    return True, None


def log_training_decision(
    storage,
    event_id: Optional[int],
    accepted: bool,
    reason: Optional[str],
    label: Optional[str] = None,
) -> None:
    """Persist a training-filter decision to the ``training_log`` table.

    Silently no-ops if ``storage`` is ``None`` or lacks the method.
    """
    if storage is None:
        return
    fn = getattr(storage, "log_training_decision", None)
    if callable(fn):
        try:
            fn(event_id=event_id, accepted=accepted, reason=reason, label=label)
        except Exception:
            pass
