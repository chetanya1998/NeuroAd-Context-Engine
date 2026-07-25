from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import runpod_client
from runpod_client import RunPodClient, RunPodSettings, parse_json_completion


def test_runpod_settings_derive_openai_base_url(monkeypatch):
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "endpoint-123")
    monkeypatch.delenv("RUNPOD_BASE_URL", raising=False)

    settings = RunPodSettings.from_env()

    assert settings.configured
    assert settings.base_url == "https://api.runpod.ai/v2/endpoint-123/openai/v1"
    assert settings.model == "neuroad-reasoner"
    assert "secret" not in str(settings.public_status())


def test_parse_json_completion_accepts_fenced_json():
    result = parse_json_completion(
        """```json
        {"executive_summary":"Grounded summary","creative_actions":["Shorten the opening."]}
        ```"""
    )

    assert result["executive_summary"] == "Grounded summary"
    assert result["creative_actions"] == ["Shorten the opening."]


def test_runpod_client_requests_json_mode_and_preserves_malformed_json_reason(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"summary":"one"\n"next":"two"}'}}]}

    class FakeClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json):
            assert json["response_format"] == {"type": "json_object"}
            return FakeResponse()

    monkeypatch.setattr(runpod_client.httpx, "Client", FakeClient)
    monkeypatch.setattr(runpod_client.time, "sleep", lambda _: None)
    settings = RunPodSettings("secret", "https://example.test/openai/v1", "model", 30, 1000, 0)
    try:
        RunPodClient(settings).chat_json(system_prompt="JSON", user_payload={})
    except runpod_client.RunPodError as exc:
        assert "malformed JSON" in str(exc)
        assert "line 2, column 1" in str(exc)
    else:
        raise AssertionError("Expected malformed JSON to be reported.")


def test_runpod_client_retries_without_json_mode_when_worker_rejects_it(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code, text, payload):
            self.status_code, self.text, self.payload = status_code, text, payload
        def json(self): return self.payload

    class FakeClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json):
            calls.append(json)
            if len(calls) == 1:
                return FakeResponse(400, "response_format is unsupported", {})
            return FakeResponse(200, "", {"choices": [{"message": {"content": '{"summary":"ready"}'}}]})

    monkeypatch.setattr(runpod_client.httpx, "Client", FakeClient)
    settings = RunPodSettings("secret", "https://example.test/openai/v1", "model", 30, 1000, 0)
    result = RunPodClient(settings).chat_json(system_prompt="JSON", user_payload={})
    assert result == {"summary": "ready"}
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_runpod_client_uses_openai_compatible_chat_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"executive_summary":"Ready"}'}}]}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr(runpod_client.httpx, "Client", FakeClient)
    settings = RunPodSettings(
        api_key="secret",
        base_url="https://api.runpod.ai/v2/test/openai/v1",
        model="neuroad-reasoner",
        timeout_seconds=300,
        max_tokens=1000,
        max_retries=0,
    )

    result = RunPodClient(settings).chat_json(system_prompt="Return JSON.", user_payload={"evidence": True})

    assert result == {"executive_summary": "Ready"}
    assert captured["url"].endswith("/openai/v1/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["payload"]["model"] == "neuroad-reasoner"


def test_normalize_runpod_insights_bounds_lists_and_text():
    result = main.normalize_runpod_insights(
        {
            "executive_summary": "  Evidence   summary  ",
            "placement_strategy": "Use the strongest supported slot.",
            "creative_actions": ["one", "one", "two", "three", "four", "five", "six"],
            "brand_safety_notes": "not a list",
            "confidence_notes": ["Transcript evidence is limited."],
        }
    )

    assert result["executive_summary"] == "Evidence summary"
    assert result["creative_actions"] == ["one", "two", "three", "four", "five"]
    assert result["brand_safety_notes"] == []


def test_runpod_evidence_payload_accepts_in_memory_ad_match_shape():
    video = {"title": "Hydration review", "description": "Product comparison", "duration_seconds": 30}
    segment = {
        "start": 0,
        "end": 10,
        "attention_score": 82,
        "ad_fit_score": 78,
        "drop_risk_score": 18,
        "brand_safety_score": 96,
        "label": "High attention",
        "recommendation_tier": "Strong ad slot",
        "recommendation_confidence": 84,
        "ad_slot_score": 80,
        "ad_slot_reasons": ["clear product context"],
        "transcript": "A clear explanation of hydration and electrolytes.",
        "transcript_insights": {"clarity_score": 90},
        "visual_evidence": {"visual_quality": 0.85},
        "topics": [{"label": "health", "confidence": 0.9}],
        "objects": [{"label": "bottle", "confidence": 0.88}],
        "ad_matches": [{"category": "Functional Beverage", "ad_fit_score": 78, "confidence": 82}],
        "strong_signals": ["clear transcript"],
        "failed_or_weak_signals": [],
    }

    result = main.build_runpod_evidence_payload(video, [segment])

    assert result["deterministic_summary"]["top_ad_category"] == "Functional Beverage"
    assert result["selected_segments"][0]["ad_matches"][0]["category"] == "Functional Beverage"


def test_persisted_runpod_insights_are_returned(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "runpod.db")
    main.init_db()
    settings = RunPodSettings(
        api_key="secret",
        base_url="https://api.runpod.ai/v2/test/openai/v1",
        model="neuroad-reasoner",
        timeout_seconds=300,
        max_tokens=1000,
        max_retries=2,
    )
    content = {
        "executive_summary": "Evidence-grounded result.",
        "placement_strategy": "Use the best supported slot.",
        "creative_actions": [],
        "brand_safety_notes": [],
        "confidence_notes": [],
    }

    main.persist_runpod_insights("video_test", settings, "completed", content=content)
    result = main.get_runpod_insights("video_test")

    assert result is not None
    assert result["status"] == "completed"
    assert result["model"] == "neuroad-reasoner"
    assert result["content"] == content
