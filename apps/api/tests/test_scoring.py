import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (
    attention_label,
    build_metadata_fallback_segments,
    convertible_video_suffix_from_url,
    cors_origins_from_env,
    health,
    is_youtube_media_blocked,
    make_segments,
    score_attention,
)


def test_segmentation_short_video_uses_two_second_chunks():
    segments = make_segments(10)
    assert len(segments) == 5
    assert segments[0]["end"] == 2


def test_segmentation_caps_long_video_at_three_minutes():
    segments = make_segments(900)
    assert segments[-1]["end"] == 180


def test_attention_score_is_bounded():
    assert score_attention(2, 2, 2, 2, 2, 2, 2) == 100
    assert score_attention(-2, -2, -2, -2, -2, -2, -2) == 0


def test_attention_labels():
    assert attention_label(85) == "High attention"
    assert attention_label(65) == "Good attention"
    assert attention_label(45) == "Neutral"
    assert attention_label(25) == "Drop risk"
    assert attention_label(10) == "Weak moment"


def test_cors_origins_can_be_configured(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, http://localhost:3000")
    assert cors_origins_from_env() == ["https://app.example.com", "http://localhost:3000"]


def test_convertible_video_suffixes_include_common_container_formats():
    assert convertible_video_suffix_from_url("https://cdn.example.com/demo.mkv") == ".mkv"
    assert convertible_video_suffix_from_url("https://cdn.example.com/demo.avi") == ".avi"
    assert convertible_video_suffix_from_url("https://cdn.example.com/demo.pdf") is None


def test_health_reports_deployment_limits():
    payload = health()
    assert payload["limits"]["max_upload_mb"] == 200
    assert payload["limits"]["max_analysis_seconds"] == 180
    assert "ffmpeg" in payload["dependencies"]


def test_youtube_bot_challenge_is_detected():
    error = RuntimeError("Sign in to confirm you’re not a bot. Use --cookies for authentication.")
    assert is_youtube_media_blocked(error)


def test_youtube_metadata_fallback_builds_limited_segments():
    video = {
        "id": "video_test",
        "title": "AI productivity workflow for founders",
        "description": "A dashboard automation tutorial for startup teams.",
        "duration_seconds": 120,
        "thumbnail_url": "https://img.youtube.com/vi/example/hqdefault.jpg",
    }
    segments = build_metadata_fallback_segments(video)
    assert len(segments) == 4
    assert segments[0]["label"] == "Metadata estimate"
    assert segments[0]["thumbnail_url"] == video["thumbnail_url"]
    assert segments[0]["topics"]
