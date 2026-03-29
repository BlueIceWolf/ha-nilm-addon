"""Deterministic stage helpers for pattern-learning pipeline.

This module keeps the learning flow explicit and testable:
1) prepare cycle
2) find candidate
3) decide merge/create
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class PreparedCycle:
    cycle: Dict[str, Any]
    suggestion_seed: str
    quality_score: float
    skipped_reason: Optional[str] = None


@dataclass
class MatchResult:
    best: Optional[Dict[str, Any]]
    best_similarity: float
    best_distance: float


@dataclass
class DedupDecision:
    result: str
    reason: str
    force_match: bool


def prepare_cycle_for_learning(
    cycle: Dict[str, Any],
    suggestion_type: str,
    *,
    quality_min_accept: float,
    quality_fn: Callable[[Dict[str, Any]], float],
    augment_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    infer_unknown_fn: Callable[[Dict[str, Any]], str],
    shape_signature_fn: Callable[[Dict[str, Any]], str],
    curve_hash_fn: Callable[[Dict[str, Any]], str],
    mode_key_fn: Callable[[Dict[str, Any]], str],
    group_id_fn: Callable[[str, Dict[str, Any]], str],
) -> PreparedCycle:
    quality_score = float(quality_fn(cycle))
    if quality_score < float(quality_min_accept):
        return PreparedCycle(
            cycle=dict(cycle),
            suggestion_seed=str(suggestion_type or "unknown").strip() or "unknown",
            quality_score=quality_score,
            skipped_reason="low_quality_cycle",
        )

    enriched = augment_fn(cycle)
    suggestion_seed = str(suggestion_type or "unknown").strip() or "unknown"
    if suggestion_seed == "unknown":
        suggestion_seed = str(infer_unknown_fn(enriched) or "unknown").strip() or "unknown"

    enriched["shape_signature"] = shape_signature_fn(enriched)
    enriched["curve_hash"] = curve_hash_fn(enriched)
    enriched["mode_key"] = mode_key_fn(enriched)
    enriched["device_group_id"] = group_id_fn(suggestion_seed, enriched)

    if bool(enriched.get("baseline_unstable", False)):
        return PreparedCycle(
            cycle=enriched,
            suggestion_seed=suggestion_seed,
            quality_score=quality_score,
            skipped_reason="baseline_unstable",
        )

    return PreparedCycle(
        cycle=enriched,
        suggestion_seed=suggestion_seed,
        quality_score=quality_score,
        skipped_reason=None,
    )


def find_best_pattern_match(
    patterns: List[Dict[str, Any]],
    cycle: Dict[str, Any],
    *,
    phase: str,
    similarity_fn: Callable[[Dict[str, Any], Dict[str, Any]], float],
) -> MatchResult:
    best = None
    best_distance = 999.0
    best_similarity = 0.0

    for item in patterns:
        if item.get("status") != "active":
            continue
        if str(item.get("phase", "L1")) != str(phase or "L1"):
            continue

        similarity = float(similarity_fn(item, cycle))
        distance = 1.0 - similarity
        if distance < best_distance:
            best_distance = distance
            best_similarity = similarity
            best = item

    return MatchResult(best=best, best_similarity=best_similarity, best_distance=best_distance)


def decide_dedup_action(
    best: Optional[Dict[str, Any]],
    cycle: Dict[str, Any],
    suggestion_seed: str,
    best_similarity: float,
    *,
    dedup_update_similarity: float,
    dedup_merge_similarity: float,
    mode_key_fn: Callable[[Dict[str, Any]], str],
    group_id_fn: Callable[[str, Dict[str, Any]], str],
) -> DedupDecision:
    if not best:
        return DedupDecision(result="new", reason="no_match", force_match=False)

    best_group = str(best.get("device_group_id") or group_id_fn(str(best.get("suggestion_type") or suggestion_seed), best))
    cycle_group = str(cycle.get("device_group_id") or "")
    same_group = best_group == cycle_group

    best_mode = str(best.get("mode_key") or mode_key_fn(best))
    cycle_mode = str(cycle.get("mode_key") or "")
    same_mode = best_mode == cycle_mode

    if best_similarity >= float(dedup_update_similarity) and same_group:
        return DedupDecision(
            result="update_existing",
            reason=f"similarity_ge_{str(dedup_update_similarity).replace('.', '_')}_same_group",
            force_match=True,
        )

    if best_similarity >= float(dedup_merge_similarity) and same_group and same_mode:
        return DedupDecision(
            result="merge_mode",
            reason=f"similarity_ge_{str(dedup_merge_similarity).replace('.', '_')}_same_group_mode",
            force_match=True,
        )

    return DedupDecision(
        result="create_new",
        reason="similarity_or_scope_below_threshold",
        force_match=False,
    )
