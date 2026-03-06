#!/usr/bin/env python3
"""Quick test of the Fridge Detector."""

from datetime import datetime
from app.utils.logging import setup_logging
from app.detectors.fridge import FridgeDetector
from app.models import PowerReading, DeviceConfig

# Setup logging
logger = setup_logging(debug=True, name="NILM-Test")

logger.info("=" * 60)
logger.info("Quick Fridge Detection Test")
logger.info("=" * 60)

# Create configuration
config = DeviceConfig(
    name="test_fridge",
    power_min_w=15.0,
    power_max_w=400.0,
    min_runtime_seconds=5,
    min_pause_seconds=3,
    startup_duration_seconds=2
)

# Create detector
detector = FridgeDetector(config)
logger.info(f"Detector configured: {config.name}")

# Simulate power readings
test_power_values = [
    (10.0, "Idle"),
    (250.0, "Startup spike"),
    (200.0, "Running 1"),
    (200.0, "Running 2"),
    (180.0, "Running 3"),
    (190.0, "Running 4"),
    (190.0, "Running 5"),
    (5.0, "Off"),
    (10.0, "Idle after"),
]

logger.info("\nSimulating power readings:")
for power_w, desc in test_power_values:
    reading = PowerReading(datetime.now(), power_w, "L1")
    state = detector.detect(reading)
    state_str = state.value if state else "None"
    logger.info(f"  {desc:20} {power_w:6.1f}W → State: {state_str}")

logger.info("\n" + "=" * 60)
logger.info("Test Complete! ✓")
logger.info("=" * 60)
