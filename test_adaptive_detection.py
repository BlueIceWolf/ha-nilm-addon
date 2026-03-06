#!/usr/bin/env python3
"""
Test: Adaptive Fridge Detector with Variable Spikes
Compares old rigid detector with new adaptive detector
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

import time
from datetime import datetime
from app.utils.logging import setup_logging
from app.detectors.fridge import FridgeDetector  # Original
from app.detectors.fridge_adaptive import AdaptiveFridgeDetector  # New
from app.models import PowerReading, DeviceConfig

# Setup
setup_logging(debug=False, name="NILM-Test")

print("\n" + "=" * 80)
print("TEST: VARIABLE FRIDGE SPIKES - Rigid vs Adaptive Detection")
print("=" * 80)

# Configuration
config = DeviceConfig(
    name="kitchen_fridge",
    power_min_w=15.0,
    power_max_w=500.0,
    min_runtime_seconds=5,
    min_pause_seconds=3,
    startup_duration_seconds=2
)

# Create both detectors
rigid_detector = FridgeDetector(config)
adaptive_detector = AdaptiveFridgeDetector(config, learning_samples=10)

print(f"\nConfiguration: {config.name}")
print(f"  Fixed power_min_w: {config.power_min_w}W")
print(f"  Min Runtime: {config.min_runtime_seconds}s")

# Test scenarios with variable spikes
scenarios = [
    ("IDLE BASELINE (learn phase)", [
        (8.0, 1), (9.0, 1), (8.5, 1), (9.5, 1),
        (8.0, 1), (9.0, 1), (8.5, 1), (9.5, 1),  # 8 readings for learning
    ]),
    ("CYCLE 1 - LARGE SPIKE (400W)", [
        (400.0, 1, "✦ Large startup spike"),
        (350.0, 1, "  Stabilizing 1"),
        (280.0, 1, "  Stabilizing 2"),
        (270.0, 2, "  Running normally"),
        (10.0, 1, "  Shutdown"),
    ]),
    ("REST PERIOD", [
        (8.0, 2),
    ]),
    ("CYCLE 2 - SMALL SPIKE (180W)", [
        (180.0, 1, "✦ Small startup spike"),
        (140.0, 1, "  Stabilizing"),
        (130.0, 2, "  Running shorter"),
        (10.0, 1, "  Shutdown"),
    ]),
    ("REST PERIOD", [
        (8.0, 2),
    ]),
    ("CYCLE 3 - MEDIUM SPIKE (280W)", [
        (280.0, 1, "✦ Medium startup spike"),
        (210.0, 1, "  Stabilizing"),
        (200.0, 2, "  Running"),
        (10.0, 1, "  Shutdown"),
    ]),
]

print("\nRunning detection on variable power patterns:\n")

step_count = 0
for phase_name, phase_data in scenarios:
    print(f"→ {phase_name}")
    
    for entry in phase_data:
        if len(entry) == 3:
            power_w, duration, desc = entry
        else:
            power_w, duration = entry
            desc = f"{power_w:.0f}W"
        
        for _ in range(duration):
            reading = PowerReading(datetime.now(), power_w, "L1")
            
            # Both detectors
            rigid_state = rigid_detector.detect(reading)
            adaptive_state = adaptive_detector.detect(reading)
            
            step_count += 1
            
            # Format output
            r_state = f"{rigid_state.value[:3]}" if rigid_state else "---"
            a_state = f"{adaptive_state.value[:3]}" if adaptive_state else "---"
            
            # Show diagnostic for adaptive
            diag = adaptive_detector.get_diagnostics()
            threshold = diag['startup_threshold_w']
            
            match = "✓" if r_state == a_state else "✗"
            print(
                f"  {step_count:2d}. {power_w:6.1f}W │ "
                f"Rigid: {r_state} │ "
                f"Adaptive: {a_state} {match} │ "
                f"Threshold: {threshold:6.1f}W │ "
                f"{desc}"
            )
            
            time.sleep(0.3)

# Summary
print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)

print("\n📊 Adaptive Detector Statistics:")
diag = adaptive_detector.get_diagnostics()
print(f"  Baseline Power: {diag['baseline_power_w']:.1f}W ± {diag['baseline_variance_w']:.1f}W")
print(f"  Startup Threshold: {diag['startup_threshold_w']:.1f}W")
print(f"  Learning Mode: {diag['learning_mode']}")
print(f"  Recent Avg Power: {diag['recent_avg_power_w']:.1f}W")

print("\n🎯 Key Differences:")
print("  ✓ Rigid Detector:")
print(f"    - Uses fixed thresholds (power_min_w={config.power_min_w}W)")
print(f"    - May miss small spikes or false trigger on noise")
print(f"    - Same behavior for all devices\n")

print("  ✓ Adaptive Detector:")
print(f"    - Learns baseline from idle periods (~{adaptive_detector.baseline_power:.1f}W)")
print(f"    - Detects spikes relative to baseline")
print(f"    - Detects power trends (rising/stable/falling)")
print(f"    - Adapts to each device's characteristics")

print("\n💡 When to use each:")
print("  • Rigid: Simple setups, consistent power patterns")
print("  • Adaptive: Variable devices, different unit ages, noisy signals")

print("\n✓ Test Complete!")
print("=" * 80 + "\n")
