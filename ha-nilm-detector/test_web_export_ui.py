#!/usr/bin/env python3

import json
import os
import sys
from urllib.request import urlopen

sys.path.append(os.path.dirname(__file__))

from app.web.server import StatsWebServer


class _FakeStorage:
    def export_shared_pattern_pack(self, limit: int = 1000, confirmed_only: bool = True):
        return {
            "format": "ha_nilm_shared_pattern_pack_v1",
            "counts": {"patterns": 1, "confirmed_only": bool(confirmed_only)},
            "patterns": [{"shared_pattern_id": "abc", "public_label": "fridge"}],
        }

    def export_llm_review_bundle(self, pattern_limit: int = 100, event_limit: int = 200, readings_limit: int = 5000, include_readings: bool = True):
        return {
            "format": "ha_nilm_llm_review_bundle_v1",
            "patterns": [{"pattern_id": 1, "shape_signature": "[0.1,0.5,0.2]"}],
            "events": [{"event_id": 10, "label": "fridge"}],
            "classification_log": [],
            "training_log": [],
            "power_readings": [{"timestamp": "2026-04-06T15:00:00", "power_w": 280.0, "phases": {"L1": 280.0}}] if include_readings else [],
            "counts": {"power_readings": 1 if include_readings else 0},
        }


def _empty_dict():
    return {}


def _empty_list(*_args, **_kwargs):
    return []


def test_web_ui_exposes_new_export_buttons_and_endpoints():
    server = StatsWebServer(
        host="127.0.0.1",
        port=0,
        get_live_data=_empty_dict,
        get_summary_data=_empty_dict,
        get_series_data=_empty_list,
        get_patterns_data=lambda _limit=500: [],
        storage=_FakeStorage(),
        language="de",
        build_info={"version": "0.6.40", "git_short_commit": "deadbeef"},
    )
    try:
        assert server.start() is True
        assert server._server is not None
        port = int(server._server.server_address[1])

        with urlopen(f"http://127.0.0.1:{port}/") as response:
            html = response.read().decode("utf-8")
        assert "exportSharedBtn" in html
        assert "exportLlmBtn" in html
        assert "0.6.40" in html

        with urlopen(f"http://127.0.0.1:{port}/api/debug/export-shared-pattern-pack") as response:
            shared_payload = json.loads(response.read().decode("utf-8"))
        assert shared_payload["format"] == "ha_nilm_shared_pattern_pack_v1"
        assert int(shared_payload["counts"]["patterns"]) == 1

        with urlopen(f"http://127.0.0.1:{port}/api/debug/export-llm-review-bundle") as response:
            llm_payload = json.loads(response.read().decode("utf-8"))
        assert llm_payload["format"] == "ha_nilm_llm_review_bundle_v1"
        assert len(llm_payload["patterns"]) == 1
        assert len(llm_payload["events"]) == 1
        assert len(llm_payload["power_readings"]) == 1
    finally:
        server.stop()