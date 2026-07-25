from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from insight_report import BRAND_PROSPECT_DISCLAIMER, normalize_report, write_report_pdf


def test_redact_insight_text_removes_contact_identifiers():
    result = main.redact_insight_text("Email hi@example.com, call +1 415 555 0123, or visit https://example.com/a.")
    assert "hi@example.com" not in result
    assert "415 555" not in result
    assert "example.com/a" not in result
    assert result.count("[redacted") == 3


def test_object_normalization_keeps_diverse_labels_and_one_person():
    result = main.normalize_object_detections({1: [
        {"label": "person", "confidence": 0.99},
        {"label": "person", "confidence": 0.70},
        {"label": "bottle", "confidence": 0.88},
        {"label": "laptop", "confidence": 0.83},
        {"label": "car", "confidence": 0.79},
    ]})
    labels = [item["label"] for item in result[1]]
    assert labels.count("person") == 1
    assert {"bottle", "laptop", "car"}.issubset(labels)


def test_report_validation_drops_hallucinated_evidence_and_adds_disclaimer():
    report = normalize_report(
        {
            "executive_summary": "Evidence based.",
            "keywords": [{"term": "hydration", "confidence": 105, "evidence_refs": ["seg_1", "made_up"]}],
            "ad_categories": [{"category": "Beverages", "contextual_fit_score": -2, "confidence": 1000, "evidence_refs": ["made_up"]}],
            "brand_prospects": [{"brand": "Example", "category": "Beverages", "evidence_refs": ["seg_1"]}],
            "placement_opportunities": [{"segment_id": "made_up", "start": 999, "end": 1000}],
            "audience_personas": [{"persona": "Office worker", "evidence_refs": ["seg_1"], "recommended_additions": ["Show a workday use case"]}],
            "attention_improvements": [{"segment_id": "seg_1", "priority": 110, "issue": "Slow opening", "recommended_change": "Open with the benefit", "evidence_refs": ["seg_1"]}],
        },
        report_type="video", report_id="report_1", target_id="video_1", fingerprint="fingerprint", model="model",
        valid_segments={"seg_1": {"video_id": "video_1", "start": 1.0, "end": 4.0}}, valid_video_ids={"video_1"},
    )
    assert report["keywords"] == [{"term": "hydration", "type": "content", "confidence": 100, "evidence_refs": ["seg_1"]}]
    assert report["ad_categories"] == []
    assert report["placement_opportunities"] == []
    assert report["audience_personas"][0]["persona"] == "Office worker"
    assert report["attention_improvements"][0]["priority"] == 100
    assert report["brand_prospect_disclaimer"] == BRAND_PROSPECT_DISCLAIMER


def test_pdf_export_uses_reportlab_paragraphs_without_global_name_error(tmp_path):
    output = tmp_path / "insight.pdf"
    write_report_pdf(
        {
            "report_type": "video",
            "executive_summary": "A grounded summary.",
            "content_profile": {"themes": ["hydration"]},
            "audience_personas": [],
            "ad_categories": [],
            "keywords": [],
            "brand_prospects": [],
            "placement_opportunities": [],
            "attention_improvements": [],
            "creative_recommendations": [],
            "brand_safety": {"findings": []},
            "limitations": [],
        },
        output,
    )
    assert output.read_bytes().startswith(b"%PDF")


def test_insight_job_is_idempotent_and_completes_with_fake_runpod(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "insights.db")
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setenv("RUNPOD_API_KEY", "test")
    monkeypatch.setenv("RUNPOD_BASE_URL", "https://example.invalid/openai/v1")
    monkeypatch.setenv("NEUROAD_ENABLE_RUNPOD_INSIGHTS", "1")
    main.init_db()
    now = main.utc_now()
    main.execute("insert into videos (id, source_type, title, duration_seconds, status, created_at) values ('video_1', 'upload', 'Demo', 10, 'completed', ?)", (now,))
    main.execute("insert into segments (id, video_id, start_time, end_time, attention_score, ad_fit_score, label, summary, transcript, created_at) values ('seg_1', 'video_1', 0, 10, 80, 75, 'Good attention', 'demo', 'Hydration bottle review', ?)", (now,))

    class FakeRunPod:
        def __init__(self, settings): pass
        def chat_json(self, **kwargs):
            return {"executive_summary": "Grounded report.", "keywords": [{"term": "hydration", "evidence_refs": ["seg_1"]}], "ad_categories": [], "brand_prospects": [], "placement_opportunities": []}

    monkeypatch.setattr(main, "RunPodClient", FakeRunPod)
    monkeypatch.setattr(main.INSIGHT_EXECUTOR, "submit", lambda fn, *args: None)
    created = main.create_insight_report_job("video", "video_1")
    repeated = main.create_insight_report_job("video", "video_1")
    assert repeated["job_id"] == created["job_id"]
    main.process_insight_job(created["job_id"])
    report = main.query_one("select * from insight_reports where id = ?", (created["report_id"],))
    assert report["status"] == "completed"
    assert report["json_path"] is None
    assert report["pdf_path"] is None
    assert json.loads(report["content_json"])["brand_prospect_disclaimer"] == BRAND_PROSPECT_DISCLAIMER
