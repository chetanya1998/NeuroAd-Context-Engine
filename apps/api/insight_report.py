from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRAND_PROSPECT_DISCLAIMER = (
    "Brand prospects are not sponsored recommendations. They were detected from the uploaded video "
    "by the NeuroAd Insight Generator and should be independently verified."
)

VIDEO_PROMPT_VERSION = "video-insight-v1"
COMPARISON_PROMPT_VERSION = "comparison-insight-v1"

COMMON_SCHEMA = """
Return only a JSON object with:
{
  "executive_summary": "2-4 concise sentences",
  "content_profile": {
    "themes": ["up to 6"],
    "audience_signals": ["up to 6"],
    "tone": ["up to 4"],
    "campaign_intents": ["up to 5"]
  },
  "keywords": [
    {"term":"", "type":"content|audience|advertising|brand", "confidence":0, "evidence_refs":["segment id"]}
  ],
  "ad_categories": [
    {"category":"", "contextual_fit_score":0, "confidence":0, "rationale":"", "evidence_refs":["segment id"]}
  ],
  "brand_prospects": [
    {"brand":"", "category":"", "contextual_fit_score":0, "confidence":0, "why_fit":"",
     "activation_idea":"", "risks":[""], "evidence_refs":["segment id"]}
  ],
  "brand_safety": {"summary":"", "findings":[""]},
  "creative_recommendations": [""],
  "limitations": [""]
}
""".strip()

VIDEO_SYSTEM_PROMPT = f"""
You are the NeuroAd Insight Generator. Synthesize only the supplied deterministic video evidence.
Do not invent transcript, objects, OCR text, scores, timestamps, or evidence identifiers.
Brand names may be proposed from general knowledge, but they are unverified prospects rather than partnerships.
Never reveal hidden reasoning. Return JSON only.
{COMMON_SCHEMA}
Also include:
"placement_opportunities": [
  {{"segment_id":"", "start":0, "end":0, "score":0, "format":"", "suggested_duration":"",
    "messaging_angle":"", "rationale":"", "evidence_refs":["segment id"]}}
],
"avoidance_zones": [
  {{"segment_id":"", "start":0, "end":0, "reason":""}}
]
Limits: 15 keywords, 5 ad categories, 8 brand prospects, 8 placement opportunities.
""".strip()

COMPARISON_SYSTEM_PROMPT = f"""
You are the NeuroAd Insight Generator. Compare only the supplied deterministic evidence for up to five videos.
Do not invent transcript, objects, OCR text, scores, timestamps, video identifiers, or evidence identifiers.
Brand names may be proposed from general knowledge, but they are unverified prospects rather than partnerships.
Never reveal hidden reasoning. Return JSON only.
{COMMON_SCHEMA}
Also include:
"cross_video_insights": {{"shared_themes":[""], "keyword_overlap":[""], "important_differences":[""]}},
"video_rankings": [
  {{"video_id":"", "campaign_objective":"", "rank":1, "rationale":""}}
],
"brand_video_matrix": [
  {{"brand":"", "video_id":"", "contextual_fit_score":0, "rationale":"", "evidence_refs":["segment id"]}}
],
"comparative_placements": [
  {{"video_id":"", "segment_id":"", "start":0, "end":0, "score":0, "rationale":""}}
]
Limits: 15 keywords, 5 ad categories, 8 brand prospects, 20 matrix rows, 12 comparative placements.
""".strip()


def _text(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _score(value: Any) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _strings(value: Any, limit: int, item_limit: int = 260) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item, item_limit)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _valid_refs(value: Any, valid_segment_ids: set[str], limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        ref = _text(item, 120)
        if ref in valid_segment_ids and ref not in result:
            result.append(ref)
        if len(result) >= limit:
            break
    return result


def _dedupe_records(records: Any, key_name: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    result = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _text(record.get(key_name), 160)
        normalized = key.casefold()
        if not key or normalized in seen:
            continue
        seen.add(normalized)
        result.append({**record, key_name: key})
        if len(result) >= limit:
            break
    return result


def normalize_report(
    raw: dict[str, Any],
    *,
    report_type: str,
    report_id: str,
    target_id: str,
    fingerprint: str,
    model: str,
    valid_segments: dict[str, dict[str, Any]],
    valid_video_ids: set[str],
) -> dict[str, Any]:
    valid_segment_ids = set(valid_segments)
    content_profile = raw.get("content_profile") if isinstance(raw.get("content_profile"), dict) else {}

    keywords = []
    for item in _dedupe_records(raw.get("keywords"), "term", 15):
        refs = _valid_refs(item.get("evidence_refs"), valid_segment_ids)
        if not refs:
            continue
        keywords.append(
            {
                "term": item["term"],
                "type": _text(item.get("type"), 40) or "content",
                "confidence": _score(item.get("confidence")),
                "evidence_refs": refs,
            }
        )

    categories = []
    for item in _dedupe_records(raw.get("ad_categories"), "category", 5):
        refs = _valid_refs(item.get("evidence_refs"), valid_segment_ids)
        if not refs:
            continue
        categories.append(
            {
                "category": item["category"],
                "contextual_fit_score": _score(item.get("contextual_fit_score")),
                "confidence": _score(item.get("confidence")),
                "rationale": _text(item.get("rationale"), 600),
                "evidence_refs": refs,
            }
        )

    brands = []
    for item in _dedupe_records(raw.get("brand_prospects"), "brand", 8):
        refs = _valid_refs(item.get("evidence_refs"), valid_segment_ids)
        brands.append(
            {
                "brand": item["brand"],
                "category": _text(item.get("category"), 160),
                "contextual_fit_score": _score(item.get("contextual_fit_score")),
                "confidence": _score(item.get("confidence")),
                "why_fit": _text(item.get("why_fit"), 700),
                "activation_idea": _text(item.get("activation_idea"), 700),
                "risks": _strings(item.get("risks"), 5),
                "evidence_refs": refs,
            }
        )

    safety = raw.get("brand_safety") if isinstance(raw.get("brand_safety"), dict) else {}
    report: dict[str, Any] = {
        "report_id": report_id,
        "report_type": report_type,
        "target_id": target_id,
        "executive_summary": _text(raw.get("executive_summary"), 1800),
        "content_profile": {
            "themes": _strings(content_profile.get("themes"), 6),
            "audience_signals": _strings(content_profile.get("audience_signals"), 6),
            "tone": _strings(content_profile.get("tone"), 4),
            "campaign_intents": _strings(content_profile.get("campaign_intents"), 5),
        },
        "keywords": keywords,
        "ad_categories": categories,
        "brand_prospects": brands,
        "brand_safety": {
            "summary": _text(safety.get("summary"), 900),
            "findings": _strings(safety.get("findings"), 8),
        },
        "creative_recommendations": _strings(raw.get("creative_recommendations"), 10, 500),
        "limitations": _strings(raw.get("limitations"), 8, 500),
        "brand_prospect_disclaimer": BRAND_PROSPECT_DISCLAIMER,
        "metadata": {
            "model": model,
            "prompt_version": VIDEO_PROMPT_VERSION if report_type == "video" else COMPARISON_PROMPT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "analysis_fingerprint": fingerprint,
        },
        "evidence_index": valid_segments,
    }

    if report_type == "video":
        placements = []
        for item in raw.get("placement_opportunities", []) if isinstance(raw.get("placement_opportunities"), list) else []:
            if not isinstance(item, dict):
                continue
            segment_id = _text(item.get("segment_id"), 120)
            segment = valid_segments.get(segment_id)
            if not segment:
                continue
            placements.append(
                {
                    "segment_id": segment_id,
                    "start": segment["start"],
                    "end": segment["end"],
                    "score": _score(item.get("score")),
                    "format": _text(item.get("format"), 120),
                    "suggested_duration": _text(item.get("suggested_duration"), 80),
                    "messaging_angle": _text(item.get("messaging_angle"), 500),
                    "rationale": _text(item.get("rationale"), 600),
                    "evidence_refs": _valid_refs(item.get("evidence_refs"), valid_segment_ids),
                }
            )
            if len(placements) >= 8:
                break
        report["placement_opportunities"] = placements
        report["avoidance_zones"] = _normalize_timed_items(raw.get("avoidance_zones"), valid_segments, 6)
    else:
        cross = raw.get("cross_video_insights") if isinstance(raw.get("cross_video_insights"), dict) else {}
        report["cross_video_insights"] = {
            "shared_themes": _strings(cross.get("shared_themes"), 8),
            "keyword_overlap": _strings(cross.get("keyword_overlap"), 12),
            "important_differences": _strings(cross.get("important_differences"), 10, 500),
        }
        report["video_rankings"] = _normalize_rankings(raw.get("video_rankings"), valid_video_ids)
        report["brand_video_matrix"] = _normalize_matrix(
            raw.get("brand_video_matrix"), valid_video_ids, valid_segment_ids
        )
        report["comparative_placements"] = _normalize_comparison_placements(
            raw.get("comparative_placements"), valid_video_ids, valid_segments
        )
    return report


def _normalize_timed_items(value: Any, valid_segments: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        segment_id = _text(item.get("segment_id"), 120)
        segment = valid_segments.get(segment_id)
        if not segment:
            continue
        result.append(
            {
                "segment_id": segment_id,
                "start": segment["start"],
                "end": segment["end"],
                "reason": _text(item.get("reason"), 500),
            }
        )
        if len(result) >= limit:
            break
    return result


def _normalize_rankings(value: Any, valid_video_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        video_id = _text(item.get("video_id"), 120)
        if video_id not in valid_video_ids:
            continue
        result.append(
            {
                "video_id": video_id,
                "campaign_objective": _text(item.get("campaign_objective"), 180),
                "rank": max(1, int(_score(item.get("rank")) or 1)),
                "rationale": _text(item.get("rationale"), 600),
            }
        )
    return result[:20]


def _normalize_matrix(value: Any, valid_video_ids: set[str], valid_segment_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        video_id = _text(item.get("video_id"), 120)
        brand = _text(item.get("brand"), 160)
        if video_id not in valid_video_ids or not brand:
            continue
        result.append(
            {
                "brand": brand,
                "video_id": video_id,
                "contextual_fit_score": _score(item.get("contextual_fit_score")),
                "rationale": _text(item.get("rationale"), 600),
                "evidence_refs": _valid_refs(item.get("evidence_refs"), valid_segment_ids),
            }
        )
    return result[:20]


def _normalize_comparison_placements(
    value: Any, valid_video_ids: set[str], valid_segments: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        video_id = _text(item.get("video_id"), 120)
        segment_id = _text(item.get("segment_id"), 120)
        segment = valid_segments.get(segment_id)
        if video_id not in valid_video_ids or not segment or segment.get("video_id") != video_id:
            continue
        result.append(
            {
                "video_id": video_id,
                "segment_id": segment_id,
                "start": segment["start"],
                "end": segment["end"],
                "score": _score(item.get("score")),
                "rationale": _text(item.get("rationale"), 600),
            }
        )
    return result[:12]


def write_report_pdf(report: dict[str, Any], path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="NeuroAd Detailed Insight Report",
    )
    story: list[Any] = [
        Paragraph("NeuroAd Detailed Insight Report", styles["Title"]),
        Spacer(1, 6),
        Paragraph(_text(report.get("executive_summary"), 3000), styles["BodyText"]),
        Spacer(1, 12),
    ]

    _pdf_list_section(story, "Themes", report.get("content_profile", {}).get("themes", []), styles)
    _pdf_table_section(
        story,
        "Advertising categories",
        ["Category", "Fit", "Confidence", "Rationale"],
        [
            [
                item.get("category", ""),
                item.get("contextual_fit_score", 0),
                item.get("confidence", 0),
                item.get("rationale", ""),
            ]
            for item in report.get("ad_categories", [])
        ],
        styles,
        Table,
        TableStyle,
        colors,
    )
    _pdf_table_section(
        story,
        "Keywords",
        ["Keyword", "Type", "Confidence"],
        [[item.get("term", ""), item.get("type", ""), item.get("confidence", 0)] for item in report.get("keywords", [])],
        styles,
        Table,
        TableStyle,
        colors,
    )
    story.extend([PageBreak(), Paragraph("Brand prospects", styles["Heading1"])])
    for brand in report.get("brand_prospects", []):
        story.extend(
            [
                Paragraph(
                    f"{_text(brand.get('brand'), 200)} · {_text(brand.get('category'), 200)} "
                    f"({_score(brand.get('contextual_fit_score'))}/100)",
                    styles["Heading2"],
                ),
                Paragraph(_text(brand.get("why_fit"), 1200), styles["BodyText"]),
                Paragraph(f"<b>Activation:</b> {_text(brand.get('activation_idea'), 1200)}", styles["BodyText"]),
                Spacer(1, 8),
            ]
        )
    story.extend(
        [
            Paragraph(BRAND_PROSPECT_DISCLAIMER, styles["Italic"]),
            Spacer(1, 12),
        ]
    )
    placement_key = "placement_opportunities" if report.get("report_type") == "video" else "comparative_placements"
    _pdf_list_section(
        story,
        "Placement opportunities",
        [
            f"{item.get('video_id', '')} {item.get('start', 0):g}–{item.get('end', 0):g}s: "
            f"{item.get('rationale') or item.get('messaging_angle', '')}"
            for item in report.get(placement_key, [])
        ],
        styles,
    )
    _pdf_list_section(story, "Creative recommendations", report.get("creative_recommendations", []), styles)
    _pdf_list_section(story, "Brand safety", report.get("brand_safety", {}).get("findings", []), styles)
    _pdf_list_section(story, "Limitations", report.get("limitations", []), styles)
    story.extend(
        [
            Spacer(1, 10),
            Paragraph(
                "Methodology: GPT-OSS synthesizes deterministic transcript, OCR, object, topic, safety, and "
                "placement evidence. Existing NeuroAd scores remain authoritative.",
                styles["Italic"],
            ),
        ]
    )

    def add_page_number(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)


def _pdf_list_section(story: list[Any], title: str, items: Any, styles: Any) -> None:
    values = items if isinstance(items, list) else []
    story.append(Paragraph(title, styles["Heading1"]))
    if not values:
        story.append(Paragraph("No evidence-backed items were returned.", styles["BodyText"]))
    for item in values:
        story.append(Paragraph(f"• {_text(item, 1600)}", styles["BodyText"]))
    story.append(Spacer(1, 10))


def _pdf_table_section(
    story: list[Any],
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    styles: Any,
    table_cls: Any,
    table_style_cls: Any,
    colors: Any,
) -> None:
    story.append(Paragraph(title, styles["Heading1"]))
    if not rows:
        story.extend([Paragraph("No evidence-backed items were returned.", styles["BodyText"]), Spacer(1, 10)])
        return
    data = [[Paragraph(_text(cell, 900), styles["BodyText"]) for cell in headers]]
    data.extend([[Paragraph(_text(cell, 900), styles["BodyText"]) for cell in row] for row in rows])
    table = table_cls(data, repeatRows=1)
    table.setStyle(
        table_style_cls(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f7fb")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4ca")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([table, Spacer(1, 10)])
