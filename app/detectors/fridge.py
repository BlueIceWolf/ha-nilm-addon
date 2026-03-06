"""
Refrigerator detector - pattern-based detection for fridge operation.
"""
from datetime import datetime, timedelta
from typing import Optional, List
import numpy as np
from app.models import DeviceState, PowerReading, DeviceConfig
from app.utils.logging import get_logger


logger = get_logger(__name__)


class FridgeDetector:
    """
    Detects refrigerator operation using rule-based pattern recognition.
    
    Fridge operating patterns:
    - Startup spike: Higher power initially (≈200-400W)
    - Running phase: Stable power consumption (≈150-300W)
    - Minimum runtime: Usually 60-300 seconds
    - Pause between cycles: Usually 10-60 minutes
    - Repetitive pattern: Regular on/off cycles
    """
    
    def __init__(self, config: DeviceConfig):
        """
        Initialize fridge detector.
        
        Args:
            config: Device configuration
        """
        self.config = config
        self.name = config.name
        self.current_state = DeviceState.OFF
        self.power_history: List[PowerReading] = []
        self.cycle_start: Optional[datetime] = None
        self.on_cycle_duration = 0.0
        self.startup_phase_end: Optional[datetime] = None
    
    def detect(self, reading: PowerReading) -> Optional[DeviceState]:
        """
        Detect fridge state from power reading.
        
        Args:
            reading: Current power reading
        
        Returns:
            Detected state or None if uncertain
        """
        # Add to history
        self.power_history.append(reading)
        if len(self.power_history) > 300:  # Keep last 5 minutes of 1-second readings
            self.power_history.pop(0)
        
        power_w = reading.power_w
        
        # Simple rule-based detection
        if self.current_state == DeviceState.OFF:
            # Check for startup
            if power_w > self.config.power_min_w:
                self.current_state = DeviceState.STARTING
                self.cycle_start = reading.timestamp
                self.startup_phase_end = reading.timestamp + timedelta(seconds=self.config.startup_duration_seconds)
                logger.debug(f"{self.name}: Detected startup (power={power_w:.1f}W)")
                return DeviceState.STARTING
        
        elif self.current_state == DeviceState.STARTING:
            # Check if power stabilizes or drops
            if power_w > self.config.power_min_w:
                # Still powered
                if reading.timestamp > self.startup_phase_end:
                    self.current_state = DeviceState.ON
                    logger.debug(f"{self.name}: Entered running phase (power={power_w:.1f}W)")
                    return DeviceState.ON
                return DeviceState.STARTING
            else:
                # Power dropped too quickly
                self.current_state = DeviceState.OFF
                logger.debug(f"{self.name}: Detected false start")
                return DeviceState.OFF
        
        elif self.current_state == DeviceState.ON:
            # Check if still running
            if power_w > self.config.power_min_w:
                # Still running
                return DeviceState.ON
            else:
                # Power dropped, check minimum runtime
                if self.cycle_start:
                    cycle_duration = (reading.timestamp - self.cycle_start).total_seconds()
                    if cycle_duration >= self.config.min_runtime_seconds:
                        self.current_state = DeviceState.OFF
                        self.on_cycle_duration = cycle_duration
                        logger.debug(
                            f"{self.name}: Cycle complete (runtime={cycle_duration:.1f}s)"
                        )
                        return DeviceState.OFF
                    else:
                        logger.debug(
                            f"{self.name}: Runtime too short ({cycle_duration:.1f}s < "
                            f"{self.config.min_runtime_seconds}s), staying on"
                        )
                        return DeviceState.ON
                else:
                    self.current_state = DeviceState.OFF
                    return DeviceState.OFF
        
        return None
    
    def get_power_stats(self, window_seconds: int = 60) -> dict:
        """
        Get power statistics for current cycle.
        
        Args:
            window_seconds: Time window to analyze
        
        Returns:
            Dictionary with power statistics
        """
        if not self.power_history:
            return {
                'min_power_w': 0,
                'max_power_w': 0,
                'avg_power_w': 0,
                'power_variance': 0,
                'readings_count': 0
            }
        
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent = [r.power_w for r in self.power_history if r.timestamp >= cutoff]
        
        if not recent:
            recent = [r.power_w for r in self.power_history[-10:]]  # Last 10 readings
        
        powers = np.array(recent) if recent else np.array([0])
        
        return {
            'min_power_w': float(np.min(powers)),
            'max_power_w': float(np.max(powers)),
            'avg_power_w': float(np.mean(powers)),
            'power_variance': float(np.var(powers)),
            'readings_count': len(recent)
        }
    
    def get_cycle_info(self) -> dict:
        """Get information about current cycle."""
        return {
            'state': self.current_state.value,
            'last_cycle_duration_s': self.on_cycle_duration,
            'power_stats': self.get_power_stats()
        }
    
    def reset(self) -> None:
        """Reset detector state."""
        self.current_state = DeviceState.OFF
        self.power_history.clear()
        self.cycle_start = None
        self.on_cycle_duration = 0.0
        self.startup_phase_end = None
        logger.info(f"{self.name}: Detector reset")
