#!/usr/bin/env python3

from app.learning.pipeline_stages import decide_dedup_action, find_best_pattern_match


def test_find_best_pattern_match_prefers_same_phase_and_high_similarity():
    patterns = [
        {"id": 1, "status": "active", "phase": "L2", "avg": 0},
        {"id": 2, "status": "active", "phase": "L1", "avg": 1},
        {"id": 3, "status": "active", "phase": "L1", "avg": 2},
    ]

    def sim_fn(existing, _candidate):
        return {1: 0.99, 2: 0.70, 3: 0.92}[existing["id"]]

    result = find_best_pattern_match(
        patterns=patterns,
        cycle={"phase": "L1"},
        phase="L1",
        similarity_fn=sim_fn,
    )

    assert result.best is not None
    assert int(result.best["id"]) == 3
    assert result.best_similarity == 0.92


def test_decide_dedup_action_requires_scope_match():
    best = {
        "id": 4,
        "suggestion_type": "fridge",
        "device_group_id": "fridge:L1",
        "mode_key": "single_phase:2:short:mid",
    }
    cycle = {
        "device_group_id": "fridge:L1",
        "mode_key": "single_phase:2:short:mid",
    }

    decision = decide_dedup_action(
        best=best,
        cycle=cycle,
        suggestion_seed="fridge",
        best_similarity=0.95,
        dedup_update_similarity=0.94,
        dedup_merge_similarity=0.88,
        mode_key_fn=lambda c: str(c.get("mode_key", "")),
        group_id_fn=lambda lbl, c: f"{lbl}:{c.get('phase', 'L1')}",
    )
    assert decision.force_match is True
    assert decision.result == "update_existing"

    cycle_other_group = {
        "device_group_id": "washer:L1",
        "mode_key": "single_phase:2:short:mid",
    }
    decision2 = decide_dedup_action(
        best=best,
        cycle=cycle_other_group,
        suggestion_seed="fridge",
        best_similarity=0.98,
        dedup_update_similarity=0.94,
        dedup_merge_similarity=0.88,
        mode_key_fn=lambda c: str(c.get("mode_key", "")),
        group_id_fn=lambda lbl, c: f"{lbl}:{c.get('phase', 'L1')}",
    )
    assert decision2.force_match is False
    assert decision2.result == "create_new"
