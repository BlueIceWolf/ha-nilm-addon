"""State engine for managing device states, timing, and hysteresis."""
from datetime import datetime
from typing import Dict, Optional

from app.models import (DeviceState, DeviceState_, DeviceConfig,
                        DetectionResult)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class StateEngine:
    """Keeps track of devices with timing constraints and hysteresis."""

    def __init__(self):
        self.states: Dict[str, DeviceState_] = {}
        self.device_configs: Dict[str, DeviceConfig] = {}

    def register_device(self, device_name: str, config: DeviceConfig) -> None:
        self.device_configs[device_name] = config
        self.states[device_name] = DeviceState_(
            device_name=device_name,
            state=DeviceState.OFF,
            power_w=0.0,
        )
        logger.info(f"Registered device: {device_name}")

    def update_device_state(self, detection: DetectionResult) -> Optional[DeviceState_]:
        device_name = detection.device_name
        if device_name not in self.states:
            logger.warning(f"Unknown device: {device_name}")
            return None

        current_state = self.states[device_name]
        config = self.device_configs[device_name]
        now = datetime.now()
        state = detection.state
        power_w = detection.power_w

        if state == DeviceState.ON and current_state.state == DeviceState.OFF:
            if current_state.last_start is None:
                current_state.last_start = now
            current_state.state = DeviceState.STARTING
            logger.debug(f"{device_name} is starting")

        elif state == DeviceState.ON and current_state.state in [DeviceState.STARTING, DeviceState.ON]:
            if current_state.state == DeviceState.STARTING:
                logger.debug(f"{device_name} entered RUNNING state")
            current_state.state = DeviceState.ON

        elif state == DeviceState.OFF and current_state.state in [DeviceState.ON, DeviceState.STARTING]:
            if current_state.last_start:
                runtime = (now - current_state.last_start).total_seconds()
                if runtime >= config.min_runtime_seconds:
                    current_state.runtime_seconds = runtime
                    current_state.daily_runtime_seconds += runtime
                    current_state.daily_cycles += 1
                    current_state.state = DeviceState.OFF
                    logger.debug(
                        f"{device_name} stopped (runtime={runtime:.1f}s, cycles={current_state.daily_cycles})"
                    )
                else:
                    logger.debug(
                        f"{device_name} runtime {runtime:.1f}s below minimum {config.min_runtime_seconds}s, staying ON"
                    )
                    current_state.state = DeviceState.ON

        elif state == DeviceState.OFF and current_state.state == DeviceState.OFF:
            pass

        current_state.power_w = power_w
        current_state.last_update = now
        current_state.confidence = detection.confidence
        if detection.details:
            current_state.metadata.update(detection.details)

        return current_state

    def get_device_state(self, device_name: str) -> Optional[DeviceState_]:
        return self.states.get(device_name)

    def get_all_states(self) -> Dict[str, DeviceState_]:
        return self.states.copy()

    def reset_daily_counters(self, device_name: str) -> None:
        if device_name in self.states:
            self.states[device_name].daily_runtime_seconds = 0.0
            self.states[device_name].daily_cycles = 0
            logger.debug(f"Reset daily counters for {device_name}")

    def reset_all_daily_counters(self) -> None:
        for device_name in self.states:
            self.reset_daily_counters(device_name)
