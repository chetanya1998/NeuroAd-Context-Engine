import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from main import (
    attention_label,
    convertible_video_suffix_from_url,
    cors_origins_from_env,
    create_video_from_url,
    download_remote_video,
    extract_audio,
    health,
    is_youtube_media_blocked,
    make_segments,
    public_job_error,
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
    assert convertible_video_suffix_from_url("https://cdn.example.com/video.mkv") == ".mkv"
    assert convertible_video_suffix_from_url("https://cdn.example.com/video.avi") == ".avi"
    assert convertible_video_suffix_from_url("https://cdn.example.com/video.pdf") is None


def test_video_url_endpoint_accepts_extractable_media_page_urls(monkeypatch):
    inserted = {}
    monkeypatch.setattr(main, "new_id", lambda prefix: f"{prefix}_test")

    def fake_execute(sql, params=()):
        inserted["params"] = params

    monkeypatch.setattr(main, "execute", fake_execute)

    payload = main.VideoUrlRequest(url="https://media.example.com/watch/abc123")
    response = create_video_from_url(payload)

    assert response["video_id"] == "video_test"
    assert response["status"] == "uploaded"
    assert inserted["params"][3] == "Media page URL queued for real extraction and analysis."


def test_remote_video_without_file_extension_uses_extractor(monkeypatch):
    expected = Path("/tmp/extracted.mp4")

    def fake_extract(url, video_id=None):
        return expected, video_id or "video_generated"

    monkeypatch.setattr(main, "download_extractable_video", fake_extract)

    path, video_id = download_remote_video("https://media.example.com/watch/abc123", "video_test")

    assert path == expected
    assert video_id == "video_test"


def test_health_reports_deployment_limits():
    payload = health()
    assert payload["limits"]["max_upload_mb"] == 200
    assert payload["limits"]["max_analysis_seconds"] == 180
    assert "ffmpeg" in payload["dependencies"]


def test_youtube_bot_challenge_is_detected():
    error = RuntimeError("Sign in to confirm you’re not a bot. Use --cookies for authentication.")
    assert is_youtube_media_blocked(error)


def test_object_detection_falls_back_when_model_loading_fails(monkeypatch):
    monkeypatch.delenv("NEUROAD_REQUIRE_OBJECT_DETECTION", raising=False)

    def broken_detector(frames):
        raise RuntimeError("OpenCV could not import MobileNet graph")

    monkeypatch.setattr(main, "detect_mobilenet_ssd_objects", broken_detector)
    monkeypatch.setattr(main, "detect_lightweight_visual_context", lambda frames: {1: []})

    assert main.detect_objects({1: {"path": "frame.jpg", "timestamp": 0}}) == {1: []}


def test_extract_audio_returns_none_when_video_has_no_audio(monkeypatch, tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(main, "has_audio_stream", lambda path: False)
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert extract_audio("video_test", source) is None


def test_public_job_error_hides_raw_subprocess_command():
    error = subprocess.CalledProcessError(
        234,
        ["/usr/bin/ffmpeg", "-i", "/data/neuroad/storage/uploads/video.mp4"],
        stderr="ffmpeg version\nInvalid data found when processing input\n",
    )

    message = public_job_error(error)

    assert "/usr/bin/ffmpeg" not in message
    assert "Invalid data found when processing input" in message
