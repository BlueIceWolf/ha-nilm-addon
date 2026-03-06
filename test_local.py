#!/usr/bin/env python3
"""
Quick test script for local development.
Simulates power readings and detector logic without MQTT.
"""

import time
from datetime import datetime, timedelta
from ha-nilm-detector.app.utils.logging import setup_logging, get_logger
from ha-nilm-detector.app.config import Config
from ha-nilm-detector.app.state_engine import StateEngine
from ha-nilm-detector.app.detectors.fridge import FridgeDetector
from ha-nilm-detector.app.models import PowerReading, DeviceConfig, DeviceState
from ha-nilm-detector.app.collector.source import MockPowerSource, Collector


logger = get_logger(__name__)


def simulate_fridge_cycle():
    """Simulate a refrigerator cycle for testing."""
    
    # Setup logging
    setup_logging(debug=True, name="NILM-Test")
    
    logger.info("=" * 60)
    logger.info("NILM Detection System - Local Test")
    logger.info("=" * 60)
    
    # Create sample configuration
    config = DeviceConfig(
        name="kitchen_fridge",
        enabled=True,
        power_min_w=15.0,
        power_max_w=400.0,
        min_runtime_seconds=10,  # Reduced for testing
        min_pause_seconds=5,      # Reduced for testing
        startup_duration_seconds=2
    )
    
    # Setup detector and state engine
    detector = FridgeDetector(config)
    state_engine = StateEngine()
    state_engine.register_device("kitchen_fridge", config)
    
    # Simulate power readings for a fridge cycle
    test_scenario = [
        # Idle
        (10.0, 3, "Fridge idle"),
        # Startup
        (250.0, 1, "Power spike - startup"),
        # Running phase
        (200.0, 10, "Running phase"),
        # Shutdown
        (5.0, 1, "Shutdown detected"),
        # Off
        (10.0, 3, "Off phase"),
        # Another cycle
        (220.0, 1, "Second cycle startup"),
        (180.0, 8, "Second cycle running"),
        (5.0, 1, "Second cycle shutdown"),
    ]
    
    logger.info("\nStarting simulation with scenario:")
    for power_w, duration_s, description in test_scenario:
        logger.info(f"  {description}: {power_w}W for {duration_s}s")
    
    logger.info("\n" + "-" * 60)
    
    # Run simulation
    for power_w, duration_s, description in test_scenario:
        logger.info(f"\n→ {description}")
        
        for i in range(duration_s):
            # Create reading
            reading = PowerReading(
                timestamp=datetime.now(),
                power_w=power_w,
                phase="L1"
            )
            
            # Detect
            detected_state = detector.detect(reading)
            
            # Update state engine
            if detected_state:
                device_state = state_engine.update_device_state(
                    "kitchen_fridge",
                    detected_state,
                    power_w,
                    detector.get_cycle_info()
                )
                
                logger.info(
                    f"  [{i+1}s] Power={power_w:.1f}W | "
                    f"Detector={detected_state.value} | "
                    f"State={device_state.state.value} | "
                    f"Cycles={device_state.daily_cycles} | "
                    f"Runtime={device_state.daily_runtime_seconds:.1f}s"
                )
            else:
                logger.debug(f"  [{i+1}s] Power={power_w:.1f}W - uncertain")
            
            # Reduced sleep for faster testing
            time.sleep(0.05)
    
    # Final summary
    logger.info("\n" + "=" * 60)
    final_state = state_engine.get_device_state("kitchen_fridge")
    logger.info("Final State Summary:")
    logger.info(f"  Device State: {final_state.state.value}")
    logger.info(f"  Total Daily Cycles: {final_state.daily_cycles}")
    logger.info(f"  Total Daily Runtime: {final_state.daily_runtime_seconds:.1f}s")
    logger.info(f"  Last Update: {final_state.last_update}")
    logger.info("=" * 60)


def test_collector():
    """Test power collector."""
    
    setup_logging(debug=True, name="NILM-Test")
    
    logger.info("\nTesting Power Collector...")
    
    source = MockPowerSource(initial_power_w=100.0)
    collector = Collector(source)
    
    if collector.connect():
        logger.info("Collector connected")
        
        for i in range(5):
            source.set_power(100.0 + i * 50)
            reading = collector.read()
            logger.info(f"Reading {i+1}: {reading.power_w:.1f}W")
            time.sleep(0.5)
        
        logger.info(f"Buffered readings: {len(collector.readings)}")
        
        collector.disconnect()
        logger.info("Collector disconnected")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "collector":
        test_collector()
    else:
        simulate_fridge_cycle()
