from typing import List, Optional

from app.models import DetectionResult, DeviceState, DeviceConfig
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ConfidenceEvaluator:
    """Evaluates and merges detector outputs into a single confident result."""

    def __init__(self, min_confidence: float = 0.6):
        self.min_confidence = min_confidence

    def evaluate(
        self,
        detection_results: List[DetectionResult],
        config: DeviceConfig,
    ) -> Optional[DetectionResult]:
        if not detection_results:
            return None

        votes = len(detection_results)
        combined_confidence = sum(r.confidence for r in detection_results) / votes
        best = max(detection_results, key=lambda r: r.confidence)

        details = {**best.details}
        details.setdefault("combined_confidence", combined_confidence)
        details.setdefault("confidence_votes", votes)

        threshold = max(self.min_confidence, config.confidence_threshold)
        if best.confidence < threshold or combined_confidence < threshold:
            logger.debug(
                f"Fallback triggered for {best.device_name}: best={best.confidence:.2f}, combined={combined_confidence:.2f}, threshold={threshold:.2f}"
            )
            fallback = DetectionResult(
                device_name=best.device_name,
                timestamp=best.timestamp,
                state=DeviceState.OFF,
                power_w=best.power_w,
                confidence=max(0.2, combined_confidence * 0.7),
                details={
                    **details,
                    "fallback_reason": "low_confidence",
                },
            )
            return fallback

        result = DetectionResult(
            device_name=best.device_name,
            timestamp=best.timestamp,
            state=best.state,
            power_w=best.power_w,
            confidence=max(best.confidence, combined_confidence),
            details=details,
        )
        return result
