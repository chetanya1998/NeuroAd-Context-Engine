from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analytics
import main


class FakePostHog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.shutdown_called = False

    def capture(self, event: str, *, distinct_id: str, properties: dict) -> None:
        self.events.append((event, distinct_id, properties))

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_analytics_context_reads_posthog_headers():
    context = analytics.AnalyticsContext.from_headers(
        {
            "x-posthog-distinct-id": "browser-user",
            "x-posthog-session-id": "session-123",
        }
    )

    assert context.distinct_id == "browser-user"
    assert context.session_id == "session-123"


def test_capture_event_filters_sensitive_properties(monkeypatch):
    fake = FakePostHog()
    monkeypatch.setattr(analytics, "_client", fake)
    context = analytics.AnalyticsContext("browser-user", "session-123")

    captured = analytics.capture_event(
        "analysis_completed",
        context,
        {
            "video_id": "video_1",
            "source_url": "https://secret.example/video",
            "transcript": "private transcript",
            "processing_duration_ms": 1200,
        },
        insert_id="analysis:job_1:completed",
    )

    assert captured
    event, distinct_id, properties = fake.events[0]
    assert event == "analysis_completed"
    assert distinct_id == "browser-user"
    assert properties["video_id"] == "video_1"
    assert properties["processing_duration_ms"] == 1200
    assert properties["$session_id"] == "session-123"
    assert properties["$insert_id"] == "analysis:job_1:completed"
    assert "source_url" not in properties
    assert "transcript" not in properties


def test_capture_event_skips_missing_distinct_id(monkeypatch):
    fake = FakePostHog()
    monkeypatch.setattr(analytics, "_client", fake)

    assert not analytics.capture_event("analysis_completed", analytics.AnalyticsContext(), {"video_id": "video_1"})
    assert fake.events == []


def test_analysis_job_persists_browser_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "analytics.db")
    monkeypatch.setattr(main, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(main, "capture_event", lambda *args, **kwargs: True)
    main.init_db()
    now = main.utc_now()
    main.execute(
        """
        insert into videos (id, source_type, title, duration_seconds, status, file_path, created_at)
        values ('video_1', 'upload', 'Demo', 10, 'uploaded', '/tmp/demo.mp4', ?)
        """,
        (now,),
    )

    result = main.create_video_analysis_job(
        "video_1",
        submit=False,
        analytics_context=analytics.AnalyticsContext("browser-user", "session-123"),
    )
    job = main.query_one("select * from jobs where id = ?", (result["job_id"],))

    assert job["analytics_distinct_id"] == "browser-user"
    assert job["analytics_session_id"] == "session-123"
