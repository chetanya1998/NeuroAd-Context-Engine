"""Fail the image build if the exported YOLOX ONNX model cannot run on CPU."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one CPU inference against YOLOX ONNX.")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--input-size", default=416, type=int)
    args = parser.parse_args()
    if not args.model.is_file() or args.model.stat().st_size <= 0:
        raise SystemExit(f"YOLOX ONNX model is missing or empty: {args.model}")

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise SystemExit("YOLOX ONNX contract must contain one input and one output.")
    if list(inputs[0].shape) != [1, 3, args.input_size, args.input_size]:
        raise SystemExit(f"Unexpected YOLOX input shape: {inputs[0].shape}")
    result = session.run(None, {inputs[0].name: np.zeros((1, 3, args.input_size, args.input_size), dtype=np.float32)})[0]
    if result.shape != (1, 3549, 85) or not np.isfinite(result).all():
        raise SystemExit(f"Unexpected YOLOX output contract: {result.shape}")


if __name__ == "__main__":
    main()
