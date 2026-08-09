import sys
import subprocess
import wave
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from content_signals import build_signal_payload
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
    score_ad_slot,
    score_attention,
    score_product_segment_fit,
    transcript_evidence_for_segment,
    transcript_for_segment,
    validate_public_product_url,
)


def test_segmentation_short_video_uses_two_second_chunks():
    segments = make_segments(10)
    assert len(segments) == 5
    assert segments[0]["end"] == 2


def test_segmentation_analyzes_the_full_configured_ten_minutes():
    segments = make_segments(900)
    assert segments[-1]["end"] == 600


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
    assert payload["limits"]["max_analysis_seconds"] == 600
    assert "ffmpeg" in payload["dependencies"]


def test_youtube_bot_challenge_is_detected():
    error = RuntimeError("Sign in to confirm you’re not a bot. Use --cookies for authentication.")
    assert is_youtube_media_blocked(error)


def test_object_detection_falls_back_when_model_loading_fails(monkeypatch):
    monkeypatch.setenv("NEUROAD_OBJECT_DETECTION_ENGINE", "yolo")
    monkeypatch.delenv("NEUROAD_REQUIRE_OBJECT_DETECTION", raising=False)

    def broken_detector(frames):
        raise RuntimeError("YOLO model could not be loaded")

    monkeypatch.setattr(main, "detect_yolo_objects", broken_detector)
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


def test_transcript_for_segment_uses_word_timestamps_for_readable_windows():
    transcript_segments = [
        {
            "start": 0,
            "end": 6,
            "text": "first phrase second phrase third phrase",
            "words": [
                {"word": "first", "start": 0.2, "end": 0.6},
                {"word": "phrase", "start": 0.6, "end": 1.0},
                {"word": "second", "start": 2.2, "end": 2.7},
                {"word": "phrase", "start": 2.7, "end": 3.2},
                {"word": "third", "start": 4.2, "end": 4.7},
                {"word": "phrase", "start": 4.7, "end": 5.2},
            ],
        }
    ]

    assert transcript_for_segment(0, 2, transcript_segments) == "first phrase"
    assert transcript_for_segment(2, 4, transcript_segments) == "second phrase"
    assert transcript_for_segment(4, 6, transcript_segments) == "third phrase"


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


def test_yolo_unavailable_falls_back_to_mobilenet(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROAD_OBJECT_DETECTION_ENGINE", "yolo")
    monkeypatch.delenv("NEUROAD_REQUIRE_OBJECT_DETECTION", raising=False)
    graph = tmp_path / "model.pb"
    config = tmp_path / "model.pbtxt"
    graph.write_bytes(b"model")
    config.write_text("model")
    monkeypatch.setattr(main, "MOBILENET_SSD_GRAPH", graph)
    monkeypatch.setattr(main, "MOBILENET_SSD_CONFIG", config)
    monkeypatch.setattr(main, "detect_yolo_objects", lambda frames: (_ for _ in ()).throw(RuntimeError("missing yolo")))
    monkeypatch.setattr(main, "detect_mobilenet_ssd_objects", lambda frames: {1: [{"label": "person", "confidence": 0.7}]})

    detections = main.detect_objects({1: {"path": "frame.jpg", "timestamp": 0}})

    assert detections[1][0]["label"] == "person"
    assert detections[1][0]["detector"] == "mobilenet_fallback"
    assert main.OBJECT_DETECTION_RUNTIME["degraded"] is True
    assert "missing yolo" in main.OBJECT_DETECTION_RUNTIME["fallback_reason"]


def test_faster_whisper_evidence_is_aligned_to_the_segment():
    evidence = transcript_evidence_for_segment(
        0,
        2,
        [
            {
                "start": 0,
                "end": 2,
                "text": "clear hydration cue",
                "source": "faster_whisper",
                "language": "en",
                "language_probability": 0.98,
                "avg_logprob": -0.2,
                "no_speech_prob": 0.03,
                "compression_ratio": 1.2,
                "words": [
                    {"word": "clear", "probability": 0.91},
                    {"word": "hydration", "probability": 0.94},
                ],
            }
        ],
    )

    assert evidence["source"] == "faster_whisper"
    assert evidence["language"] == "en"
    assert evidence["word_confidence"] > 0.9
    assert evidence["words"][0]["confidence"] == 0.91


def test_hindi_transcript_words_and_code_switching_are_not_treated_as_silence():
    evidence = transcript_evidence_for_segment(
        0,
        2,
        [
            {
                "start": 0,
                "end": 2,
                "text": "आज hydration कैसे बेहतर करें",
                "source": "faster_whisper",
                "language": "hi",
                "language_probability": 0.96,
                "words": [
                    {"word": "आज", "start": 0.0, "end": 0.3, "probability": 0.94},
                    {"word": "hydration", "start": 0.3, "end": 0.8, "probability": 0.9},
                    {"word": "कैसे", "start": 0.8, "end": 1.2, "probability": 0.93},
                ],
            }
        ],
    )
    insights = main.analyze_transcript_segment(
        "आज hydration कैसे बेहतर करें", 2, 0, 0.8, evidence
    )

    assert evidence["language"] == "hi-en"
    assert evidence["language_method"] == "script_and_asr"
    assert insights["word_count"] == 5
    assert insights["silence_penalty"] == 0
    assert "कैसे" in insights["hook_terms"]


def test_ad_slot_score_rewards_context_safety_and_low_drop_risk():
    strong, reasons = score_ad_slot(
        82,
        88,
        12,
        96,
        84,
        {"word_count": 10, "words_per_second": 1.9, "silence_penalty": 0},
        {"motion": 0.25},
    )
    weak, _ = score_ad_slot(
        45,
        20,
        72,
        60,
        30,
        {"word_count": 12, "words_per_second": 4.8, "silence_penalty": 0},
        {"motion": 0.85},
    )

    assert strong > weak
    assert "contextual ad fit: 88" in reasons


def test_product_fit_rewards_specific_context_and_flags_prohibited_contexts():
    product = {
        "name": "Hydration Bottle",
        "brand_name": "Aqua",
        "description": "Reusable water bottle for active runners",
        "category": "fitness",
        "keywords": ["hydration", "water bottle", "running"],
        "audience": ["runners"],
        "prohibited_contexts": ["medical claim"],
    }
    aligned = {
        "transcript": "Runners need hydration on a long running session. This water bottle stays cold.",
        "summary": "Active running and hydration context.",
        "label": "Running",
        "topics": [{"label": "fitness"}],
        "objects": [{"label": "bottle"}],
        "brand_safety_score": 95,
        "transcript_insights": {"transcript_confidence": 88},
        "visual_evidence": {"visual_quality": 0.8},
    }
    blocked = {**aligned, "transcript": "This medical claim says hydration guarantees a cure."}

    aligned_fit = score_product_segment_fit(product, aligned)
    blocked_fit = score_product_segment_fit(product, blocked)

    assert aligned_fit["fit_score"] >= 50
    assert aligned_fit["confidence"] >= 60
    assert blocked_fit["blocked"] is True
    assert blocked_fit["fit_score"] < aligned_fit["fit_score"]


def product_fit_segment(**overrides):
    base = {
        "id": "segment_fit_fixture",
        "start": 4,
        "end": 6,
        "transcript": "",
        "summary": "",
        "label": "",
        "topics": [],
        "objects": [],
        "attention_score": 60,
        "ad_slot_score": 65,
        "drop_risk_score": 30,
        "brand_safety_score": 95,
        "transcript_insights": {"transcript_confidence": 80, "word_count": 8, "words_per_second": 2},
        "visual_evidence": {"visual_quality": 0.75},
    }
    return {**base, **overrides}


def reviewed_product_fixture(**overrides):
    base = {
        "name": "Aqua Hydration Bottle",
        "brand_name": "Aqua",
        "description": "Insulated reusable bottle for workouts and travel",
        "category": "fitness",
        "keywords": ["hydration", "water bottle"],
        "features": ["insulated", "zero sugar electrolyte"],
        "use_cases": ["running", "workout"],
        "audience": ["runners"],
        "prohibited_contexts": ["medical claim"],
    }
    return {**base, **overrides}


def test_product_fit_ignores_generic_person_only_evidence():
    generic = product_fit_segment(
        summary="A person is visible.",
        objects=[{"label": "person", "confidence": 0.95}] * 4,
        topics=[{"label": "entertainment"}],
    )

    fit = score_product_segment_fit(reviewed_product_fixture(), generic)

    assert fit["fit_score"] <= 10
    assert fit["evidence_coverage"]["visual_matches"] == 0
    assert fit["confidence"] <= 30


def test_exact_category_and_feature_evidence_outweighs_vague_topic_overlap():
    vague = product_fit_segment(summary="A general lifestyle moment.", topics=[{"label": "travel"}])
    specific = product_fit_segment(
        transcript="This insulated water bottle supports hydration during a running workout.",
        topics=[{"label": "fitness"}],
        objects=[{"label": "bottle", "confidence": 0.88}],
    )

    vague_fit = score_product_segment_fit(reviewed_product_fixture(), vague)
    specific_fit = score_product_segment_fit(reviewed_product_fixture(), specific)

    assert specific_fit["fit_score"] >= vague_fit["fit_score"] + 30
    assert specific_fit["component_breakdown"]["brand_category_relevance"] > 0
    assert specific_fit["evidence_coverage"]["modalities"] >= 2


def test_low_quality_evidence_reduces_confidence_without_forcing_unsuitable_score():
    strong_quality = product_fit_segment(transcript="Hydration for runners during a workout.", topics=[{"label": "fitness"}])
    weak_quality = product_fit_segment(
        transcript="Hydration for runners during a workout.",
        topics=[{"label": "fitness"}],
        transcript_insights={"transcript_confidence": 15, "word_count": 4, "words_per_second": 5},
        visual_evidence={"visual_quality": 0.15},
    )

    strong_fit = score_product_segment_fit(reviewed_product_fixture(), strong_quality)
    weak_fit = score_product_segment_fit(reviewed_product_fixture(), weak_quality)

    assert weak_fit["fit_score"] == strong_fit["fit_score"]
    assert weak_fit["confidence"] < strong_fit["confidence"]
    assert any("Transcript confidence is low" in item for item in weak_fit["limitations"])


def test_product_fit_scoring_is_deterministic():
    segment = product_fit_segment(
        transcript="Aqua hydration bottle for runners.",
        topics=[{"label": "fitness"}],
        objects=[{"label": "bottle", "confidence": 0.8}],
    )

    first = score_product_segment_fit(reviewed_product_fixture(), segment)
    second = score_product_segment_fit(reviewed_product_fixture(), segment)

    assert first == second


def test_product_profile_and_fit_results_are_reused_when_inputs_are_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "product-fit.db")
    monkeypatch.setattr(main, "validate_public_product_url", lambda url: url)
    main.init_db()
    now = main.utc_now()
    with main.connect() as conn:
        conn.execute(
            "insert into videos (id, source_type, title, duration_seconds, status, created_at) values (?, ?, ?, ?, ?, ?)",
            ("video_cache", "upload", "Cache test", 6, "completed", now),
        )
        conn.execute(
            """
            insert into segments
            (id, video_id, start_time, end_time, attention_score, ad_fit_score, drop_risk_score, brand_safety_score,
             label, summary, transcript, transcript_insights, visual_evidence, score_reasons, recommendation,
             ad_slot_score, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "segment_cache", "video_cache", 0, 2, 70, 65, 20, 98, "fitness", "Hydration workout",
                "Aqua hydration bottle for runners", json.dumps({"transcript_confidence": 85, "word_count": 5, "words_per_second": 2}),
                json.dumps({"visual_quality": 0.8}), "[]", "Review placement", 72, now,
            ),
        )
        conn.execute("insert into topics (id, segment_id, label, confidence, created_at) values (?, ?, ?, ?, ?)", ("topic_cache", "segment_cache", "fitness", 0.9, now))
        conn.execute("insert into detected_objects (id, segment_id, label, confidence, created_at) values (?, ?, ?, ?, ?)", ("object_cache", "segment_cache", "bottle", 0.9, now))
        conn.commit()

    profile = reviewed_product_fixture(
        source_url="https://example.com/product",
        canonical_url="https://example.com/product",
        field_sources={"name": "User edited"},
        field_confidence={"name": 100},
        warnings=[],
    )
    saved = main.save_product_profile(profile, {}, "reviewed")
    saved_again = main.save_product_profile(profile, {}, "reviewed")
    first = main.run_product_fit(main.get_product_or_404(saved["id"]), main.get_video_or_404("video_cache"))
    second = main.run_product_fit(main.get_product_or_404(saved["id"]), main.get_video_or_404("video_cache"))

    assert saved_again["id"] == saved["id"]
    assert first["fit_run_id"] == second["fit_run_id"]
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"


def test_product_resolution_cache_hits_and_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "resolution-cache.db")
    monkeypatch.setattr(main, "validate_public_product_url", lambda url: url)
    calls = []

    def fake_extract(url):
        calls.append(url)
        return {
            "source_url": url, "canonical_url": url, "name": "Cached product", "keywords": [],
            "features": [], "use_cases": [], "audience": [], "prohibited_contexts": [],
        }

    monkeypatch.setattr(main, "extract_product_profile", fake_extract)
    main.init_db()
    request = main.ProductResolveRequest(url="https://example.com/product/")

    first = main.resolve_product(request)
    second = main.resolve_product(request)
    main.execute(
        "update product_resolution_cache set fetched_at = ?",
        ("2000-01-01T00:00:00",),
    )
    third = main.resolve_product(request)

    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert third["cache_status"] == "miss"
    assert len(calls) == 2


def test_product_url_rejects_loopback_addresses():
    with pytest.raises(HTTPException, match="Private network"):
        validate_public_product_url("http://127.0.0.1/internal-product")


def test_repeated_person_only_detections_are_preserved_for_visual_evidence():
    detections = {
        1: [{"label": "person", "confidence": 0.91}],
        2: [{"label": "person", "confidence": 0.88}],
        3: [{"label": "person", "confidence": 0.84}],
        4: [{"label": "person", "confidence": 0.82}],
    }

    assert main.normalize_object_detections(detections) == detections


def test_object_normalization_preserves_mixed_detections():
    detections = {
        1: [{"label": "person", "confidence": 0.91}],
        2: [{"label": "person", "confidence": 0.88}, {"label": "bottle", "confidence": 0.74}],
        3: [{"label": "person", "confidence": 0.84}],
    }

    normalized = main.normalize_object_detections(detections)

    assert normalized[1] == [{"label": "person", "confidence": 0.91}]
    assert normalized[2] == [{"label": "person", "confidence": 0.88}, {"label": "bottle", "confidence": 0.74}]
    assert normalized[3] == [{"label": "person", "confidence": 0.84}]


def test_object_tracking_preserves_multiple_people_and_reuses_temporal_tracks():
    detections = {
        1: [
            {"label": "person", "confidence": 0.92, "bbox": [0, 0, 100, 200], "frame_timestamp": 0.5},
            {"label": "person", "confidence": 0.88, "bbox": [180, 0, 280, 200], "frame_timestamp": 0.5},
            {"label": "person", "confidence": 0.90, "bbox": [4, 0, 104, 200], "frame_timestamp": 0.8},
        ]
    }

    tracked = main.finalize_object_detections(detections, detector="yolo_local")[1]

    assert len(tracked) == 3
    first, second = [item for item in tracked if item["frame_timestamp"] == 0.5]
    continuation = next(item for item in tracked if item["frame_timestamp"] == 0.8)
    assert first["track_id"] != second["track_id"]
    assert continuation["track_id"] == first["track_id"]
    assert [item["instance_index"] for item in (first, second)] == [0, 1]


def test_production_ultralytics_inference_requires_license_acknowledgement(monkeypatch):
    monkeypatch.setenv("NEUROAD_ENVIRONMENT", "production")
    monkeypatch.setenv("NEUROAD_OBJECT_DETECTION_ENGINE", "yolo")
    monkeypatch.delenv("NEUROAD_ULTRALYTICS_LICENSE_ACCEPTED", raising=False)

    with pytest.raises(RuntimeError, match="license compliance is acknowledged"):
        main.detect_objects({})


def test_yoloe_failure_uses_yolo26_with_explicit_fallback_provenance(monkeypatch, tmp_path):
    yolo_model = tmp_path / "yolo26s.pt"
    yolo_model.write_bytes(b"test-weight-placeholder")
    monkeypatch.setenv("NEUROAD_ENVIRONMENT", "development")
    monkeypatch.setenv("NEUROAD_OBJECT_DETECTION_ENGINE", "yoloe")
    monkeypatch.setattr(main, "YOLO_MODEL_PATH", yolo_model)
    monkeypatch.setattr(main, "detect_yoloe_objects", lambda _frames: (_ for _ in ()).throw(RuntimeError("GPU unavailable")))
    monkeypatch.setattr(
        main,
        "detect_yolo_objects",
        lambda _frames: {
            1: [
                {
                    "label": "bottle",
                    "confidence": 0.88,
                    "bbox": [10, 20, 90, 180],
                    "frame_timestamp": 0.5,
                }
            ]
        },
    )

    result = main.detect_objects({1: {"path": "unused", "timestamp": 0.5}})

    assert result[1][0]["detector"] == "yolo26_cpu"
    assert result[1][0]["track_id"] == "bottle_001"
    assert main.OBJECT_DETECTION_RUNTIME["degraded"] is False
    assert "GPU unavailable" in main.OBJECT_DETECTION_RUNTIME["fallback_reason"]


def test_signal_payload_adds_six_actionable_metrics_without_removing_legacy_scores():
    segments = [
        {
            "id": "seg_1",
            "start": 0.0,
            "end": 2.0,
            "attention_score": 78,
            "ad_fit_score": 72,
            "drop_risk_score": 22,
            "ad_slot_score": 74,
            "transcript": "How do you stay hydrated? This bottle keeps water cold.",
            "transcript_insights": {
                "word_count": 10,
                "words_per_second": 2.5,
                "transcript_confidence": 88,
                "hook_terms": ["how"],
                "cta_terms": [],
                "repetition_penalty": 0.0,
                "early_hook": True,
                "language": "en",
            },
            "visual_evidence": {
                "sampled_frames": 12,
                "visual_novelty": 0.72,
                "motion": 0.55,
                "motion_acceleration": 0.3,
                "visual_clutter": 0.2,
                "blur_penalty": 0.1,
                "frame_width": 1080,
                "frame_height": 1920,
            },
            "audio_evidence": {"available": True, "audio_energy": 0.62, "silence_duration": 0.1, "silence_ratio": 0.05, "confidence": 0.9},
            "detector_provenance": {"active_detector": "yolo_local", "degraded": False},
            "objects": [{"label": "bottle", "confidence": 0.9, "bbox": [300, 400, 800, 1400], "track_id": "bottle_001"}],
            "topics": [{"label": "fitness", "confidence": 0.82}],
            "strong_signals": ["clear hook", "visible product"],
            "failed_or_weak_signals": [],
            "ad_slot_reasons": ["clear product context"],
        },
        {
            "id": "seg_2",
            "start": 2.0,
            "end": 4.0,
            "attention_score": 42,
            "ad_fit_score": 48,
            "drop_risk_score": 61,
            "ad_slot_score": 45,
            "transcript": "This bottle keeps water cold.",
            "transcript_insights": {
                "word_count": 6,
                "words_per_second": 1.0,
                "transcript_confidence": 76,
                "hook_terms": [],
                "cta_terms": [],
                "repetition_penalty": 0.7,
                "early_hook": False,
                "language": "en",
            },
            "visual_evidence": {
                "sampled_frames": 6,
                "visual_novelty": 0.08,
                "motion": 0.05,
                "motion_acceleration": 0.02,
                "visual_clutter": 0.25,
                "blur_penalty": 0.2,
                "frame_width": 1080,
                "frame_height": 1920,
            },
            "audio_evidence": {"available": True, "audio_energy": 0.2, "silence_duration": 1.6, "silence_ratio": 0.8, "confidence": 0.9},
            "detector_provenance": {"active_detector": "yolo_local", "degraded": False},
            "objects": [{"label": "bottle", "confidence": 0.86, "bbox": [302, 400, 802, 1400], "track_id": "bottle_001"}],
            "topics": [{"label": "fitness", "confidence": 0.78}],
            "strong_signals": [],
            "failed_or_weak_signals": ["long pause", "repeated message"],
            "ad_slot_reasons": [],
        },
    ]

    payload = build_signal_payload(segments)

    assert {metric["key"] for metric in payload["decision_metrics"]} == {
        "content_momentum", "hook_strength", "message_clarity", "creative_friction", "placement_readiness", "evidence_reliability"
    }
    assert all(metric["confidence"] in {"High", "Medium", "Low"} for metric in payload["decision_metrics"])
    assert all(metric["timestamp"]["label"] and metric["next_action"] for metric in payload["decision_metrics"])
    assert segments[0]["attention_score"] == 78
    assert payload["priority_recommendations"][0]["status"] == "Strongest moment"
    assert any("silence" in reason for card in payload["priority_recommendations"] for reason in card["why"])


def test_degraded_detector_cannot_create_ready_placement_recommendation():
    segment = {
        "id": "seg_1", "start": 0.0, "end": 2.0, "attention_score": 90, "ad_fit_score": 90,
        "drop_risk_score": 5, "ad_slot_score": 95, "transcript": "Buy this product now",
        "transcript_insights": {"word_count": 4, "words_per_second": 2, "transcript_confidence": 95, "cta_terms": ["buy"], "hook_terms": [], "repetition_penalty": 0},
        "visual_evidence": {"sampled_frames": 12, "visual_novelty": 0.8, "motion": 0.7, "blur_penalty": 0.05},
        "audio_evidence": {"available": True, "audio_energy": 0.8, "silence_duration": 0, "silence_ratio": 0, "confidence": 0.9},
        "detector_provenance": {"active_detector": "heuristic_fallback", "degraded": True},
        "objects": [{"label": "product", "confidence": 0.4}], "topics": [{"label": "shopping", "confidence": 0.9}],
        "strong_signals": [], "failed_or_weak_signals": [], "ad_slot_reasons": ["high score"],
    }

    payload = build_signal_payload([segment])
    placement = next(metric for metric in payload["decision_metrics"] if metric["key"] == "placement_readiness")

    assert placement["label"] == "Review"
    assert placement["evidence_reliability"] != "High"


def test_versioned_signal_storage_preserves_legacy_analysis_contract(monkeypatch, tmp_path):
    database = tmp_path / "neuroad.db"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"consent-safe-test-media")
    monkeypatch.setattr(main, "DB_PATH", database)
    main.init_db()
    main.execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values ('video_signals', 'upload', null, 'Signal test', '', null, 2, 'completed', ?, null, ?)
        """,
        (str(source), main.utc_now()),
    )
    run_id = main.create_analysis_run("video_signals", source)
    segment = {
        "start": 0.0, "end": 2.0, "attention_score": 80, "ad_fit_score": 75, "drop_risk_score": 20,
        "brand_safety_score": 100, "label": "High attention", "summary": "Clear product moment.",
        "transcript": "See this bottle now", "transcript_insights": {"word_count": 4, "words_per_second": 2, "transcript_confidence": 90, "cta_terms": ["see"], "hook_terms": ["see"], "repetition_penalty": 0},
        "visual_evidence": {"sampled_frames": 12, "visual_novelty": 0.7, "motion": 0.5, "blur_penalty": 0.1, "frame_width": 1080, "frame_height": 1920},
        "audio_evidence": {
            "available": True,
            "audio_energy": 0.6,
            "silence_duration": 0.1,
            "silence_ratio": 0.05,
            "confidence": 0.9,
            "waveform_energy": [0.1, 0.6, 0.3],
        },
        "detector_provenance": {"active_detector": "yolo_local", "degraded": False},
        "score_reasons": ["clear visual movement"], "recommendation": "Keep the product visible.",
        "recommendation_tier": "Strong ad slot", "recommendation_confidence": 85, "evidence_mode": "transcript_visual",
        "strong_signals": ["visible product"], "failed_or_weak_signals": [], "ad_slot_score": 82,
        "ad_slot_reasons": ["clear context"], "is_best_ad_slot": True, "thumbnail_url": None,
        "objects": [{"label": "bottle", "confidence": 0.92, "bbox": [100, 100, 500, 900], "frame_timestamp": 0.5, "track_id": "bottle_001", "detector": "yolo_local", "instance_index": 0}],
        "topics": [{"label": "fitness", "confidence": 0.8}],
        "ad_matches": [{"category": "fitness", "ad_fit_score": 75, "reason": "product context", "confidence": 80}],
        "ocr_evidence": {"available": False}, "social_evidence": {"available": False},
    }

    main.write_analysis("video_signals", [segment], analysis_run_id=run_id)
    payload = main.build_analysis_payload(main.query_one("select * from videos where id = 'video_signals'"))
    lazy_evidence = main.get_segment_evidence("video_signals", payload["segments"][0]["id"])

    assert main.query_one("select count(*) as count from object_tracks where analysis_run_id = ?", (run_id,))["count"] == 1
    assert main.query_one("select count(*) as count from decision_metrics where analysis_run_id = ?", (run_id,))["count"] == 6
    assert main.query_one("select count(*) as count from signal_samples where analysis_run_id = ?", (run_id,))["count"] > 0
    assert payload["segments"][0]["attention_score"] == 80
    assert "waveform_energy" not in payload["segments"][0]["audio_evidence"]
    assert lazy_evidence["audio"]["waveform_energy"] == [0.1, 0.6, 0.3]
    assert len(payload["decision_metrics"]) == 6
    assert payload["analysis_version"] == "content-signals-v1"


def test_extractor_cache_is_versioned_by_source_and_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "cache.db")
    monkeypatch.setenv("NEUROAD_ENABLE_EXTRACTOR_CACHE", "1")
    main.init_db()
    configuration = {"model": "multilingual-small", "threshold": 0.5}
    payload = {"evidence": {1: {"available": True, "confidence": 0.88}}}

    main.write_extractor_cache("source-a", "audio_speech", "v1", configuration, payload)

    cached = main.read_extractor_cache("source-a", "audio_speech", "v1", configuration)
    changed = main.read_extractor_cache(
        "source-a", "audio_speech", "v1", {**configuration, "threshold": 0.6}
    )
    different_source = main.read_extractor_cache("source-b", "audio_speech", "v1", configuration)

    assert cached == {"evidence": {"1": {"available": True, "confidence": 0.88}}}
    assert changed is None
    assert different_source is None
