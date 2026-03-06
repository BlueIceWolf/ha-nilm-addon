"""
Automatic device detection for NILM system.
Learns device patterns from power consumption data.
"""
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import statistics

from app.models import PowerReading
from app.utils.logging import get_logger


logger = get_logger(__name__)


@dataclass
class DetectedDevice:
    """Automatically detected device."""
    id: str
    name: str
    power_signature: List[float] = field(default_factory=list)
    avg_power_w: float = 0.0
    peak_power_w: float = 0.0
    runtime_pattern: List[int] = field(default_factory=list)  # minutes per day
    confidence: float = 0.0
    device_type: str = "unknown"
    last_seen: Optional[datetime] = None


class AutoDetector:
    """
    Automatic device detection using clustering and pattern recognition.
    
    Learns device signatures from power consumption patterns.
    """
    
    def __init__(self, learning_period_hours: int = 24):
        """
        Initialize auto detector.
        
        Args:
            learning_period_hours: Hours to collect data before detection
        """
        self.learning_period = timedelta(hours=learning_period_hours)
        self.power_history: List[PowerReading] = []
        self.detected_devices: Dict[str, DetectedDevice] = {}
        self.baseline_power = 0.0
        self.learning_start: Optional[datetime] = None
        self.is_learning = True
        
        # Detection parameters
        self.min_power_threshold = 50.0  # W - ignore small loads
        self.peak_detection_threshold = 100.0  # W - potential device start
        self.min_event_duration = 30  # seconds
        self.similarity_threshold = 0.8  # for pattern matching
        
    def add_reading(self, reading: PowerReading) -> Optional[DetectedDevice]:
        """
        Add power reading and detect devices.
        
        Args:
            reading: New power reading
            
        Returns:
            Detected device if new device found, None otherwise
        """
        self.power_history.append(reading)
        
        # Keep only recent history (last 24h)
        cutoff = datetime.now() - timedelta(hours=24)
        self.power_history = [r for r in self.power_history if r.timestamp > cutoff]
        
        # Initialize learning
        if self.learning_start is None:
            self.learning_start = reading.timestamp
            logger.info("Started learning baseline power consumption")
            return None
            
        # Still in learning phase
        if reading.timestamp - self.learning_start < self.learning_period:
            self._update_baseline()
            return None
            
        # Learning complete, start detection
        if self.is_learning:
            self.is_learning = False
            logger.info(f"Learning complete. Baseline power: {self.baseline_power:.1f}W")
            
        # Detect power events
        detected = self._detect_power_event(reading)
        if detected:
            device = self._classify_device(detected)
            if device:
                return device
                
        return None
        
    def _update_baseline(self):
        """Update baseline power consumption during learning phase."""
        if len(self.power_history) < 10:
            return
            
        recent_readings = self.power_history[-100:]  # last ~5 minutes
        powers = [r.power_w for r in recent_readings]
        
        # Use median to avoid outliers
        self.baseline_power = statistics.median(powers)
        
    def _detect_power_event(self, reading: PowerReading) -> Optional[Dict]:
        """
        Detect significant power consumption events.
        
        Returns event data if device activation detected.
        """
        if len(self.power_history) < 2:
            return None
            
        prev_reading = self.power_history[-2]
        power_delta = reading.power_w - prev_reading.power_w
        
        # Check for significant power increase
        if power_delta > self.peak_detection_threshold:
            # Look for sustained power (not just spike)
            sustained_power = self._check_sustained_power(reading)
            if sustained_power:
                return {
                    'start_time': reading.timestamp,
                    'power_delta': power_delta,
                    'sustained_power': sustained_power,
                    'duration': self.min_event_duration
                }
                
        return None
        
    def _check_sustained_power(self, start_reading: PowerReading) -> Optional[float]:
        """
        Check if power increase is sustained.
        
        Returns average sustained power if event is valid.
        """
        # Look ahead in history for sustained power
        start_idx = len(self.power_history) - 1
        check_duration = timedelta(seconds=self.min_event_duration)
        end_time = start_reading.timestamp + check_duration
        
        sustained_readings = []
        for i in range(start_idx, min(start_idx + 60, len(self.power_history))):  # next 60 readings
            r = self.power_history[i]
            if r.timestamp > end_time:
                break
            if r.power_w > self.baseline_power + self.min_power_threshold:
                sustained_readings.append(r.power_w)
                
        if len(sustained_readings) >= 10:  # at least 10 readings sustained
            return statistics.mean(sustained_readings)
            
        return None
        
    def _classify_device(self, event_data: Dict) -> Optional[DetectedDevice]:
        """
        Classify detected power event as a device.
        
        Uses pattern matching and heuristics.
        """
        power = event_data['sustained_power']
        timestamp = event_data['start_time']
        
        # Simple classification based on power consumption
        device_type = self._guess_device_type(power)
        
        # Create unique device ID
        device_id = f"{device_type}_{int(timestamp.timestamp())}"
        
        # Check if similar device already exists
        for existing_id, existing_device in self.detected_devices.items():
            if self._devices_similar(existing_device, power, device_type):
                # Update existing device
                existing_device.last_seen = timestamp
                existing_device.confidence = min(1.0, existing_device.confidence + 0.1)
                return None  # Not a new device
                
        # New device detected
        device = DetectedDevice(
            id=device_id,
            name=f"Auto-detected {device_type}",
            avg_power_w=power,
            peak_power_w=power,
            confidence=0.5,
            device_type=device_type,
            last_seen=timestamp
        )
        
        self.detected_devices[device_id] = device
        logger.info(f"New device detected: {device.name} ({power:.1f}W)")
        
        return device
        
    def _guess_device_type(self, power_w: float) -> str:
        """Guess device type based on power consumption."""
        if 100 <= power_w <= 300:
            return "refrigerator"
        elif 500 <= power_w <= 2000:
            return "washing_machine"
        elif 1000 <= power_w <= 3000:
            return "dishwasher"
        elif 1500 <= power_w <= 4000:
            return "oven"
        else:
            return "appliance"
            
    def _devices_similar(self, device: DetectedDevice, new_power: float, new_type: str) -> bool:
        """Check if two devices are similar."""
        power_diff = abs(device.avg_power_w - new_power) / device.avg_power_w
        type_match = device.device_type == new_type
        
        return power_diff < 0.3 and type_match  # 30% power tolerance
        
    def get_detected_devices(self) -> List[DetectedDevice]:
        """Get list of all detected devices."""
        return list(self.detected_devices.values())
        
    def get_device_status(self, device_id: str) -> Optional[Dict]:
        """Get current status of a device."""
        if device_id not in self.detected_devices:
            return None
            
        device = self.detected_devices[device_id]
        
        # Simple on/off detection based on recent power
        recent_power = self._get_recent_avg_power()
        is_on = recent_power > device.avg_power_w * 0.8
        
        return {
            'device_id': device_id,
            'is_on': is_on,
            'current_power': recent_power,
            'avg_power': device.avg_power_w,
            'confidence': device.confidence,
            'last_seen': device.last_seen
        }
        
    def _get_recent_avg_power(self, minutes: int = 1) -> float:
        """Get average power over recent time period."""
        if not self.power_history:
            return 0.0
            
        cutoff = datetime.now() - timedelta(minutes=minutes)
        recent = [r.power_w for r in self.power_history if r.timestamp > cutoff]
        
        return statistics.mean(recent) if recent else 0.0