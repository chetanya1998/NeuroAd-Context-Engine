import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from evaluate import evaluate


def test_benchmark_evaluator_enforces_detection_and_evidence_gates():
    annotations = {
        "video_1": {
            "video_id": "video_1",
            "frames": [{"timestamp": 1.0, "people_count": 1, "objects": [{"label": "person", "bbox": [0, 0, 100, 100]}]}],
            "product_events": [{"event": "appearance", "label": "bottle", "timestamp": 2.0}],
            "scene_boundaries": [3.0],
            "ocr": [{"text": "Hydrate now"}],
            "decision_labels": {"hook_strength": "Strong"},
        }
    }
    predictions = {
        "video_1": {
            "video_id": "video_1",
            "frames": [{"timestamp": 1.0, "objects": [{"label": "person", "bbox": [0, 0, 100, 100]}]}],
            "product_events": [{"event": "appearance", "label": "bottle", "timestamp": 2.2}],
            "scene_boundaries": [3.1],
            "ocr": [{"text": "Hydrate now"}],
            "decision_labels": {"hook_strength": "Strong"},
            "recommendations": [{"evidence_reliability": "High", "supported": True}],
            "diarization_der": 0.1,
        }
    }

    result = evaluate(annotations, predictions)

    assert result["metrics"]["person_product_recall"] == 1.0
    assert result["metrics"]["product_event_median_error_seconds"] == 0.2
    assert result["passed"] is True
