import json

from app.learning.local_llm import LocalLLMClassifier


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "label": "fridge",
                        "confidence": 0.91,
                        "device_family": "compressor",
                        "evidence": ["high inrush", "stable runtime"],
                    }
                )
            }
        }


def test_local_llm_rejects_public_endpoint():
    classifier = LocalLLMClassifier(
        enabled=True,
        base_url="https://example.com",
        model="test-model",
    )
    assert classifier.ready is False


def test_local_llm_accepts_private_endpoint():
    classifier = LocalLLMClassifier(
        enabled=True,
        base_url="http://192.168.1.20:11434",
        model="test-model",
    )
    assert classifier.ready is True


def test_local_llm_uses_structured_output_and_allowed_labels(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.learning.local_llm.requests.post", fake_post)

    classifier = LocalLLMClassifier(
        enabled=True,
        base_url="http://ollama:11434",
        model="test-model",
        min_confidence=0.65,
    )

    result = classifier.classify(
        cycle={
            "phase": "L1",
            "avg_power_w": 140.0,
            "peak_power_w": 420.0,
            "duration_s": 300.0,
            "energy_wh": 12.0,
            "derived_features": {
                "inrush_ratio": 3.0,
                "normalized_variance": 1.2,
                "has_flat_plateau": True,
                "has_inrush_spike": True,
            },
        },
        candidate_labels=["fridge", "pump"],
        similar_patterns=[],
    )

    assert result is not None
    assert result.label == "fridge"
    assert result.confidence == 0.91
    assert captured["url"] == "http://ollama:11434/api/chat"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["options"]["temperature"] == 0
    assert captured["payload"]["format"]["properties"]["label"]["enum"] == [
        "fridge",
        "pump",
        "unknown",
    ]
