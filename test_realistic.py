#!/usr/bin/env python3
"""
Realistic test with time delays simulating real power measurements.
"""

import time
from datetime import datetime
from app.utils.logging import setup_logging
from app.state_engine import StateEngine
from app.detectors.fridge import FridgeDetector
from app.models import PowerReading, DeviceConfig

# Setup
logger = setup_logging(debug=False, name="NILM-Test")

print("\n" + "=" * 70)
print("HA NILM DETECTOR - REFRIGERATOR TEST")
print("=" * 70)

# Configuration
config = DeviceConfig(
    name="kitchen_fridge",
    power_min_w=15.0,
    power_max_w=500.0,
    min_runtime_seconds=5,
    min_pause_seconds=3,
    startup_duration_seconds=2
)

# Setup components
detector = FridgeDetector(config)
state_engine = StateEngine()
state_engine.register_device("kitchen_fridge", config)

print(f"\nConfiguration:")
print(f"  Device: {config.name}")
print(f"  Power Min: {config.power_min_w}W, Max: {config.power_max_w}W")
print(f"  Startup Duration: {config.startup_duration_seconds}s")
print(f"  Min Runtime: {config.min_runtime_seconds}s")

# Test scenario: Power values with duration in seconds
scenario = [
    ("IDLE PHASE", [
        (10.0, 2, "Idle"),
    ]),
    ("FIRST CYCLE - STARTUP & RUNNING", [
        (250.0, 1, "★ Startup Spike"),
        (210.0, 1, "← Stabilizing"),
        (195.0, 3, "Running..."),
        (10.0, 1, "☆ Shutdown"),
    ]),
    ("OFF PHASE", [
        (10.0, 3, "Off"),
    ]),
    ("SECOND CYCLE", [
        (230.0, 1, "★ Startup 2"),
        (200.0, 1, "← Stabilizing"),
        (185.0, 3, "Running..."),
        (10.0, 1, "☆ Shutdown"),
    ]),
]

start_time = time.time()
total_steps = 0

for phase_name, phase_steps in scenario:
    print(f"\n{phase_name}:")
    print("-" * 70)
    
    for power_w, duration_s, description in phase_steps:
        for second in range(duration_s):
            # Create power reading
            reading = PowerReading(
                timestamp=datetime.now(),
                power_w=power_w,
                phase="L1"
            )
            
            # Detect state
            detected_state = detector.detect(reading)
            
            # Update state engine
            if detected_state:
                device_state = state_engine.update_device_state(
                    "kitchen_fridge",
                    detected_state,
                    power_w,
                    detector.get_cycle_info()
                )
                
                elapsed = int(time.time() - start_time)
                state_short = device_state.state.value[:3].upper()
                
                print(
                    f"  [{elapsed:02d}s] {power_w:6.1f}W  │  "
                    f"Detector: {detected_state.value:8} │ "
                    f"State: {state_short} │ "
                    f"Cycles: {device_state.daily_cycles} │ "
                    f"Runtime: {device_state.daily_runtime_seconds:6.1f}s  │  "
                    f"{description}"
                )
            
            total_steps += 1
            # Real delay
            time.sleep(1.0)

# Final report
print("\n" + "=" * 70)
print("FINAL REPORT")
print("=" * 70)

final_state = state_engine.get_device_state("kitchen_fridge")
print(f"\nDevice: {config.name}")
print(f"  Current State: {final_state.state.value.upper()}")
print(f"  Total Daily Cycles: {final_state.daily_cycles}")
print(f"  Total Daily Runtime: {final_state.daily_runtime_seconds:.1f}s")
print(f"  Last Update: {final_state.last_update}")
print(f"\nTotal Test Duration: {int(time.time() - start_time)}s")
print(f"Total Measurements: {total_steps}")

print("\n✓ Test Complete!")
print("=" * 70 + "\n")
