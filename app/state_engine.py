"""
State engine for managing device states and timers.
"""
from datetime import datetime, timedelta
from typing import Dict, Optional
from app.models import DeviceState, DeviceState_, DeviceConfig, PowerReading
from app.utils.logging import get_logger


logger = get_logger(__name__)


class StateEngine:
    """Manages device states with hysteresis and timing logic."""
    
    def __init__(self):
        """Initialize state engine."""
        self.states: Dict[str, DeviceState_] = {}
        self.device_configs: Dict[str, DeviceConfig] = {}
    
    def register_device(self, device_name: str, config: DeviceConfig) -> None:
        """
        Register a device.
        
        Args:
            device_name: Device identifier
            config: Device configuration
        """
        self.device_configs[device_name] = config
        self.states[device_name] = DeviceState_(
            device_name=device_name,
            state=DeviceState.OFF,
            power_w=0.0
        )
        logger.info(f"Registered device: {device_name}")
    
    def update_device_state(
        self,
        device_name: str,
        state: DeviceState,
        power_w: float,
        detection_result: Optional[Dict] = None
    ) -> DeviceState_:
        """
        Update device state with state machine logic.
        
        Args:
            device_name: Device identifier
            state: Detected state
            power_w: Detected power in watts
            detection_result: Additional detection details
        
        Returns:
            Updated device state
        """
        if device_name not in self.states:
            logger.warning(f"Unknown device: {device_name}")
            return None
        
        current_state = self.states[device_name]
        config = self.device_configs[device_name]
        now = datetime.now()
        
        # State machine logic
        if state == DeviceState.ON and current_state.state == DeviceState.OFF:
            # Device turning on
            if current_state.last_start is None:
                current_state.last_start = now
            current_state.state = DeviceState.STARTING
            logger.debug(f"{device_name} is starting")
        
        elif state == DeviceState.ON and current_state.state in [DeviceState.ON, DeviceState.STARTING]:
            # Device still on
            current_state.state = DeviceState.ON
        
        elif state == DeviceState.OFF and current_state.state in [DeviceState.ON, DeviceState.STARTING]:
            # Device turning off
            if current_state.last_start:
                runtime = (now - current_state.last_start).total_seconds()
                
                # Check minimum runtime
                if runtime >= config.min_runtime_seconds:
                    current_state.runtime_seconds = runtime
                    current_state.daily_runtime_seconds += runtime
                    current_state.daily_cycles += 1
                    current_state.state = DeviceState.OFF
                    logger.debug(
                        f"{device_name} stopped (runtime: {runtime:.1f}s, "
                        f"daily_cycles: {current_state.daily_cycles})"
                    )
                else:
                    # Runtime too short, stay on
                    logger.debug(
                        f"{device_name} runtime too short ({runtime:.1f}s), "
                        f"minimum: {config.min_runtime_seconds}s"
                    )
                    current_state.state = DeviceState.ON
        
        elif state == DeviceState.OFF and current_state.state == DeviceState.OFF:
            # Device already off
            pass
        
        current_state.power_w = power_w
        current_state.last_update = now
        
        if detection_result:
            current_state.metadata.update(detection_result)
        
        return current_state
    
    def get_device_state(self, device_name: str) -> Optional[DeviceState_]:
        """Get current device state."""
        return self.states.get(device_name)
    
    def get_all_states(self) -> Dict[str, DeviceState_]:
        """Get all device states."""
        return self.states.copy()
    
    def reset_daily_counters(self, device_name: str) -> None:
        """Reset daily counters."""
        if device_name in self.states:
            self.states[device_name].daily_runtime_seconds = 0.0
            self.states[device_name].daily_cycles = 0
            logger.debug(f"Reset daily counters for {device_name}")
    
    def reset_all_daily_counters(self) -> None:
        """Reset daily counters for all devices."""
        for device_name in self.states:
            self.reset_daily_counters(device_name)
