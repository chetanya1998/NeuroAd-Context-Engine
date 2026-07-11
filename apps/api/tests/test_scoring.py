import sys
import subprocess
import wave
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
    evaluate_recommendation,
    health,
    is_youtube_media_blocked,
    make_segments,
    public_job_error,
    score_ad_matches,
    score_attention,
    transcript_for_segment,
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


def test_missing_transcript_with_visual_evidence_returns_conditional_or_edit_first():
    context = evaluate_recommendation(
        58,
        42,
        44,
        92,
        {"word_count": 0, "clarity_score": 0, "transcript_confidence": 0},
        {"visual_quality": 0.78, "motion": 0.34, "object_count": 2, "sampled_frames": 2},
        [{"label": "person", "confidence": 0.8}, {"label": "bottle", "confidence": 0.76}],
        [{"confidence": 62}],
    )

    assert context["tier"] in {"Conditional ad slot", "Edit before monetization"}
    assert context["evidence_mode"] == "visual_only"
    assert "transcript unavailable" in context["failed_or_weak_signals"]


def test_missing_transcript_with_weak_visual_evidence_avoids_or_edits_first():
    context = evaluate_recommendation(
        24,
        10,
        78,
        90,
        {"word_count": 0, "clarity_score": 0, "transcript_confidence": 0},
        {"visual_quality": 0.18, "motion": 0.02, "object_count": 0, "sampled_frames": 1},
        [],
        [],
    )

    assert context["tier"] in {"Avoid", "Edit before monetization"}


def test_strong_transcript_and_visual_category_evidence_returns_strong_slot():
    context = evaluate_recommendation(
        76,
        68,
        28,
        94,
        {"word_count": 20, "clarity_score": 82, "transcript_confidence": 82},
        {"visual_quality": 0.74, "motion": 0.24, "object_count": 2, "sampled_frames": 3},
        [{"label": "bottle", "confidence": 0.86}, {"label": "person", "confidence": 0.72}],
        [{"confidence": 76}],
    )

    assert context["tier"] == "Strong ad slot"


def test_person_only_does_not_create_strong_product_category():
    matches = score_ad_matches(
        [{"label": "person", "confidence": 0.9}],
        [],
        "",
        82,
        "",
        96,
        20,
    )

    assert not matches or max(match["ad_fit_score"] for match in matches) < 60


def test_transcript_quality_flags_unrealistic_speech_rate():
    insights = main.analyze_transcript_segment(" ".join(["hydration"] * 20), 2, 0, 0.62)

    assert "unrealistic_speech_rate" in insights["transcript_quality_flags"]
    assert insights["transcript_confidence"] <= 35


def test_duplicate_nearby_transcript_lowers_confidence():
    insights = main.analyze_transcript_segment("clear hydration cue here", 2, 0, 0.75)
    main.apply_transcript_sequence_quality(insights, "clear hydration cue here", "clear hydration cue here")

    assert "duplicate_nearby_transcript" in insights["transcript_quality_flags"]
    assert insights["transcript_confidence"] <= 40


def test_transcript_for_segment_uses_real_overlap_not_touching_boundaries():
    transcript_segments = [
        {"start": 0, "end": 2, "text": "first window"},
        {"start": 2, "end": 4, "text": "second window"},
    ]

    assert transcript_for_segment(0, 2, transcript_segments) == "first window"
    assert transcript_for_segment(2, 4, transcript_segments) == "second window"


def test_transcript_for_segment_dedupes_repeated_chunks():
    transcript_segments = [
        {"start": 0, "end": 1, "text": "zero sugar hydration"},
        {"start": 0.4, "end": 1.4, "text": "Zero sugar hydration"},
        {"start": 1.4, "end": 2, "text": "after workout"},
    ]

    assert transcript_for_segment(0, 2, transcript_segments) == "zero sugar hydration after workout"


def test_transcript_for_segment_does_not_copy_long_chunk_to_every_window():
    transcript_segments = [{"start": 0, "end": 6, "text": "long timestamped transcript"}]
    windows = [
        transcript_for_segment(0, 2, transcript_segments),
        transcript_for_segment(2, 4, transcript_segments),
        transcript_for_segment(4, 6, transcript_segments),
    ]

    assert windows.count("long timestamped transcript") == 1


def test_hydration_terms_map_to_functional_beverage():
    matches = score_ad_matches(
        [{"label": "bottle", "confidence": 0.86}],
        [{"label": "functional beverage", "confidence": 0.8}],
        "",
        72,
        "zero sugar electrolyte hydration sachet for workouts",
        96,
        30,
    )

    assert matches
    assert matches[0]["category"].startswith("Functional Beverage")


def write_test_wav(path: Path, samples, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(main.np.asarray(samples, dtype=main.np.int16).tobytes())


def test_audio_cleanup_disabled_uses_original(monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROAD_ENABLE_AUDIO_CLEANUP", raising=False)
    source = tmp_path / "audio.wav"
    write_test_wav(source, [0, 100, -100, 0])

    assert main.cleanup_audio_with_uvr("video_test", source) == source


def test_uvr_cleanup_failure_falls_back_to_original(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROAD_ENABLE_AUDIO_CLEANUP", "1")
    monkeypatch.setenv("NEUROAD_AUDIO_CLEANUP_ENGINE", "uvr")
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path)
    source = tmp_path / "audio.wav"
    write_test_wav(source, [0, 100, -100, 0])
    monkeypatch.setattr(main.shutil, "which", lambda command: f"/usr/bin/{command}")

    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(main.subprocess, "run", fail_run)

    assert main.cleanup_audio_with_uvr("video_test", source) == source


def test_vad_suppresses_silent_regions(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROAD_ENABLE_VAD", "1")
    monkeypatch.setenv("NEUROAD_VAD_RMS_THRESHOLD", "0.01")
    monkeypatch.setenv("NEUROAD_VAD_PADDING_CHUNKS", "0")
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path)
    source = tmp_path / "audio.wav"
    silence = main.np.zeros(1600, dtype=main.np.int16)
    speech = main.np.full(1600, 9000, dtype=main.np.int16)
    write_test_wav(source, main.np.concatenate([silence, speech]))

    output = main.apply_vad_to_audio("video_test", source)

    assert output != source
    with wave.open(str(output), "rb") as wav:
        samples = main.np.frombuffer(wav.readframes(wav.getnframes()), dtype=main.np.int16)
    assert int(main.np.max(main.np.abs(samples[:1200]))) == 0
    assert int(main.np.max(main.np.abs(samples[-1200:]))) > 0


def test_yolo_unavailable_falls_back_to_mobilenet(monkeypatch):
    monkeypatch.setenv("NEUROAD_OBJECT_DETECTION_ENGINE", "yolo")
    monkeypatch.delenv("NEUROAD_REQUIRE_OBJECT_DETECTION", raising=False)
    monkeypatch.setattr(main, "detect_yolo_objects", lambda frames: (_ for _ in ()).throw(RuntimeError("missing yolo")))
    monkeypatch.setattr(main, "detect_mobilenet_ssd_objects", lambda frames: {1: [{"label": "person", "confidence": 0.7}]})

    assert main.detect_objects({1: {"path": "frame.jpg", "timestamp": 0}}) == {1: [{"label": "person", "confidence": 0.7}]}


def test_repeated_person_only_detections_are_not_product_evidence():
    detections = {
        1: [{"label": "person", "confidence": 0.91}],
        2: [{"label": "person", "confidence": 0.88}],
        3: [{"label": "person", "confidence": 0.84}],
        4: [{"label": "person", "confidence": 0.82}],
    }

    assert main.normalize_object_detections(detections) == {1: [], 2: [], 3: [], 4: []}


def test_person_detections_do_not_hide_product_objects():
    detections = {
        1: [{"label": "person", "confidence": 0.91}],
        2: [{"label": "person", "confidence": 0.88}, {"label": "bottle", "confidence": 0.74}],
        3: [{"label": "person", "confidence": 0.84}],
    }

    normalized = main.normalize_object_detections(detections)

    assert normalized[1] == []
    assert normalized[2] == [{"label": "bottle", "confidence": 0.74}]
    assert normalized[3] == []
