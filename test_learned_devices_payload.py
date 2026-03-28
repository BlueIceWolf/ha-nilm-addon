#!/usr/bin/env python3

import os
import sys
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), 'ha-nilm-detector'))

from app.main import NILMDetectionSystem
from app.models import PowerReading


class StubStorage:
    def list_patterns(self, limit: int = 100):
        return [
            {
                "id": 7,
                "device_group_label": "dishwasher",
                "user_label": "",
                "candidate_name": "dishwasher",
                "suggestion_type": "dishwasher",
                "seen_count": 6,
                "confidence_score": 82.0,
                "avg_power_w": 150.0,
                "peak_power_w": 180.0,
                "phase": "L1",
                "is_confirmed": False,
            },
            {
                "id": 8,
                "device_group_label": "dishwasher",
                "user_label": "",
                "candidate_name": "dishwasher",
                "suggestion_type": "dishwasher",
                "seen_count": 2,
                "confidence_score": 55.0,
                "avg_power_w": 145.0,
                "peak_power_w": 170.0,
                "phase": "L1",
                "is_confirmed": False,
            },
        ]


def test_learned_patterns_are_exposed_as_virtual_devices():
    system = NILMDetectionSystem.__new__(NILMDetectionSystem)
    system.storage = StubStorage()

    latest = PowerReading(
        timestamp=datetime(2026, 3, 28, 12, 0, 0),
        power_w=165.0,
        phase="TOTAL",
        metadata={"phase_powers_w": {"L1": 165.0}},
    )

    payload = system._build_learned_devices_payload(latest=latest, existing_names=set())

    assert "dishwasher" in payload
    assert payload["dishwasher"]["source"] == "learned_pattern"
    assert payload["dishwasher"]["state"] == "on"
    assert payload["dishwasher"]["pattern_id"] == 7


def test_learned_devices_get_suffix_on_name_collision():
    system = NILMDetectionSystem.__new__(NILMDetectionSystem)
    system.storage = StubStorage()

    latest = PowerReading(
        timestamp=datetime(2026, 3, 28, 12, 0, 0),
        power_w=165.0,
        phase="TOTAL",
        metadata={"phase_powers_w": {"L1": 165.0}},
    )

    payload = system._build_learned_devices_payload(latest=latest, existing_names={"dishwasher"})

    assert "dishwasher (learned)" in payload