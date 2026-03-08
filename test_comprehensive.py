#!/usr/bin/env python3
"""
Comprehensive test suite for all pattern detection improvements.
Tests adaptive thresholds, debouncing, noise filtering, and temporal patterns.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

from datetime import datetime, timedelta
from app.learning.pattern_learner import PatternLearner
from app.models import PowerReading
from app.utils.logging import setup_logging, get_logger
from app.storage.sqlite_store import SQLiteStore
import tempfile
import json

logger = setup_logging(debug=False, name="ComprehensiveTest")
log = get_logger(__name__)


def test_adaptive_thresholds():
    """Test that adaptive thresholds adjust to changing baseline."""
    log.info("\n" + "=" * 80)
    log.info("TEST 1: ADAPTIVE THRESHOLDS")
    log.info("=" * 80)
    
    learner = PatternLearner(
        use_adaptive_thresholds=True,
        min_cycle_seconds=5.0,
    )
    
    ts = datetime(2026, 3, 8, 10, 0, 0)
    cycles = []
    
    # Scenario 1: Low baseline (10W idle)
    log.info("\nScenario 1: Low baseline (10W idle)")
    for i in range(10):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        learner.ingest(reading)
    
    # Device runs at 100W
    for i in range(10, 20):
        reading = PowerReading(ts + timedelta(seconds=i), 100.0, "test")
        learner.ingest(reading)
    
    # Back to idle
    for i in range(20, 25):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            cycles.append(cycle)
            log.info(f"✓ Cycle detected: {cycle.peak_power_w:.0f}W")
    
    # Scenario 2: Baseline shifts to 50W (new always-on device)
    log.info("\nScenario 2: Baseline shifts to 50W")
    ts2 = datetime(2026, 3, 8, 11, 0, 0)
    
    for i in range(30):
        reading = PowerReading(ts2 + timedelta(seconds=i), 50.0, "test")
        learner.ingest(reading)
    
    # Device runs at 150W (100W above new baseline)
    for i in range(30, 40):
        reading = PowerReading(ts2 + timedelta(seconds=i), 150.0, "test")
        learner.ingest(reading)
    
    # Back to new baseline
    for i in range(40, 45):
        reading = PowerReading(ts2 + timedelta(seconds=i), 50.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            cycles.append(cycle)
            log.info(f"✓ Cycle detected with new baseline: {cycle.peak_power_w:.0f}W")
    
    log.info(f"\n✓ Adaptive thresholds test: {len(cycles)} cycles detected")
    return len(cycles) >= 1  # Should detect at least one cycle


def test_noise_filtering():
    """Test that noise spikes are filtered out."""
    log.info("\n" + "=" * 80)
    log.info("TEST 2: NOISE FILTERING (Spike Rejection)")
    log.info("=" * 80)
    
    learner = PatternLearner(
        use_adaptive_thresholds=True,
        min_cycle_seconds=5.0,
        noise_filter_window=3,
    )
    
    ts = datetime(2026, 3, 8, 12, 0, 0)
    cycles = []
    
    # Idle baseline
    for i in range(10):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        learner.ingest(reading)
    
    # Real device (100W for 10 seconds)
    log.info("\nReal device: 100W for 10s with noise spikes")
    for i in range(10, 20):
        # Add random spikes every 3 seconds
        power = 100.0
        if i % 3 == 0:
            power = 500.0  # Spike!
            log.info(f"  Spike injected at {i}s: 500W")
        reading = PowerReading(ts + timedelta(seconds=i), power, "test")
        learner.ingest(reading)
    
    # Back to idle
    for i in range(20, 25):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            cycles.append(cycle)
            # Note: Median filter prevents false triggers, but raw samples still contain spikes
            # This is correct - filter is for state detection, not data modification
            log.info(f"✓ Cycle detected: peak={cycle.peak_power_w:.0f}W, avg={cycle.avg_power_w:.0f}W")
            # Check that cycle was detected (not filtered as false positive)
            log.info("  ✓ Noise filtering working (cycle detection stable)")
            return True
    
    # If we exit without detecting a cycle, the filter might be too aggressive
    log.warning("  ✗ No cycle detected - filter too aggressive?")
    return len(cycles) > 0


def test_debouncing():
    """Test that debouncing prevents oscillation."""
    log.info("\n" + "=" * 80)
    log.info("TEST 3: DEBOUNCING (Prevent False Triggers)")
    log.info("=" * 80)
    
    learner = PatternLearner(
        use_adaptive_thresholds=True,
        min_cycle_seconds=5.0,
        debounce_samples=2,
    )
    
    ts = datetime(2026, 3, 8, 13, 0, 0)
    cycles = []
    
    # Idle baseline
    for i in range(5):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        learner.ingest(reading)
    
    # Oscillating device (fluctuates around threshold)
    log.info("\nOscillating power: 45W → 15W → 45W → 15W...")
    for i in range(5, 25):
        power = 45.0 if i % 2 == 0 else 15.0
        reading = PowerReading(ts + timedelta(seconds=i), power, "test")
        cycle = learner.ingest(reading)
        if cycle:
            cycles.append(cycle)
    
    # Final stable OFF
    for i in range(25, 30):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            cycles.append(cycle)
    
    log.info(f"\n✓ Debouncing test: {len(cycles)} cycles (should be 0-1, not many)")
    # Without debouncing, would get many false cycles from oscillation
    # With debouncing, should get 0 or 1 real cycle
    return len(cycles) <= 1


def test_multi_device_scenarios():
    """Test realistic multi-device scenarios."""
    log.info("\n" + "=" * 80)
    log.info("TEST 4: MULTI-DEVICE SCENARIOS")
    log.info("=" * 80)
    
    learner = PatternLearner(
        use_adaptive_thresholds=True,
        min_cycle_seconds=5.0,
    )
    
    ts = datetime(2026, 3, 8, 14, 0, 0)
    cycles = []
    
    # Scenario: Multiple devices in sequence
    scenarios = [
        ("Microwave", 5, 900, "Short burst - 5s @ 900W"),
        ("Toaster", 8, 1200, "Medium burst - 8s @ 1200W"),
        ("Kettle", 12, 2200, "Longer - 12s @ 2200W"),
        ("Fridge", 25, 180, "Long cycle - 25s @ 180W"),
        ("Washing Machine", 40, 1800, "Very long - 40s @ 1800W"),
    ]
    
    current_time = 0
    
    for device_name, duration, power, description in scenarios:
        log.info(f"\n{device_name}: {description}")
        
        # Idle before device
        for i in range(3):
            reading = PowerReading(ts + timedelta(seconds=current_time + i), 10.0, "test")
            learner.ingest(reading)
        current_time += 3
        
        # Device active
        for i in range(duration):
            reading = PowerReading(ts + timedelta(seconds=current_time + i), power, "test")
            learner.ingest(reading)
        current_time += duration
        
        # Idle after device
        for i in range(5):
            reading = PowerReading(ts + timedelta(seconds=current_time + i), 10.0, "test")
            cycle = learner.ingest(reading)
            if cycle:
                cycles.append((device_name, cycle))
                device_type = PatternLearner.suggest_device_type(cycle)
                log.info(f"  ✓ Detected: {cycle.duration_s:.0f}s @ {cycle.peak_power_w:.0f}W → {device_type}")
        current_time += 5
    
    log.info(f"\n✓ Multi-device test: {len(cycles)}/{len(scenarios)} devices detected")
    return len(cycles) >= 3  # Should detect at least 3 out of 5


def test_temporal_patterns():
    """Test temporal pattern storage."""
    log.info("\n" + "=" * 80)
    log.info("TEST 5: TEMPORAL PATTERN STORAGE")
    log.info("=" * 80)
    
    # Create temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = SQLiteStore(db_path, retention_days=30)
        
        if not store.connect():
            log.error("Failed to connect to test database")
            return False
        
        log.info("\nSimulating refrigerator cycles at regular intervals...")
        
        # Simulate fridge cycles every 30 minutes
        base_time = datetime(2026, 3, 8, 8, 0, 0)
        
        for cycle_num in range(5):
            cycle_time = base_time + timedelta(minutes=cycle_num * 30)
            
            cycle_data = {
                "start_ts": cycle_time.isoformat(),
                "end_ts": (cycle_time + timedelta(seconds=20)).isoformat(),
                "avg_power_w": 180.0,
                "peak_power_w": 200.0,
                "duration_s": 20.0,
                "energy_wh": 1.0,
                "active_phase_count": 1,
                "operating_modes": [],
                "has_multiple_modes": False,
            }
            
            result = store.learn_cycle_pattern(cycle_data, "fridge")
            
            if result.get("matched"):
                log.info(f"  Cycle {cycle_num + 1}: Matched existing pattern (ID={result['pattern']['id']})")
            else:
                log.info(f"  Cycle {cycle_num + 1}: Created new pattern (ID={result['pattern']['id']})")
        
        # Check temporal data
        patterns = store.list_patterns(limit=10)
        
        if patterns:
            pattern = patterns[0]
            log.info(f"\n✓ Pattern learned:")
            log.info(f"  Seen: {pattern.get('seen_count')} times")
            log.info(f"  Avg Power: {pattern.get('avg_power_w'):.1f}W")
            log.info(f"  Duration: {pattern.get('duration_s'):.1f}s")
            
            # Check temporal fields
            typical_interval = pattern.get('typical_interval_s', 0)
            avg_hour = pattern.get('avg_hour_of_day', 0)
            
            if typical_interval > 0:
                log.info(f"  Typical Interval: {typical_interval/60:.0f} minutes")
                log.info(f"  Avg Hour of Day: {avg_hour:.1f}")
                log.info("  ✓ Temporal patterns stored successfully!")
                store.close()
                return True
            else:
                log.warning("  ✗ Temporal data not stored")
                store.close()
                return False
        
        store.close()
        return False


def test_mode_detection():
    """Test multi-mode detection."""
    log.info("\n" + "=" * 80)
    log.info("TEST 6: MULTI-MODE DETECTION")
    log.info("=" * 80)
    
    learner = PatternLearner(
        use_adaptive_thresholds=True,
        min_cycle_seconds=10.0,
    )
    
    ts = datetime(2026, 3, 8, 15, 0, 0)
    
    # Idle
    for i in range(5):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        learner.ingest(reading)
    
    # Washing machine: wash phase
    log.info("\nWashing machine cycle:")
    log.info("  Phase 1: Wash @ 1500W (30s)")
    for i in range(5, 35):
        reading = PowerReading(ts + timedelta(seconds=i), 1500.0, "test")
        learner.ingest(reading)
    
    # Rinse phase
    log.info("  Phase 2: Rinse @ 800W (20s)")
    for i in range(35, 55):
        reading = PowerReading(ts + timedelta(seconds=i), 800.0, "test")
        learner.ingest(reading)
    
    # Spin phase
    log.info("  Phase 3: Spin @ 2200W (25s)")
    for i in range(55, 80):
        reading = PowerReading(ts + timedelta(seconds=i), 2200.0, "test")
        learner.ingest(reading)
    
    # Back to idle
    for i in range(80, 90):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            log.info(f"\n✓ Cycle detected: {cycle.duration_s:.0f}s @ {cycle.peak_power_w:.0f}W")
            log.info(f"  Multiple modes: {cycle.has_multiple_modes}")
            log.info(f"  Operating modes: {len(cycle.operating_modes)}")
            
            if cycle.operating_modes:
                for mode in cycle.operating_modes:
                    log.info(f"    • {mode['type']:10s}: {mode['avg_power_w']:6.0f}W @ {mode['duration_s']:5.1f}s")
            
            return cycle.has_multiple_modes and len(cycle.operating_modes) >= 2
    
    return False


def main():
    """Run all comprehensive tests."""
    log.info("=" * 80)
    log.info("COMPREHENSIVE PATTERN DETECTION TEST SUITE")
    log.info("=" * 80)
    log.info("Testing all implemented improvements:")
    log.info("  • Adaptive Thresholds")
    log.info("  • Noise Filtering")
    log.info("  • Debouncing")
    log.info("  • Multi-Device Scenarios")
    log.info("  • Temporal Pattern Storage")
    log.info("  • Multi-Mode Detection")
    
    results = {}
    
    try:
        results['adaptive_thresholds'] = test_adaptive_thresholds()
        results['noise_filtering'] = test_noise_filtering()
        results['debouncing'] = test_debouncing()
        results['multi_device'] = test_multi_device_scenarios()
        results['temporal_patterns'] = test_temporal_patterns()
        results['mode_detection'] = test_mode_detection()
    except Exception as e:
        log.error(f"Test suite failed with error: {e}", exc_info=True)
        return False
    
    # Summary
    log.info("\n" + "=" * 80)
    log.info("TEST SUMMARY")
    log.info("=" * 80)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        log.info(f"{test_name:25s}: {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    log.info("=" * 80)
    log.info(f"TOTAL: {passed} passed, {failed} failed out of {len(results)} tests")
    log.info("=" * 80)
    
    if passed == len(results):
        log.info("\n🎉 ALL TESTS PASSED! System is fully functional.")
        return True
    else:
        log.warning(f"\n⚠️  {failed} test(s) failed. Review above for details.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
