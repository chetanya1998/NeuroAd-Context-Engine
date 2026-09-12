# Third-party notices

## YOLOX-Nano

The production object detector is built from the [YOLOX 0.3.0 source
release](https://github.com/Megvii-BaseDetection/YOLOX/tree/0.3.0), licensed
under Apache-2.0. The Docker build pins the source commit and the official
YOLOX-Nano checkpoint checksum before exporting a static ONNX artifact.

## ONNX Runtime

The runtime uses ONNX Runtime, licensed under the MIT License. The production
image pins the package version in `apps/api/requirements-yolox.txt`.

This notice does not replace an asset-level licence review for a particular
deployment or any changes to the model artefact.
