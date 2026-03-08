#!/usr/bin/env python3
"""
Test PatternLearner - the core pattern recognition system.
This tests how well the system detects and learns appliance cycles.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

from datetime import datetime, timedelta
from app.learning.pattern_learner import PatternLearner
from app.models import PowerReading
from app.utils.logging import setup_logging, get_logger

logger = setup_logging(debug=True, name="PatternTest")
log = get_logger(__name__)

def test_pattern_detection():
    """Test core pattern learning capabilities."""
    
    log.info("=" * 70)
    log.info("PATTERN LEARNER TEST - Core Cycle Detection")
    log.info("=" * 70)
    
    learner = PatternLearner(
        on_threshold_w=40.0,
        off_threshold_w=20.0,
        min_cycle_seconds=5.0,    # Reduced to catch short cycles (microwave, toaster)
        max_cycle_seconds=3600.0,  # 1 hour max
        use_adaptive_thresholds=True,  # Test adaptive thresholds
    )
    
    detected_cycles = []
    
    # Microwave simulation: 5-second burst at 1000W
    log.info("\n[TEST 1] MICROWAVE (1000W, 5 seconds)")
    log.info("-" * 70)
    ts = datetime(2026, 3, 8, 10, 0, 0)
    
    # Idle phase (10W for 3 seconds)
    for i in range(3):
        reading = PowerReading(ts + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.info(f"✓ CYCLE DETECTED (unexpected in idle)")
    
    # Active phase (1000W for 5 seconds)
    for i in range(3, 8):
        reading = PowerReading(ts + timedelta(seconds=i), 1000.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.warning(f"✓ CYCLE DETECTED (unexpected during active)")
    
    # Shutdown phase (5W for 5 seconds - extended for debouncing)  
    for i in range(8, 13):
        reading = PowerReading(ts + timedelta(seconds=i), 5.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.info(f"✓ MICROWAVE CYCLE DETECTED")
            log.info(f"  Duration: {cycle.duration_s:.1f}s")
            log.info(f"  Peak Power: {cycle.peak_power_w:.0f}W")
            log.info(f"  Avg Power: {cycle.avg_power_w:.0f}W")
            log.info(f"  Energy: {cycle.energy_wh:.2f}Wh")
            log.info(f"  Samples: {cycle.sample_count}")
            if cycle.has_multiple_modes:
                log.info(f"  Modes: {len(cycle.operating_modes)}")
                for m in cycle.operating_modes:
                    log.info(f"    - {m['type']}: {m['avg_power_w']:.0f}W for {m['duration_s']:.1f}s")
    
    # Test 2: Fridge simulation - longer cycle with cycling pattern
    log.info("\n[TEST 2] REFRIGERATOR (200W cycling, 60 seconds)")
    log.info("-" * 70)
    ts2 = datetime(2026, 3, 8, 11, 0, 0)
    
    # Idle baseline
    for i in range(5):
        reading = PowerReading(ts2 + timedelta(seconds=i), 10.0, "test")
        learner.ingest(reading)
    
    # Fridge ON (200W for 20s)
    for i in range(5, 25):
        power = 200.0 + (10.0 if i % 2 == 0 else 0.0)  # Minor cycling
        reading = PowerReading(ts2 + timedelta(seconds=i), power, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.warning(f"Early cycle detected at {i}s: {cycle.duration_s:.1f}s")
    
    # Fridge OFF (10W for 40s)
    for i in range(25, 65):
        reading = PowerReading(ts2 + timedelta(seconds=i), 10.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.info(f"✓ CYCLE DETECTED")
            log.info(f"  Duration: {cycle.duration_s:.1f}s")
            log.info(f"  Peak Power: {cycle.peak_power_w:.0f}W")
            log.info(f"  Avg Power: {cycle.avg_power_w:.0f}W")
            log.info(f"  Energy: {cycle.energy_wh:.2f}Wh")
    
    # Test 3: Washing machine - multi-mode cycle
    log.info("\n[TEST 3] WASHING MACHINE (multi-phase, 120 seconds)")
    log.info("-" * 70)
    ts3 = datetime(2026, 3, 8, 12, 0, 0)
    
    # Idle
    for i in range(5):
        reading = PowerReading(ts3 + timedelta(seconds=i), 15.0, "test")
        learner.ingest(reading)
    
    # Wash phase: pump at 1800W
    for i in range(5, 50):
        reading = PowerReading(ts3 + timedelta(seconds=i), 1800.0, "test")
        learner.ingest(reading)
    
    # Spin phase: motor at 2400W 
    for i in range(50, 80):
        reading = PowerReading(ts3 + timedelta(seconds=i), 2400.0, "test")
        learner.ingest(reading)
    
    # Idle again
    for i in range(80, 125):
        reading = PowerReading(ts3 + timedelta(seconds=i), 15.0, "test")
        cycle = learner.ingest(reading)
        if cycle:
            detected_cycles.append(cycle)
            log.info(f"✓ CYCLE DETECTED")
            log.info(f"  Duration: {cycle.duration_s:.1f}s (expected ~70-75s)")
            log.info(f"  Peak Power: {cycle.peak_power_w:.0f}W (expected ~2400W)")
            log.info(f"  Avg Power: {cycle.avg_power_w:.0f}W")
            log.info(f"  Energy: {cycle.energy_wh:.2f}Wh")
            log.info(f"  Has Multiple Modes: {cycle.has_multiple_modes}")
            if cycle.operating_modes:
                log.info(f"  Operating Modes: {len(cycle.operating_modes)}")
                for mode in cycle.operating_modes:
                    log.info(f"    • {mode['type']:10s}: {mode['avg_power_w']:6.0f}W @ {mode['duration_s']:6.1f}s")
    
    # Summary
    log.info("\n" + "=" * 70)
    log.info(f"SUMMARY: Detected {len(detected_cycles)} cycles")
    log.info("=" * 70)
    
    for idx, cycle in enumerate(detected_cycles, 1):
        log.info(f"\n[Cycle {idx}]")
        log.info(f"  Duration: {cycle.duration_s:.1f}s")
        log.info(f"  Energy: {cycle.energy_wh:.2f}Wh")
        log.info(f"  Peak: {cycle.peak_power_w:.0f}W")
        
        # Try to classify
        device_type = PatternLearner.suggest_device_type(cycle)
        log.info(f"  Type: {device_type}")

if __name__ == "__main__":
    test_pattern_detection()
