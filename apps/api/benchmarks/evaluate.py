from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


PRODUCT_TERMS = {
    "product",
    "packaging",
    "bottle",
    "box",
    "packet",
    "sachet",
    "tube",
    "jar",
    "can",
    "cosmetics",
    "clothing",
    "electronics",
    "food product",
}


def load_records(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    values = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line.strip()]
    return {str(item["video_id"]): item for item in values}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def bbox_iou(first: list[float], second: list[float]) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def evaluation_class(item: dict[str, Any]) -> str | None:
    kind = str(item.get("kind", "")).lower()
    label = str(item.get("label", "")).lower()
    if kind in {"person", "product"}:
        return kind
    if label == "person":
        return "person"
    if any(term in label for term in PRODUCT_TERMS):
        return "product"
    return None


def nearest_frame(frames: list[dict[str, Any]], timestamp: float, tolerance: float = 0.25) -> dict[str, Any] | None:
    candidate = min(frames, key=lambda item: abs(float(item.get("timestamp", 0)) - timestamp), default=None)
    return candidate if candidate and abs(float(candidate.get("timestamp", 0)) - timestamp) <= tolerance else None


def detection_counts(
    annotations: dict[str, dict[str, Any]], predictions: dict[str, dict[str, Any]]
) -> tuple[int, int, int, list[float]]:
    true_positive = false_positive = false_negative = 0
    people_errors: list[float] = []
    for video_id, truth in annotations.items():
        predicted_frames = predictions.get(video_id, {}).get("frames", [])
        for truth_frame in truth.get("frames", []):
            predicted_frame = nearest_frame(predicted_frames, float(truth_frame.get("timestamp", 0)))
            truth_objects = [item for item in truth_frame.get("objects", []) if evaluation_class(item)]
            predicted_objects = [item for item in (predicted_frame or {}).get("objects", []) if evaluation_class(item)]
            unmatched = set(range(len(predicted_objects)))
            for truth_object in truth_objects:
                truth_class = evaluation_class(truth_object)
                matches = [
                    index
                    for index in unmatched
                    if evaluation_class(predicted_objects[index]) == truth_class
                    and bbox_iou(truth_object["bbox"], predicted_objects[index]["bbox"]) >= 0.5
                ]
                if matches:
                    best = max(matches, key=lambda index: bbox_iou(truth_object["bbox"], predicted_objects[index]["bbox"]))
                    unmatched.remove(best)
                    true_positive += 1
                else:
                    false_negative += 1
            false_positive += len(unmatched)
            truth_people = int(truth_frame.get("people_count", sum(evaluation_class(item) == "person" for item in truth_objects)))
            predicted_people = sum(evaluation_class(item) == "person" for item in predicted_objects)
            people_errors.append(abs(truth_people - predicted_people))
    return true_positive, false_positive, false_negative, people_errors


def boundary_counts(truth: list[float], predicted: list[float], tolerance: float = 0.5) -> tuple[int, int, int]:
    unmatched = set(range(len(predicted)))
    true_positive = 0
    for boundary in truth:
        matches = [index for index in unmatched if abs(float(predicted[index]) - float(boundary)) <= tolerance]
        if matches:
            unmatched.remove(min(matches, key=lambda index: abs(float(predicted[index]) - float(boundary))))
            true_positive += 1
    return true_positive, len(unmatched), len(truth) - true_positive


def edit_distance(first: str, second: str) -> int:
    previous = list(range(len(second) + 1))
    for first_index, first_character in enumerate(first, start=1):
        current = [first_index]
        for second_index, second_character in enumerate(second, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[second_index] + 1,
                    previous[second_index - 1] + (first_character != second_character),
                )
            )
        previous = current
    return previous[-1]


def normalized_text(value: str) -> str:
    return " ".join(value.lower().split())


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate(annotations: dict[str, dict[str, Any]], predictions: dict[str, dict[str, Any]], baseline: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    tp, fp, fn, people_errors = detection_counts(annotations, predictions)
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)

    scene_tp = scene_fp = scene_fn = 0
    event_errors: list[float] = []
    ocr_truth_count = ocr_recalled = 0
    ocr_characters = ocr_edits = 0
    decision_total = decision_matches = 0
    unsupported_high = 0
    diarization_values: list[float] = []
    durations: list[float] = []
    costs: list[float] = []
    for video_id, truth in annotations.items():
        predicted = predictions.get(video_id, {})
        current_tp, current_fp, current_fn = boundary_counts(
            truth.get("scene_boundaries", []), predicted.get("scene_boundaries", [])
        )
        scene_tp += current_tp
        scene_fp += current_fp
        scene_fn += current_fn
        predicted_events = predicted.get("product_events", [])
        for event in truth.get("product_events", []):
            candidates = [
                candidate
                for candidate in predicted_events
                if candidate.get("event") == event.get("event") and candidate.get("label") == event.get("label")
            ]
            if candidates:
                nearest = min(candidates, key=lambda candidate: abs(float(candidate["timestamp"]) - float(event["timestamp"])))
                event_errors.append(abs(float(nearest["timestamp"]) - float(event["timestamp"])))
        predicted_ocr = [normalized_text(str(item.get("text", ""))) for item in predicted.get("ocr", [])]
        for item in truth.get("ocr", []):
            expected = normalized_text(str(item.get("text", "")))
            if not expected:
                continue
            ocr_truth_count += 1
            best = min(predicted_ocr, key=lambda value: edit_distance(expected, value), default="")
            distance = edit_distance(expected, best)
            ocr_characters += len(expected)
            ocr_edits += distance
            if distance / max(1, len(expected)) <= 0.2:
                ocr_recalled += 1
        for key, expected in truth.get("decision_labels", {}).items():
            decision_total += 1
            decision_matches += predicted.get("decision_labels", {}).get(key) == expected
        unsupported_high += sum(
            str(item.get("evidence_reliability", "")).lower() == "high" and not bool(item.get("supported", False))
            for item in predicted.get("recommendations", [])
        )
        if predicted.get("diarization_der") is not None:
            diarization_values.append(float(predicted["diarization_der"]))
        performance = predicted.get("performance", {})
        if performance.get("seconds_per_minute") is not None:
            durations.append(float(performance["seconds_per_minute"]))
        if performance.get("cost_per_minute") is not None:
            costs.append(float(performance["cost_per_minute"]))

    scene_precision = safe_ratio(scene_tp, scene_tp + scene_fp)
    scene_recall = safe_ratio(scene_tp, scene_tp + scene_fn)
    scene_f1 = safe_ratio(2 * scene_precision * scene_recall, scene_precision + scene_recall)
    metrics: dict[str, Any] = {
        "person_product_precision": round(precision, 4),
        "person_product_recall": round(recall, 4),
        "product_event_median_error_seconds": round(statistics.median(event_errors), 4) if event_errors else None,
        "people_count_mae": round(statistics.mean(people_errors), 4) if people_errors else None,
        "scene_boundary_f1": round(scene_f1, 4),
        "ocr_text_recall": round(safe_ratio(ocr_recalled, ocr_truth_count), 4),
        "ocr_character_error_rate": round(safe_ratio(ocr_edits, ocr_characters), 4),
        "diarization_der": round(statistics.mean(diarization_values), 4) if diarization_values else None,
        "decision_label_agreement": round(safe_ratio(decision_matches, decision_total), 4),
        "unsupported_high_reliability_recommendations": unsupported_high,
        "seconds_per_minute_p50": round(percentile(durations, 0.5), 4) if durations else None,
        "seconds_per_minute_p95": round(percentile(durations, 0.95), 4) if durations else None,
        "cost_per_minute_p50": round(percentile(costs, 0.5), 4) if costs else None,
        "cost_per_minute_p95": round(percentile(costs, 0.95), 4) if costs else None,
    }
    if baseline is not None:
        baseline_tp, baseline_fp, baseline_fn, _ = detection_counts(annotations, baseline)
        baseline_precision = safe_ratio(baseline_tp, baseline_tp + baseline_fp)
        baseline_recall = safe_ratio(baseline_tp, baseline_tp + baseline_fn)
        metrics["recall_improvement_points"] = round(recall - baseline_recall, 4)
        metrics["precision_change_points"] = round(precision - baseline_precision, 4)

    gates = {
        "person_product_recall": recall >= 0.85,
        "person_product_precision": precision >= 0.80,
        "product_event_timing": metrics["product_event_median_error_seconds"] is not None and metrics["product_event_median_error_seconds"] <= 0.5,
        "people_count_mae": metrics["people_count_mae"] is not None and metrics["people_count_mae"] <= 0.5,
        "scene_boundary_f1": scene_f1 >= 0.90,
        "ocr_text_recall": metrics["ocr_text_recall"] >= 0.85,
        "ocr_character_error_rate": metrics["ocr_character_error_rate"] <= 0.15,
        "diarization_der": metrics["diarization_der"] is not None and metrics["diarization_der"] <= 0.20,
        "decision_label_agreement": metrics["decision_label_agreement"] >= 0.80,
        "no_unsupported_high_reliability": unsupported_high == 0,
    }
    if baseline is not None:
        gates["recall_improvement"] = metrics["recall_improvement_points"] >= 0.20
        gates["precision_regression"] = metrics["precision_change_points"] >= -0.05
    return {"metrics": metrics, "gates": gates, "passed": all(gates.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NeuroAd release gates on a consent-safe benchmark.")
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    result = evaluate(
        load_records(args.annotations),
        load_records(args.predictions),
        load_records(args.baseline) if args.baseline else None,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if args.enforce and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
