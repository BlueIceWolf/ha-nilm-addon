#!/usr/bin/env python3
"""
Test: Inverter vs Non-Inverter Device Detection
Compare detection of traditional on/off vs gradual ramping devices
"""

import time
from datetime import datetime
from app.utils.logging import setup_logging
from app.detectors.fridge import FridgeDetector  # Sharp spikes
from app.detectors.inverter import InverterDeviceDetector  # Gradual ramps
from app.models import PowerReading, DeviceConfig

setup_logging(debug=False, name="NILM-Test")

print("\n" + "=" * 90)
print("TEST: INVERTER vs NON-INVERTER DETECTION")
print("=" * 90)

# Configuration A: Traditional fridge (compressor)
fridge_config = DeviceConfig(
    name="kitchen_fridge",
    power_min_w=15.0,
    power_max_w=500.0,
    min_runtime_seconds=5,
    min_pause_seconds=3,
    startup_duration_seconds=2
)

# Configuration B: Inverter device (heat pump / modern washing machine)
inverter_config = DeviceConfig(
    name="heat_pump",
    power_min_w=10.0,
    power_max_w=3000.0,
    min_runtime_seconds=8,  # Longer runtimes for inverter devices
    min_pause_seconds=5,
    startup_duration_seconds=3
)

# Create detectors
fridge_detector = FridgeDetector(fridge_config)
inverter_detector = InverterDeviceDetector(inverter_config)

print(f"\nDetectors:")
print(f"  1. Fridge Detector (sharp spikes)")
print(f"  2. Inverter Detector (gradual ramps)")

# Scenario 1: Traditional Fridge Operation
print("\n" + "=" * 90)
print("SCENARIO 1: TRADITIONAL FRIDGE (Sharp Spike)")
print("=" * 90)

fridge_scenario = [
    (10.0, 1, "Idle"),
    (250.0, 1, "SHARP SPIKE! (typical compressor)"),
    (220.0, 1, "Running"),
    (220.0, 2, "Running..."),
    (10.0, 1, "Shutdown"),
    (10.0, 1, "Idle"),
]

print("\nFridge Detector recognizing sharp startup spike:\n")
fridge_detector.reset() if hasattr(fridge_detector, 'reset') else None
step = 0
for power_w, duration, desc in fridge_scenario:
    for _ in range(duration):
        reading = PowerReading(datetime.now(), power_w, "L1")
        state = fridge_detector.detect(reading)
        state_str = f"{state.value[:3]}" if state else "---"
        
        step += 1
        print(f"  {step}. {power_w:6.1f}W → {state_str}  │  {desc}")
        time.sleep(0.2)

print(f"\n✓ Fridge cycle recognized: {fridge_detector.current_state.value}")

# Scenario 2: Inverter Device (Heat Pump) Operation
print("\n" + "=" * 90)
print("SCENARIO 2: INVERTER DEVICE (Heat Pump / Modern Washing Machine)")
print("=" * 90)

inverter_scenario = [
    (5.0, 1, "Idle / Standby"),
    (80.0, 1, "Soft ramp start ↗"),
    (150.0, 1, "    ↗ Ramping up"),
    (200.0, 1, "    ↗ Still ramping"),
    (280.0, 1, "    stabilizing"),
    (320.0, 1, "Peak operation"),
    (280.0, 1, "Operation stable"),
    (200.0, 1, "Ramp down ↘"),
    (100.0, 1, "  ↘ Decreasing"),
    (30.0, 1, "  ↘ Final phase"),
    (5.0, 2, "Shutdown / Idle"),
]

print("\nInverter Detector recognizing gradual ramp:\n")
inverter_detector.reset() if hasattr(inverter_detector, 'reset') else None
step = 0
for power_w, duration, desc in inverter_scenario:
    for _ in range(duration):
        reading = PowerReading(datetime.now(), power_w, "L1")
        state = inverter_detector.detect(reading)
        state_str = f"{state.value[:3]}" if state else "---"
        
        # Get diagnostic
        diag = inverter_detector.get_diagnostics()
        slope = diag['power_slope_w_per_s']
        
        step += 1
        slope_str = f"Slope: {slope:+6.1f}W/s"
        print(f"  {step:2d}. {power_w:6.1f}W → {state_str}  │  {slope_str}  │  {desc}")
        time.sleep(0.2)

print(f"\n✓ Inverter cycle recognized: {inverter_detector.current_state.value}")

# Comparison table
print("\n" + "=" * 90)
print("COMPARISON")
print("=" * 90)

comparison_data = [
    ("Startup Characteristic", "Sharp spike (instant)", "Gradual ramp (2-5s)"),
    ("Power Stability", "Stable during run", "Variable (control loop)"),
    ("Min Runtime", "Often 30-60s", "Often 30s-several minutes"),
    ("Shutdown", "Instant drop", "Gradual decrease"),
    ("Harmonic Distortion", "Low (5-15% THD)", "High (20-40% THD)"),
    ("Detection Method", "Spike + Threshold", "Slope + Stability"),
    ("Examples", "Fridges, Freezers", "Heat pumps, Mod. Washers, Dishwashers"),
]

print("\n{:<30} {:<35} {:<35}".format("Characteristic", "Non-Inverter", "Inverter"))
print("-" * 100)
for char, non_inv, inv in comparison_data:
    print("{:<30} {:<35} {:<35}".format(char, non_inv, inv))

# Diagnostics
print("\n" + "=" * 90)
print("DETECTOR DIAGNOSTICS")
print("=" * 90)

print("\nFridge Detector (last state):")
print(f"  Current State: {fridge_detector.current_state.value}")

print("\nInverter Detector (last state):")
diag = inverter_detector.get_diagnostics()
print(f"  Current State: {diag['state']}")
print(f"  Power Slope: {diag['power_slope_w_per_s']:.2f}W/s")
print(f"  Power Stable: {diag['is_stable']}")
print(f"  Recent Power: {diag['recent_power_w']:.1f}W")
print(f"  Cycle Duration: {diag['cycle_elapsed_s']:.1f}s")

# Summary
print("\n" + "=" * 90)
print("KEY INSIGHTS")
print("=" * 90)

print("""
🔧 Non-Inverter Devices (Traditional):
   ✓ Easy to detect: sudden power spike
   ✓ Stable operation: constant power
   ✓ Quick detection: ~1 second
   ✗ All-or-nothing: no partial load
   
⚡ Inverter Devices (Modern):
   ✓ Efficient: variable power adjustment
   ✓ Soft start: protects electronics
   ✓ Quiet operation: less mechanical stress
   ✗ Harder to detect: gradual ramps
   ✗ Complex patterns: sub-cycles
   
🎯 Best Approach:
   → Use BOTH detectors in parallel (hybrid)
   → Let StateEngine pick the right one
   → Or use Inverter detector for both (more general)
""")

print("\n✓ Test Complete!")
print("=" * 90 + "\n")
