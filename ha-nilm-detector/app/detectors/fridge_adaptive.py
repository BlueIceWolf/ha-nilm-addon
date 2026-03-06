"""
Enhanced refrigerator detector with adaptive pattern recognition.
Learns from observing actual power patterns instead of fixed thresholds.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import numpy as np
from collections import deque
from app.models import DeviceState, PowerReading, DeviceConfig
from app.utils.logging import get_logger


logger = get_logger(__name__)


class AdaptiveFridgeDetector:
    """
    Advanced fridge detector with adaptive learning.
    
    Key improvements:
    - Learns baseline power from idle periods
    - Detects changes relative to baseline (not absolute)
    - Tracks power trends (rising, stable, falling)
    - Handles variable startup spikes
    - Filters noise with moving averages
    """
    
    def __init__(self, config: DeviceConfig, learning_samples: int = 30):
        """
        Initialize adaptive detector.
        
        Args:
            config: Device configuration
            learning_samples: Number of readings to learn baseline from
        """
        self.config = config
        self.name = config.name
        
        # State
        self.current_state = DeviceState.OFF
        
        # Learning mode
        self.learning_mode = True
        self.learning_samples = learning_samples
        self.baseline_power = config.power_min_w  # Start with config value
        self.baseline_variance = 5.0  # Will be updated
        
        # Power history with timestamps
        self.power_history: deque = deque(maxlen=300)  # Last 5min at 1Hz
        
        # Cycle tracking
        self.cycle_start: Optional[datetime] = None
        self.startup_phase_end: Optional[datetime] = None
        self.cycle_power_readings: List[float] = []
        
        # State thresholds (will adapt)
        self.startup_threshold_multiplier = 1.5  # 50% above baseline
        self.min_startup_duration = config.startup_duration_seconds
        self.min_runtime = config.min_runtime_seconds
    
    def detect(self, reading: PowerReading) -> Optional[DeviceState]:
        """
        Detect fridge state using adaptive pattern recognition.
        
        Args:
            reading: Current power reading
        
        Returns:
            Detected state or None if uncertain
        """
        power_w = reading.power_w
        
        # Add to history
        self.power_history.append((reading.timestamp, power_w))
        
        # Learning phase: collect idle baseline
        if self.learning_mode and self.current_state == DeviceState.OFF:
            if len(self.power_history) >= self.learning_samples:
                self._update_baseline()
                if len([p for t, p in self.power_history 
                       if p < self.baseline_power + 20]) > self.learning_samples * 0.8:
                    logger.info(f"{self.name}: Baseline established at {self.baseline_power:.1f}W ± {self.baseline_variance:.1f}W")
        
        # Get adaptive thresholds
        startup_threshold = self.baseline_power + (self.baseline_variance * self.startup_threshold_multiplier)
        off_threshold = self.baseline_power + (self.baseline_variance * 0.5)
        
        # Detect transitions
        is_power_high = power_w > startup_threshold
        is_power_low = power_w < off_threshold
        is_stable = self._is_power_stable()
        is_rising = self._is_power_rising()
        
        # State machine with adaptive logic
        if self.current_state == DeviceState.OFF:
            # OFF → STARTING: Power spike detected
            if is_power_high and is_rising:
                self.current_state = DeviceState.STARTING
                self.cycle_start = reading.timestamp
                self.startup_phase_end = reading.timestamp + timedelta(seconds=self.min_startup_duration)
                self.cycle_power_readings = [power_w]
                logger.debug(
                    f"{self.name}: Startup detected! "
                    f"Power={power_w:.1f}W (threshold={startup_threshold:.1f}W)"
                )
                return DeviceState.STARTING
        
        elif self.current_state == DeviceState.STARTING:
            # STARTING → ON: Power stabilized
            self.cycle_power_readings.append(power_w)
            
            if reading.timestamp > self.startup_phase_end and is_stable and power_w > off_threshold:
                self.current_state = DeviceState.ON
                logger.debug(
                    f"{self.name}: Startup complete, entering running phase "
                    f"(avg_power={np.mean(self.cycle_power_readings):.1f}W)"
                )
                return DeviceState.ON
            
            # STARTING → OFF: False alarm (power dropped too quickly)
            elif is_power_low:
                self.current_state = DeviceState.OFF
                self.cycle_power_readings = []
                logger.debug(f"{self.name}: False startup detected, returning to OFF")
                return DeviceState.OFF
            
            return DeviceState.STARTING
        
        elif self.current_state == DeviceState.ON:
            # ON → OFF: Power dropped
            self.cycle_power_readings.append(power_w)
            
            if is_power_low:
                # Check runtime
                if self.cycle_start:
                    runtime = (reading.timestamp - self.cycle_start).total_seconds()
                    avg_power = np.mean(self.cycle_power_readings)
                    
                    if runtime >= self.min_runtime:
                        self.current_state = DeviceState.OFF
                        logger.debug(
                            f"{self.name}: Cycle complete "
                            f"(runtime={runtime:.1f}s, avg_power={avg_power:.1f}W)"
                        )
                        self.cycle_power_readings = []
                        return DeviceState.OFF
                    else:
                        logger.debug(
                            f"{self.name}: Transient drop (runtime={runtime:.1f}s < min={self.min_runtime}s)"
                        )
                        return DeviceState.ON
                else:
                    self.current_state = DeviceState.OFF
                    return DeviceState.OFF
            
            return DeviceState.ON
        
        return None
    
    def _update_baseline(self) -> None:
        """Update baseline power from idle periods."""
        if len(self.power_history) < 10:
            return
        
        # Get power readings in idle state (OFF)
        idle_readings = [p for t, p in self.power_history 
                         if p < self.config.power_min_w + 50]
        
        if len(idle_readings) > 5:
            self.baseline_power = float(np.mean(idle_readings))
            self.baseline_variance = float(np.std(idle_readings))
            self.baseline_variance = max(self.baseline_variance, 2.0)  # Min 2W variance
    
    def _is_power_stable(self, window_seconds: int = 5) -> bool:
        """Check if power is stable (low variance) over recent period."""
        if len(self.power_history) < 5:
            return False
        
        # Get recent readings
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent = [p for t, p in self.power_history if t >= cutoff]
        
        if not recent:
            recent = [p for t, p in list(self.power_history)[-5:]]
        
        if len(recent) < 3:
            return False
        
        variance = np.var(recent)
        return variance < 500  # Threshold: variance < 500 W²
    
    def _is_power_rising(self, window_seconds: int = 3) -> bool:
        """Check if power is rising (startup phase)."""
        if len(self.power_history) < 3:
            return False
        
        # Get recent readings
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent = [p for t, p in self.power_history if t >= cutoff]
        
        if not recent:
            recent = [p for t, p in list(self.power_history)[-3:]]
        
        if len(recent) < 2:
            return False
        
        # Check if trend is rising
        return recent[-1] > recent[0]
    
    def get_diagnostics(self) -> dict:
        """Get diagnostic information about current detection state."""
        recent_powers = [p for t, p in self.power_history][-10:] if self.power_history else []
        
        return {
            'state': self.current_state.value,
            'baseline_power_w': self.baseline_power,
            'baseline_variance_w': self.baseline_variance,
            'learning_mode': self.learning_mode,
            'startup_threshold_w': self.baseline_power + (self.baseline_variance * self.startup_threshold_multiplier),
            'recent_avg_power_w': float(np.mean(recent_powers)) if recent_powers else 0,
            'recent_power_variance': float(np.var(recent_powers)) if recent_powers else 0,
            'cycle_elapsed_s': (datetime.now() - self.cycle_start).total_seconds() if self.cycle_start else 0,
            'power_readings_buffered': len(self.power_history)
        }
