from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from statistics import mean, pstdev
from typing import Any, Iterable


ANALYSIS_SCHEMA_VERSION = "content-signals-v1"
PRODUCT_WORDS = {
    "product",
    "brand",
    "bottle",
    "box",
    "packet",
    "packaging",
    "sachet",
    "tube",
    "jar",
    "can",
    "cosmetic",
    "clothing",
    "electronics",
    "food",
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def average(values: Iterable[float | int | None], default: float = 0.0) -> float:
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return mean(usable) if usable else default


def confidence_band(value: float | int) -> str:
    normalized = float(value) / 100 if float(value) > 1 else float(value)
    if normalized >= 0.75:
        return "High"
    if normalized >= 0.48:
        return "Medium"
    return "Low"


def timestamp_label(start: float, end: float | None = None) -> str:
    def format_value(value: float) -> str:
        minutes = int(max(0.0, value) // 60)
        seconds = int(max(0.0, value) % 60)
        return f"{minutes:02d}:{seconds:02d}"

    return format_value(start) if end is None else f"{format_value(start)}–{format_value(end)}"


def distinct_instances(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(objects):
        key = str(item.get("track_id") or f"{item.get('label', 'object')}:{item.get('instance_index', index)}")
        if key not in output or float(item.get("confidence", 0.0) or 0.0) > float(
            output[key].get("confidence", 0.0) or 0.0
        ):
            output[key] = item
    return list(output.values())


def subject_geometry(segment: dict[str, Any], instances: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    visual = segment.get("visual_evidence", {})
    width = float(visual.get("frame_width", 0.0) or 0.0)
    height = float(visual.get("frame_height", 0.0) or 0.0)
    if width <= 0 or height <= 0:
        return None, None
    prominence: list[float] = []
    centrality: list[float] = []
    for item in instances:
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [float(value) for value in bbox]
        prominence.append(clamp(max(0.0, x2 - x1) * max(0.0, y2 - y1) / (width * height)))
        center_x = (x1 + x2) / 2 / width
        center_y = (y1 + y2) / 2 / height
        centrality.append(clamp(1 - math.hypot(center_x - 0.5, center_y - 0.5) / 0.71))
    return (max(prominence) if prominence else None, max(centrality) if centrality else None)


def lexical_novelty(current: str, previous: str) -> float | None:
    current_words = set(re.findall(r"\w{3,}", current.lower()))
    previous_words = set(re.findall(r"\w{3,}", previous.lower()))
    if not current_words:
        return None
    if not previous_words:
        return 1.0
    return clamp(1 - len(current_words & previous_words) / max(1, len(current_words | previous_words)))


def segment_reliability(segment: dict[str, Any]) -> tuple[float, list[str]]:
    visual = segment.get("visual_evidence", {})
    transcript = segment.get("transcript_insights", {})
    audio = segment.get("audio_evidence", {})
    ocr = segment.get("ocr_evidence", {})
    detector = segment.get("detector_provenance", {})
    components: list[float] = []
    reasons: list[str] = []
    sampled_frames = int(visual.get("sampled_frames", 0) or 0)
    if sampled_frames:
        components.append(clamp(sampled_frames / 10))
        reasons.append(f"{sampled_frames} visual samples")
    transcript_confidence = float(transcript.get("transcript_confidence", 0) or 0) / 100
    if transcript.get("word_count", 0):
        components.append(transcript_confidence)
        reasons.append(f"transcript confidence {int(round(transcript_confidence * 100))}%")
    if audio.get("available"):
        components.append(float(audio.get("confidence", 0.75) or 0.75))
        reasons.append("audio waveform available")
    if detector.get("active_detector"):
        detector_quality = 0.82 if not detector.get("degraded") else 0.34
        components.append(detector_quality)
        reasons.append(str(detector.get("active_detector")).replace("_", " "))
    if ocr.get("available") and ocr.get("texts"):
        components.append(float(ocr.get("confidence", 0.0) or 0.0))
        reasons.append("OCR text and boxes available")
    if not components:
        return 0.15, ["insufficient extractor evidence"]
    coverage_bonus = min(0.12, len(components) * 0.03)
    reliability = clamp(average(components) + coverage_bonus)
    if detector.get("degraded"):
        reliability = min(reliability, 0.72)
        reasons.append("object detector is degraded; product claims require review")
    return reliability, reasons


def build_segment_signal_summary(
    segment: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    visual = segment.get("visual_evidence", {})
    transcript = segment.get("transcript_insights", {})
    audio = dict(segment.get("audio_evidence", {}) or {})
    advanced_social = dict(segment.get("social_evidence", {}) or {})
    advanced_narrative = dict(segment.get("narrative_evidence", {}) or {})
    ocr = dict(segment.get("ocr_evidence", {}) or {})
    instances = distinct_instances(segment.get("objects", []))
    previous_instances = distinct_instances(previous.get("objects", [])) if previous else []
    prominence, centrality = subject_geometry(segment, instances)
    current_tracks = {str(item.get("track_id")) for item in instances if item.get("track_id")}
    previous_tracks = {str(item.get("track_id")) for item in previous_instances if item.get("track_id")}
    new_instances = [item for item in instances if item.get("track_id") and str(item.get("track_id")) not in previous_tracks]
    disappeared = previous_tracks - current_tracks
    people = [item for item in instances if str(item.get("label", "")).lower() == "person"]
    person_observations = [
        item for item in segment.get("objects", []) if str(item.get("label", "")).lower() == "person"
    ]
    sampled_frames = max(1, int(visual.get("sampled_frames", 0) or 0))
    person_persistence = clamp(
        len({round(float(item.get("frame_timestamp", 0.0) or 0.0), 2) for item in person_observations}) / sampled_frames
    )
    previous_text = str(previous.get("transcript", "")) if previous else ""
    lexical_novelty_value = lexical_novelty(str(segment.get("transcript", "")), previous_text)
    novelty = advanced_narrative.get("semantic_novelty")
    if novelty is None:
        novelty = lexical_novelty_value
    duration = max(0.1, float(segment.get("end", 0)) - float(segment.get("start", 0)))
    word_count = int(transcript.get("word_count", 0) or 0)
    words_per_second = float(transcript.get("words_per_second", 0.0) or 0.0)
    topic = (segment.get("topics") or [{}])[0]
    previous_topic = ((previous or {}).get("topics") or [{}])[0]
    topic_transition = bool(
        previous
        and (
            topic.get("label") != previous_topic.get("label")
            or float(advanced_narrative.get("topic_transition_strength", 0.0) or 0.0) >= 0.55
        )
    )
    product_mentions = sorted(
        {
            str(item.get("label"))
            for item in instances
            if any(term in str(item.get("label", "")).lower() for term in PRODUCT_WORDS)
        }
    )
    transcript_text = str(segment.get("transcript", ""))
    question = "?" in transcript_text or bool(re.search(r"\b(why|how|what|when|where|who|kya|kaise|kyun)\b", transcript_text, re.I))
    reliability, reliability_reasons = segment_reliability(segment)

    visual_findings: list[str] = []
    if new_instances:
        visual_findings.append(f"A new {str(new_instances[0].get('label', 'visual element'))} appears here.")
    if float(visual.get("visual_novelty", 0) or 0) < 0.2 and float(visual.get("motion", 0) or 0) < 0.18:
        visual_findings.append("This scene stays visually similar for too long.")
    if prominence is not None and prominence >= 0.12 and centrality is not None and centrality >= 0.65:
        visual_findings.append("The main subject is clear and central here.")
    if float(visual.get("blur_penalty", 0) or 0) >= 0.55:
        visual_findings.append("Image quality is soft or difficult to inspect on mobile.")
    if ocr.get("mobile_readable") is False:
        visual_findings.append("Text is difficult to read on mobile.")

    audio_findings: list[str] = []
    silence_duration = audio.get("silence_duration")
    if silence_duration is not None and float(silence_duration) >= 1.5:
        audio_findings.append(f"Energy drops for {float(silence_duration):.1f} seconds.")
    if words_per_second > 4:
        audio_findings.append("Speech becomes too fast to follow.")
    if audio.get("sudden_audio_discontinuity") is not None and float(audio["sudden_audio_discontinuity"]) >= 0.55:
        audio_findings.append("A sudden audio change may interrupt the transition.")

    narrative_findings: list[str] = []
    if topic_transition:
        narrative_findings.append(f"The topic shifts to {topic.get('label', 'a new idea')} here.")
    repetition_level = max(
        float(transcript.get("repetition_penalty", 0) or 0),
        float(advanced_narrative.get("semantic_repetition", 0) or 0),
    )
    if repetition_level >= 0.65:
        narrative_findings.append("This point repeats the earlier message.")
    if question:
        narrative_findings.append("A clear question creates curiosity here.")
    if transcript.get("cta_terms"):
        narrative_findings.append("A clear call to action appears here.")

    visual_change = clamp(
        float(visual.get("visual_novelty", 0) or 0) * 0.45
        + float(visual.get("motion", 0) or 0) * 0.35
        + float(visual.get("motion_acceleration", 0) or 0) * 0.20
    )
    social_confidence = clamp(
        float(advanced_social.get("confidence", 0.0) or 0.0)
        if advanced_social.get("available")
        else reliability * (0.75 if people else 0.55)
    )
    mouth_activity = advanced_social.get("mouth_activity")
    likely_speaking = bool(people and word_count > 0 and (mouth_activity is None or float(mouth_activity) >= 0.002))
    return {
        "visual": {
            "visual_change_intensity": round(visual_change, 3),
            "motion_level": visual.get("motion"),
            "motion_acceleration": visual.get("motion_acceleration"),
            "scene_change_strength": visual.get("visual_novelty"),
            "scene_shot_change_frequency": round(float(visual.get("shot_change_count", 0) or 0) / duration, 3),
            "scene_boundaries": visual.get("scene_boundaries", []),
            "shot_duration": round(duration / (int(visual.get("shot_change_count", 0) or 0) + 1), 3),
            "pacing_variation": visual.get("pacing_variation"),
            "camera_movement": visual.get("camera_movement"),
            "subject_prominence": round(prominence, 3) if prominence is not None else None,
            "centre_of_frame_focus": round(centrality, 3) if centrality is not None else None,
            "object_appearance_count": len(new_instances),
            "object_disappearance_count": len(disappeared),
            "text_prominence": ocr.get("text_prominence"),
            "text_readability": ocr.get("text_readability"),
            "mobile_text_readable": ocr.get("mobile_readable"),
            "ocr_text": ocr.get("texts", []),
            "brightness": visual.get("brightness"),
            "contrast": visual.get("contrast"),
            "saturation": visual.get("saturation"),
            "visual_clutter": visual.get("visual_clutter"),
            "subject_background_separation": round(clamp((prominence or 0) * 2 + (1 - float(visual.get("visual_clutter", 0) or 0)) * 0.35), 3)
            if prominence is not None
            else None,
            "new_visual_element": bool(new_instances),
            "quality_warning": bool(float(visual.get("blur_penalty", 0) or 0) >= 0.5 or float(visual.get("brightness", 0.5) or 0.5) < 0.18),
            "findings": visual_findings,
            "confidence": round(reliability, 3),
        },
        "audio": {
            **audio,
            "speech_to_music_ratio": None,
            "speech_pace_wps": round(words_per_second, 2),
            "pitch_variation": audio.get("pitch_variation"),
            "tempo_bpm": audio.get("tempo_bpm"),
            "audio_video_sync_strength": None,
            "speaker_change": None,
            "findings": audio_findings,
            "confidence": round(float(audio.get("confidence", 0.0) or 0.0), 3),
        },
        "narrative": {
            **advanced_narrative,
            "topic": topic.get("label"),
            "topic_clarity": round(float(topic.get("confidence", 0.0) or 0.0), 3),
            "topic_introduction": bool(not previous or topic_transition),
            "topic_transition": topic_transition,
            "information_density_wps": round(word_count / duration, 2),
            "semantic_novelty": round(novelty, 3) if novelty is not None else None,
            "repetition_level": round(repetition_level, 3),
            "question_pattern": question,
            "answer_pattern": bool(previous and "?" in previous_text and word_count > 0),
            "hook_language": transcript.get("hook_terms", []),
            "cta_clarity": "clear" if transcript.get("cta_terms") else "missing",
            "product_brand_mentions": product_mentions,
            "named_entities": advanced_narrative.get("named_entities")
            or sorted(set(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", transcript_text)))[:8],
            "narrative_stage": infer_narrative_stage(segment),
            "language": transcript.get("language"),
            "language_probability": transcript.get("language_probability"),
            "transcript_confidence": transcript.get("transcript_confidence"),
            "findings": narrative_findings,
            "confidence": round(float(transcript.get("transcript_confidence", 0) or 0) / 100, 3),
        },
        "social": {
            **advanced_social,
            "face_prominence": advanced_social.get("face_prominence", round(prominence, 3) if people and prominence is not None else None),
            "face_persistence": advanced_social.get("face_persistence", round(person_persistence, 3) if people else 0.0),
            "direct_to_camera_presence": advanced_social.get("direct_to_camera_presence"),
            "head_movement": advanced_social.get("head_movement"),
            "mouth_activity_likely_speaking": likely_speaking,
            "eye_region_movement": advanced_social.get("eye_region_movement"),
            "facial_behaviour_change_rate": advanced_social.get("facial_behaviour_change_rate"),
            "people_on_screen": max(len(people), int(advanced_social.get("people_on_screen", 0) or 0)),
            "social_interaction_density": round(clamp((len(people) - 1) * 0.45 + (0.25 if word_count else 0)), 3),
            "speaker_listener_alternation": None,
            "face_voice_alignment": round(clamp(person_persistence * 0.65 + 0.25), 3) if likely_speaking else None,
            "findings": social_findings(
                people,
                float(advanced_social.get("face_persistence", person_persistence) or 0),
                advanced_social.get("direct_to_camera_presence"),
            ),
            "confidence": round(social_confidence, 3),
        },
        "reliability": {
            "score": round(reliability, 3),
            "band": confidence_band(reliability),
            "reasons": reliability_reasons,
        },
    }


def social_findings(
    people: list[dict[str, Any]], persistence: float, direct_to_camera: float | None = None
) -> list[str]:
    if direct_to_camera is not None and direct_to_camera >= 0.65:
        return ["Direct-to-camera delivery is strongest here."]
    if len(people) >= 2:
        return ["Two-person interaction increases conversational variety."]
    if len(people) == 1 and persistence >= 0.7:
        return ["A face remains on screen; add visual change if the delivery feels static."]
    return []


def infer_narrative_stage(segment: dict[str, Any]) -> str:
    text = str(segment.get("transcript", "")).lower()
    insights = segment.get("transcript_insights", {})
    if insights.get("cta_terms"):
        return "CTA"
    if any(term in text for term in ("proof", "result", "tested", "because", "example")):
        return "proof"
    if any(term in text for term in ("benefit", "helps", "solution", "value", "so you can")):
        return "value"
    if any(term in text for term in ("problem", "struggle", "issue", "but", "challenge")):
        return "problem"
    return "setup"


def enrich_segments_with_signals(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous: dict[str, Any] | None = None
    for segment in segments:
        summary = build_segment_signal_summary(segment, previous)
        segment["signal_summary"] = summary
        segment["narrative_evidence"] = summary["narrative"]
        segment["social_evidence"] = summary["social"]
        previous = segment
    lip_audio_pairs = [
        (
            float(segment.get("signal_summary", {}).get("social", {}).get("mouth_activity", 0.0) or 0.0),
            float(segment.get("signal_summary", {}).get("audio", {}).get("audio_energy", 0.0) or 0.0),
        )
        for segment in segments
        if segment.get("signal_summary", {}).get("social", {}).get("available")
        and segment.get("signal_summary", {}).get("social", {}).get("people_on_screen") == 1
        and segment.get("signal_summary", {}).get("audio", {}).get("available")
    ]
    sync_strength = pearson_strength(lip_audio_pairs)
    if sync_strength is not None:
        for segment in segments:
            social = segment.get("signal_summary", {}).get("social", {})
            if social.get("available") and social.get("people_on_screen") == 1:
                segment["signal_summary"]["audio"]["audio_video_sync_strength"] = round(sync_strength, 3)
    return segments


def pearson_strength(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    first = [item[0] for item in pairs]
    second = [item[1] for item in pairs]
    first_mean, second_mean = average(first), average(second)
    numerator = sum((x - first_mean) * (y - second_mean) for x, y in pairs)
    denominator = math.sqrt(
        sum((x - first_mean) ** 2 for x in first) * sum((y - second_mean) ** 2 for y in second)
    )
    if denominator <= 1e-9:
        return None
    return clamp((numerator / denominator + 1) / 2)


def metric_card(
    key: str,
    name: str,
    status: str,
    score: float,
    confidence: float,
    segment: dict[str, Any],
    reasons: list[str],
    next_action: str,
) -> dict[str, Any]:
    start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
    reliability = segment.get("signal_summary", {}).get("reliability", {})
    return {
        "key": key,
        "name": name,
        "label": status,
        "score": int(round(clamp(score) * 100)),
        "confidence": confidence_band(confidence),
        "confidence_score": int(round(clamp(confidence) * 100)),
        "timestamp": {"start": start, "end": end, "label": timestamp_label(start, end)},
        "reasons": reasons[:4],
        "next_action": next_action,
        "evidence_reliability": reliability.get("band", confidence_band(confidence)),
    }


def build_decision_metrics(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []
    signals = [segment.get("signal_summary", {}) for segment in segments]
    momentum_values = [
        average(
            [
                signal.get("visual", {}).get("visual_change_intensity"),
                signal.get("audio", {}).get("audio_energy"),
                signal.get("narrative", {}).get("semantic_novelty"),
            ],
            0.25,
        )
        for signal in signals
    ]
    momentum = clamp(average(momentum_values) * 0.75 + (1 - min(1.0, pstdev(momentum_values) if len(momentum_values) > 1 else 0)) * 0.25)
    weakest_momentum = segments[min(range(len(segments)), key=lambda index: momentum_values[index])]
    momentum_label = "Strong" if momentum >= 0.67 else "Uneven" if momentum >= 0.43 else "Needs improvement"

    hook_segments = [segment for segment in segments if float(segment.get("start", 0)) < 5] or [segments[0]]
    hook_segment = max(
        hook_segments,
        key=lambda item: (
            (1 if item.get("transcript_insights", {}).get("early_hook") else 0)
            + float(item.get("signal_summary", {}).get("visual", {}).get("visual_change_intensity", 0) or 0)
        ),
    )
    hook_score = clamp(
        (0.48 if hook_segment.get("transcript_insights", {}).get("early_hook") else 0.08)
        + float(hook_segment.get("signal_summary", {}).get("visual", {}).get("visual_change_intensity", 0) or 0) * 0.34
        + (0.18 if hook_segment.get("signal_summary", {}).get("narrative", {}).get("question_pattern") else 0)
    )

    clarity_values = [
        average(
            [
                segment.get("signal_summary", {}).get("narrative", {}).get("topic_clarity"),
                float(segment.get("transcript_insights", {}).get("transcript_confidence", 0) or 0) / 100,
            ],
            0.2,
        )
        for segment in segments
    ]
    clarity = average(clarity_values)
    clarity_segment = segments[max(range(len(segments)), key=lambda index: clarity_values[index])]
    clarity_label = "Clear" if clarity >= 0.68 else "Mixed" if clarity >= 0.42 else "Unclear"

    friction_values = [
        clamp(
            float(segment.get("drop_risk_score", 0) or 0) / 100 * 0.45
            + float(segment.get("transcript_insights", {}).get("repetition_penalty", 0) or 0) * 0.20
            + float(segment.get("audio_evidence", {}).get("silence_ratio", 0) or 0) * 0.20
            + float(segment.get("visual_evidence", {}).get("visual_clutter", 0) or 0) * 0.15
        )
        for segment in segments
    ]
    friction = average(friction_values)
    friction_segment = segments[max(range(len(segments)), key=lambda index: friction_values[index])]
    friction_label = "Low" if friction < 0.32 else "Medium" if friction < 0.58 else "High"

    placement_segment = max(segments, key=lambda item: float(item.get("ad_slot_score", 0) or 0))
    placement_score = float(placement_segment.get("ad_slot_score", 0) or 0) / 100
    placement_reliability = float(
        placement_segment.get("signal_summary", {}).get("reliability", {}).get("score", 0.0) or 0.0
    )
    placement_detector_degraded = bool(placement_segment.get("detector_provenance", {}).get("degraded"))
    placement_label = (
        "Ready"
        if placement_score >= 0.7 and placement_reliability >= 0.7 and not placement_detector_degraded
        else "Review"
        if placement_score >= 0.42
        else "Avoid"
    )

    reliability_values = [float(signal.get("reliability", {}).get("score", 0.0) or 0.0) for signal in signals]
    reliability_score = average(reliability_values)
    reliability_segment = segments[min(range(len(segments)), key=lambda index: reliability_values[index])]
    reliability_label = confidence_band(reliability_score)

    return [
        metric_card(
            "content_momentum",
            "Content momentum",
            momentum_label,
            momentum,
            average(reliability_values),
            weakest_momentum,
            ["visual, audio, and narrative movement are combined", f"lowest momentum is {timestamp_label(weakest_momentum['start'], weakest_momentum['end'])}"],
            "Add a visual, spoken, or narrative change at the weakest timestamp." if momentum_label != "Strong" else "Reuse this rhythm in future edits.",
        ),
        metric_card(
            "hook_strength",
            "Hook strength",
            "Strong" if hook_score >= 0.62 else "Improve",
            hook_score,
            float(hook_segment.get("signal_summary", {}).get("reliability", {}).get("score", 0)),
            hook_segment,
            ["opening language, questions, and visual change were checked", "the hook window is limited to the first five seconds"],
            "Lead with the clearest promise, question, product, or visual result in the first three seconds." if hook_score < 0.62 else "Keep this opening and test a shorter variant.",
        ),
        metric_card(
            "message_clarity",
            "Message clarity",
            clarity_label,
            clarity,
            float(clarity_segment.get("signal_summary", {}).get("reliability", {}).get("score", 0)),
            clarity_segment,
            ["topic consistency and transcript clarity were combined", f"the clearest topic evidence appears at {timestamp_label(clarity_segment['start'])}"],
            "State the topic and viewer benefit earlier, then remove competing points." if clarity_label != "Clear" else "Keep the topic phrasing consistent through the CTA.",
        ),
        metric_card(
            "creative_friction",
            "Creative friction",
            friction_label,
            1 - friction,
            float(friction_segment.get("signal_summary", {}).get("reliability", {}).get("score", 0)),
            friction_segment,
            ["drop risk, silence, repetition, and clutter were combined", f"the strongest interruption appears at {timestamp_label(friction_segment['start'], friction_segment['end'])}"],
            "Shorten the pause or repeated line and introduce a clearer visual transition." if friction_label != "Low" else "No urgent pacing repair is indicated.",
        ),
        metric_card(
            "placement_readiness",
            "Placement readiness",
            placement_label,
            placement_score,
            placement_reliability,
            placement_segment,
            list(placement_segment.get("ad_slot_reasons", [])) or ["attention, safety, context, and interruption risk were checked"],
            "Use this moment only after reviewing its evidence." if placement_label == "Review" else "Place the CTA or product immediately after the established value." if placement_label == "Ready" else "Choose another timestamp or improve context before insertion.",
        ),
        metric_card(
            "evidence_reliability",
            "Evidence reliability",
            reliability_label,
            reliability_score,
            reliability_score,
            reliability_segment,
            ["confidence is separate from the content score", "coverage, extractor health, and cross-modal evidence are considered"],
            "Review the raw evidence before acting on low-confidence recommendations." if reliability_label != "High" else "Recommendations have sufficient evidence for creator review.",
        ),
    ]


def segment_recommendation_card(segment: dict[str, Any]) -> dict[str, Any]:
    signal = segment.get("signal_summary", {})
    visual = signal.get("visual", {})
    audio = signal.get("audio", {})
    narrative = signal.get("narrative", {})
    issues: list[str] = []
    actions: list[str] = []
    if float(visual.get("visual_change_intensity", 0) or 0) < 0.25:
        issues.append("low visual change")
        actions.append("add a product close-up or new visual")
    if float(audio.get("silence_duration", 0) or 0) >= 1.5:
        issues.append(f"{float(audio['silence_duration']):.1f} seconds of silence")
        actions.append("shorten the pause")
    if float(narrative.get("repetition_level", 0) or 0) >= 0.45:
        issues.append("repeated message")
        actions.append("replace the repeated line with the key benefit")
    if not narrative.get("product_brand_mentions"):
        issues.append("product is not clearly evidenced")
        actions.append("show or name the product")
    if float(segment.get("drop_risk_score", 0) or 0) >= 60:
        issues.append("high drop risk")
    if not actions:
        actions.append("keep this moment and reuse its pacing pattern")
    reliability = signal.get("reliability", {})
    impact = clamp(
        float(segment.get("drop_risk_score", 0) or 0) / 100 * 0.55
        + len(issues) / 5 * 0.30
        + (1 - float(segment.get("attention_score", 0) or 0) / 100) * 0.15
    )
    return {
        "segment_id": segment.get("id"),
        "timestamp": {
            "start": segment.get("start", 0),
            "end": segment.get("end", 0),
            "label": timestamp_label(float(segment.get("start", 0)), float(segment.get("end", 0))),
        },
        "status": "Improve before publishing" if issues else "Strong moment",
        "why": issues[:4] or ["clear movement and message evidence"],
        "suggested_action": "; ".join(actions[:3]).capitalize() + ".",
        "evidence_reliability": reliability.get("band", "Low"),
        "impact_score": int(round(impact * 100)),
    }


def build_priority_recommendations(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = [segment_recommendation_card(segment) for segment in segments]
    fixes = sorted((card for card in cards if card["status"] != "Strong moment"), key=lambda card: card["impact_score"], reverse=True)[:4]
    strongest_segment = max(
        segments,
        key=lambda item: float(item.get("attention_score", 0) or 0) + float(item.get("ad_slot_score", 0) or 0),
        default=None,
    )
    strongest = segment_recommendation_card(strongest_segment) if strongest_segment else None
    if strongest:
        strongest["status"] = "Strongest moment"
        strongest["why"] = list(strongest_segment.get("strong_signals", []))[:4] or ["best combined attention and placement evidence"]
        strongest["suggested_action"] = "Keep this moment and reuse its strongest creative pattern."
    return ([strongest] if strongest else []) + fixes


def build_timeline_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for segment in segments:
        signal = segment.get("signal_summary", {})
        points.append(
            {
                "segment_id": segment.get("id"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "label": timestamp_label(float(segment.get("start", 0)), float(segment.get("end", 0))),
                "visual": signal.get("visual", {}),
                "audio": signal.get("audio", {}),
                "narrative": signal.get("narrative", {}),
                "social": signal.get("social", {}),
                "reliability": signal.get("reliability", {}),
            }
        )
    return {
        "resolution": "segment",
        "families": ["visual", "audio", "narrative", "social"],
        "points": points,
    }


def signal_availability(segments: list[dict[str, Any]]) -> dict[str, Any]:
    has_audio = any(segment.get("audio_evidence", {}).get("available") for segment in segments)
    has_transcript = any(segment.get("transcript_insights", {}).get("word_count", 0) for segment in segments)
    detector_names = sorted(
        {
            str(segment.get("detector_provenance", {}).get("active_detector"))
            for segment in segments
            if segment.get("detector_provenance", {}).get("active_detector")
        }
    )
    degraded = any(segment.get("detector_provenance", {}).get("degraded") for segment in segments)
    has_face_landmarks = any(
        segment.get("social_evidence", {}).get("extractor") == "mediapipe_face_landmarker"
        and segment.get("social_evidence", {}).get("available")
        for segment in segments
    )
    has_ocr = any(segment.get("ocr_evidence", {}).get("available") for segment in segments)
    return {
        "visual": {"status": "available" if segments else "unavailable", "extractors": ["opencv_shared_decode"]},
        "objects": {"status": "degraded" if degraded else "available", "extractors": detector_names},
        "audio": {"status": "available" if has_audio else "unavailable", "extractors": ["waveform"] if has_audio else []},
        "narrative": {"status": "available" if has_transcript else "unavailable", "extractors": ["faster_whisper", "rules"] if has_transcript else []},
        "social": {
            "status": "available" if has_face_landmarks else "partial",
            "extractors": ["anonymous_person_tracks"] + (["mediapipe_face_landmarker"] if has_face_landmarks else []),
            "missing": [] if has_face_landmarks else ["mediapipe_face_landmarker"],
        },
        "ocr": {
            "status": "available" if has_ocr else "unavailable",
            "extractors": ["paddleocr_ppocrv5"] if has_ocr else [],
            "missing": [] if has_ocr else ["paddleocr"],
        },
    }


def build_signal_payload(segments: list[dict[str, Any]]) -> dict[str, Any]:
    enrich_segments_with_signals(segments)
    return {
        "analysis_version": ANALYSIS_SCHEMA_VERSION,
        "decision_metrics": build_decision_metrics(segments),
        "priority_recommendations": build_priority_recommendations(segments),
        "timeline_summary": build_timeline_summary(segments),
        "signal_availability": signal_availability(segments),
        "review_summary": {"state": "unreviewed", "reviewed_segments": 0, "total_segments": len(segments)},
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
