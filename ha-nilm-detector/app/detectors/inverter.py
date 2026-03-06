"""
Inverter-aware device detector - handles VFD, EC motor, and PWM devices.
Works with devices that have gradual power ramp instead of sharp spikes.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import numpy as np
from collections import deque
from app.models import DeviceState, PowerReading, DeviceConfig
from app.utils.logging import get_logger


logger = get_logger(__name__)


class InverterDeviceDetector:
    """
    Detects inverter-driven devices (VFD, EC motors, PWM devices).
    
    Key characteristics:
    - Gradual power ramp (not instant spikes)
    - Variable operating power (50-300W during run)
    - Possible sub-cycles (wash/spin/rinse patterns)
    - Harmonic signature (if THD available)
    - Longer runtimes than regular devices
    
    Detection strategy:
    1. Monitor power slope (dP/dt)
    2. Detect ramping up phase
    3. Track stable running phase
    4. Detect ramp down phase
    5. Confirm with duration thresholds
    """
    
    def __init__(self, config: DeviceConfig, sample_window: int = 30):
        """
        Initialize inverter detector.
        
        Args:
            config: Device configuration
            sample_window: Samples to examine for slope detection
        """
        self.config = config
        self.name = config.name
        
        # State tracking
        self.current_state = DeviceState.OFF
        self.cycle_start: Optional[datetime] = None
        self.power_history: deque = deque(maxlen=300)
        self.sample_window = sample_window
        
        # Inverter-specific thresholds (will adapt)
        self.baseline_power = config.power_min_w
        self.baseline_variance = 5.0
        
        # Phase tracking
        self.ramp_up_started: Optional[datetime] = None
        self.ramp_up_threshold = 500  # W/s - max slope for "soft start" (allows typical VFD ramps)
        self.min_ramp_duration = 1  # seconds (faster for inverter devices)
        self.min_stable_duration = 2  # seconds for running phase
        
        # Multi-state tracking
        self.state_phase_counter = 0
    
    def detect(self, reading: PowerReading) -> Optional[DeviceState]:
        """
        Detect inverter device state.
        
        Args:
            reading: Current power reading
        
        Returns:
            Detected state or None if uncertain
        """
        power_w = reading.power_w
        now = reading.timestamp
        
        # Add to history
        self.power_history.append((now, power_w))
        
        # Calculate power slope
        slope = self._calculate_slope()
        
        # Off-state baseline
        is_power_very_low = power_w < (self.baseline_power + 20)
        
        # Soft ramp detection (characteristic of inverters)
        is_ramping_up = slope > 5 and slope < self.ramp_up_threshold  # Not instant, but clear rise
        is_stable = self._is_power_stable(window=10)
        is_gradually_lowering = -self.ramp_up_threshold < slope < -5  # Gradual decrease
        
        # State machine for inverter devices
        if self.current_state == DeviceState.OFF:
            # OFF → STARTING: Detect beginning of ramp
            if slope > 5 and power_w > (self.baseline_power + 50):
                self.current_state = DeviceState.STARTING
                self.ramp_up_started = now
                self.cycle_start = now
                logger.debug(
                    f"{self.name}: Soft startup detected! "
                    f"Power={power_w:.1f}W, Slope={slope:.2f}W/s"
                )
                return DeviceState.STARTING
        
        elif self.current_state == DeviceState.STARTING:
            # STARTING → ON: Ramp completed and stabilized
            if self.ramp_up_started:
                ramp_duration = (now - self.ramp_up_started).total_seconds()
                
                if ramp_duration >= self.min_ramp_duration and is_stable and power_w > (self.baseline_power + 40):
                    self.current_state = DeviceState.ON
                    self.state_phase_counter = 1
                    logger.debug(
                        f"{self.name}: Ramp complete, entering operation "
                        f"(ramp_duration={ramp_duration:.1f}s, power={power_w:.1f}W)"
                    )
                    return DeviceState.ON
            
            # STARTING → OFF: False alarm (dropped too quickly)
            elif is_power_very_low:
                self.current_state = DeviceState.OFF
                logger.debug(f"{self.name}: False startup (power dropped immediately)")
                return DeviceState.OFF
            
            return DeviceState.STARTING
        
        elif self.current_state == DeviceState.ON:
            # ON → ON: Could be sub-cycles (e.g., wash/spin/rinse)
            # Stay ON as long as power is above baseline
            if power_w > (self.baseline_power + 30):
                return DeviceState.ON
            
            # ON → OFF: Power dropping and will stay low
            elif is_gradually_lowering or is_power_very_low:
                if self.cycle_start:
                    runtime = (now - self.cycle_start).total_seconds()
                    
                    # For inverter devices, expect longer runtimes
                    min_runtime = max(self.config.min_runtime_seconds, 10)  # At least 10s for inverters
                    
                    if runtime >= min_runtime:
                        self.current_state = DeviceState.OFF
                        logger.debug(
                            f"{self.name}: Cycle complete "
                            f"(runtime={runtime:.1f}s)"
                        )
                        return DeviceState.OFF
                    else:
                        logger.debug(
                            f"{self.name}: Transient power dip "
                            f"(runtime={runtime:.1f}s < min={min_runtime}s)"
                        )
                        return DeviceState.ON
                else:
                    self.current_state = DeviceState.OFF
                    return DeviceState.OFF
            
            return DeviceState.ON
        
        return None
    
    def _calculate_slope(self, window_seconds: int = 3) -> float:
        """
        Calculate power slope (dP/dt) in Watts per second.
        
        Args:
            window_seconds: Time window to analyze
        
        Returns:
            Slope in W/s (positive = rising, negative = falling)
        """
        if len(self.power_history) < 2:
            return 0.0
        
        # Get readings from last N seconds
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent = [(t, p) for t, p in self.power_history if t >= cutoff]
        
        if not recent or len(recent) < 2:
            recent = list(self.power_history)[-3:]
        
        if len(recent) < 2:
            return 0.0
        
        # Linear regression for slope
        times = [(t - recent[0][0]).total_seconds() for t, p in recent]
        powers = [p for t, p in recent]
        
        if len(times) > 1 and max(times) > 0:
            slope = (powers[-1] - powers[0]) / (times[-1] - times[0])
            return float(slope)
        
        return 0.0
    
    def _is_power_stable(self, window: int = 10) -> bool:
        """Check if power is stable (low variance)."""
        if len(self.power_history) < window:
            return False
        
        recent_powers = [p for t, p in list(self.power_history)[-window:]]
        variance = np.var(recent_powers)
        
        # For inverters, allow higher variance during operation
        return variance < 2000  # Threshold: variance < 2000 W²
    
    def get_diagnostics(self) -> dict:
        """Get diagnostic information."""
        recent = [p for t, p in list(self.power_history)[-10:]] if self.power_history else []
        slope = self._calculate_slope()
        
        return {
            'state': self.current_state.value,
            'power_slope_w_per_s': slope,
            'is_stable': self._is_power_stable(),
            'recent_power_w': recent[-1] if recent else 0,
            'recent_avg_power_w': float(np.mean(recent)) if recent else 0,
            'recent_power_variance': float(np.var(recent)) if recent else 0,
            'cycle_elapsed_s': (datetime.now() - self.cycle_start).total_seconds() if self.cycle_start else 0,
            'power_readings_buffered': len(self.power_history)
        }
    
    def reset(self) -> None:
        """Reset detector state for testing."""
        self.current_state = DeviceState.OFF
        self.power_history.clear()
        self.cycle_start = None
        self.ramp_up_started = None
