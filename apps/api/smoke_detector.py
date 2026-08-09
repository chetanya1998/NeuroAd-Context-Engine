from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a configured Ultralytics detector and run one inference.")
    parser.add_argument("--engine", choices=("yolo", "yoloe"), default="yolo")
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    model_path = Path(args.model).resolve()
    if not model_path.is_file() or model_path.stat().st_size <= 0:
        raise SystemExit(f"Detector weight is missing or empty: {model_path}")

    if args.engine == "yoloe":
        from ultralytics import YOLOE

        detector = YOLOE(str(model_path))
        detector.set_classes(["person", "product packaging"])
    else:
        from ultralytics import YOLO

        detector = YOLO(str(model_path))

    started = time.perf_counter()
    predict_arguments = {
        "source": np.zeros((320, 320, 3), dtype=np.uint8),
        "imgsz": 320,
        "verbose": False,
    }
    if args.device:
        predict_arguments["device"] = args.device
    results = detector.predict(**predict_arguments)
    if len(results) != 1:
        raise SystemExit("Detector smoke inference returned an unexpected result count.")

    print(
        json.dumps(
            {
                "status": "ok",
                "engine": args.engine,
                "model": str(model_path),
                "sha256": file_sha256(model_path),
                "inference_seconds": round(time.perf_counter() - started, 3),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
