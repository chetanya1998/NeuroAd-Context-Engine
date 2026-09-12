"""Export the pinned YOLOX-Nano checkpoint to a static ONNX Runtime artifact.

This helper is executed only in the Docker builder stage. Keeping it in the
repository makes the model conversion reproducible and avoids shipping the
YOLOX Python package or PyTorch in the runtime image.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torch import nn

from yolox.exp import get_exp
from yolox.models.network_blocks import SiLU
from yolox.utils import replace_module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export YOLOX-Nano to ONNX.")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input-size", default=416, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.input_size != 416:
        raise SystemExit("The pinned YOLOX-Nano checkpoint is exported at 416px only.")
    if not args.checkpoint.is_file() or args.checkpoint.stat().st_size <= 0:
        raise SystemExit(f"YOLOX checkpoint is missing or empty: {args.checkpoint}")

    experiment = get_exp(None, "yolox-nano")
    model = experiment.get_model()
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    model.load_state_dict(checkpoint["model"] if "model" in checkpoint else checkpoint)
    model = replace_module(model, nn.SiLU, SiLU).eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # ``dynamo=False`` intentionally uses the stable TorchScript exporter. It
    # supports the fixed-shape model and is compatible with the pinned ONNX opset.
    torch.onnx.export(
        model,
        torch.randn(1, 3, args.input_size, args.input_size),
        args.output,
        input_names=["images"],
        output_names=["output"],
        opset_version=11,
        dynamo=False,
    )


if __name__ == "__main__":
    main()
