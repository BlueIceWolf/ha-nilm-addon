"""Online learning helpers for dataset export and incremental updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


def build_pattern_dataset_rows(patterns: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in patterns:
        row = {
            "pattern_id": p.get("id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label": p.get("user_label") or p.get("suggestion_type") or "unknown",
            "features": {
                "avg_power_w": p.get("avg_power_w", 0.0),
                "peak_power_w": p.get("peak_power_w", 0.0),
                "duration_s": p.get("duration_s", 0.0),
                "energy_wh": p.get("energy_wh", 0.0),
                "power_variance": p.get("power_variance", 0.0),
                "rise_rate_w_per_s": p.get("rise_rate_w_per_s", 0.0),
                "fall_rate_w_per_s": p.get("fall_rate_w_per_s", 0.0),
                "duty_cycle": p.get("duty_cycle", 0.0),
                "peak_to_avg_ratio": p.get("peak_to_avg_ratio", 1.0),
                "num_substates": p.get("num_substates", 0),
                "has_heating_pattern": bool(p.get("has_heating_pattern", False)),
                "has_motor_pattern": bool(p.get("has_motor_pattern", False)),
                "seen_count": p.get("seen_count", 0),
                "frequency_per_day": p.get("frequency_per_day", 0.0),
                "typical_interval_s": p.get("typical_interval_s", 0.0),
                "quality_score_avg": p.get("quality_score_avg", 0.0),
                "phase": p.get("phase", "unknown"),
                "phase_mode": p.get("phase_mode", "unknown"),
            },
            "meta": {
                "status": p.get("status", "active"),
                "source": "online_learning_export",
            },
        }
        rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
