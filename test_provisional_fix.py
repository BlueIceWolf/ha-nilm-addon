#!/usr/bin/env python3
"""
Test the provisional pattern storage fix.
Verify that provisional patterns are stored in learned_patterns table,
not just in provisional_patterns.
"""

import sys
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

from app.storage.sqlite_store import SQLiteStore
from app.models import PowerReading
from app.utils.logging import setup_logging, get_logger

logger = setup_logging(debug=True, name="ProvisionalFixTest")
log = get_logger(__name__)


def test_provisional_pattern_in_learned_patterns():
    """Test that provisional patterns are stored in learned_patterns."""
    
    log.info("=" * 80)
    log.info("TEST: Provisional Patterns in learned_patterns")
    log.info("=" * 80)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.sqlite3")
        patterns_db = os.path.join(tmpdir, "patterns.sqlite3")
        
        store = SQLiteStore(db_path=db_path, patterns_db_path=patterns_db)
        
        try:
            if not store.connect():
                log.error("Failed to connect to storage")
                return False
            
            # Configure learning policy
            store.configure_learning_policy(
                min_event_duration_s=5.0,
                min_samples_for_learning=4,
                min_waveform_score_for_provisional=0.15,
                min_waveform_score_for_final=0.45,
                merge_similarity_threshold=0.86,
            )
            
            # Create a test cycle with medium quality (should be provisional)
            base_time = datetime(2026, 4, 10, 12, 0, 0)
            cycle_data = {
                "start_ts": base_time.isoformat(),
                "end_ts": (base_time + timedelta(seconds=30)).isoformat(),
                "avg_power_w": 200.0,
                "peak_power_w": 280.0,
                "energy_wh": 1.7,
                "duration_s": 30.0,
                "sample_count": 30,
                "active_phase_count": 1,
                "phase": "L1",
                "phase_mode": "single_phase",
                "power_variance": 1200.0,
                "rise_rate_w_per_s": 50.0,
                "fall_rate_w_per_s": 45.0,
                "duty_cycle": 0.8,
                "peak_to_avg_ratio": 1.4,
                "num_substates": 1,
                "step_count": 1,
                "has_heating_pattern": False,
                "has_motor_pattern": False,
                "segmentation_confidence": 0.35,  # Medium confidence - should be provisional
                "waveform_completeness_score": 0.40,
                "quality_score": 0.35,
                "truncated_start": False,
                "truncated_end": False,
                "profile_points": [{"t_s": float(i), "power_w": 200.0 + (i % 5) * 10} for i in range(30)],
                "pre_roll_samples": [],
                "post_roll_samples": [],
                "operating_modes": [],
                "has_multiple_modes": False,
            }
            
            log.info("\n[1] About to learn cycle with medium quality...")
            log.info(f"    Segmentation confidence: {cycle_data['segmentation_confidence']}")
            log.info(f"    Waveform score: {cycle_data['waveform_completeness_score']}")
            
            result = store.learn_cycle_pattern(cycle=cycle_data, suggestion_type="fridge")
            
            log.info(f"\n[2] Learn result:")
            log.info(f"    Matched: {result.get('matched')}")
            log.info(f"    Pattern ID: {result.get('pattern', {}).get('id')}")
            log.info(f"    Learning tier: {result.get('learning_tier')}")
            log.info(f"    Pattern: {bool(result.get('pattern'))}")
            
            # Check learned_patterns table
            log.info(f"\n[3] Checking learned_patterns table...")
            patterns = store.list_patterns(limit=100)
            log.info(f"    Total patterns in learned_patterns: {len(patterns)}")
            
            if patterns:
                for pattern in patterns:
                    log.info(f"    Pattern ID {pattern.get('id')}: status={pattern.get('status')}, "
                            f"label={pattern.get('suggestion_type')}, "
                            f"seg_conf={pattern.get('segmentation_confidence', 'N/A')}")
            else:
                log.warning("    NO PATTERNS FOUND IN learned_patterns!")
            
            # Check provisional_patterns table
            log.info(f"\n[4] Checking provisional_patterns table...")
            prov_patterns = store._list_provisional_patterns(limit=100)
            log.info(f"    Total patterns in provisional_patterns: {len(prov_patterns)}")
            
            if prov_patterns:
                for pattern in prov_patterns:
                    log.info(f"    Provisional Pattern ID {pattern.get('id')}: "
                            f"status={pattern.get('status')}, "
                            f"label={pattern.get('refined_label')}")
            else:
                log.info("    No patterns in provisional_patterns (this is OK now)")
            
            # CRITICAL TEST
            log.info(f"\n[5] CRITICAL CHECK:")
            expected_in_learned = len(patterns) > 0
            list_shows_provisional = any(p.get('status') == 'provisional' for p in patterns) if patterns else False
            
            if expected_in_learned:
                log.info(f"    [PASS] Provisional pattern IS in learned_patterns!")
                if list_shows_provisional:
                    log.info(f"    [PASS] Pattern has status='provisional'")
                else:
                    log.warning(f"    [WARN] Pattern in learned_patterns but status not provisional: {[p.get('status') for p in patterns]}")
            else:
                log.error(f"    [FAIL] Provisional pattern NOT in learned_patterns!")
                log.error(f"    Patterns returned: {patterns}")
            
            # Check learning statistics
            log.info(f"\n[6] LEARNING STATISTICS:")
            stats = store._learning_stats
            log.info(f"    Events seen: {int(stats.get('events_seen_total', 0))}")
            log.info(f"    Provisional patterns created: {int(stats.get('provisional_patterns_created', 0))}")
            log.info(f"    Final patterns created: {int(stats.get('final_patterns_created', 0))}")
            log.info(f"    Patterns merged: {int(stats.get('patterns_merged', 0))}")
            log.info(f"    Patterns promoted: {int(stats.get('patterns_promoted', 0))}")
            log.info(f"    Rejections - Quality: {int(stats.get('rejected_quality', 0))}, "
                    f"Baseline: {int(stats.get('rejected_baseline', 0))}, "
                    f"Session: {int(stats.get('rejected_session_dup', 0))}, "
                    f"Segmentation: {int(stats.get('rejected_segmentation', 0))}")
            
            log.info("\n" + "=" * 80)
            log.info(f"RESULT: {'PASS' if expected_in_learned else 'FAIL'}")
            log.info("=" * 80)
            
            return expected_in_learned
            
        finally:
            # Close database connections
            if store._conn:
                store._conn.close()
            if store._patterns_conn:
                store._patterns_conn.close()


if __name__ == "__main__":
    success = test_provisional_pattern_in_learned_patterns()
    sys.exit(0 if success else 1)
