# Consent-safe release benchmark

Keep benchmark media outside Git. Only opted-in media and annotations may be used.

The evaluator accepts JSON arrays or JSONL records keyed by `video_id`. An annotation record can contain `frames` with timestamped person/product boxes, `product_events`, `scene_boundaries`, readable `ocr` text, and expected `decision_labels`. Prediction records use the same fields and may additionally contain recommendation support flags, diarization DER, and per-minute performance/cost.

Run:

```bash
python apps/api/benchmarks/evaluate.py \
  --annotations /private/benchmark/annotations.jsonl \
  --predictions /private/benchmark/new-pipeline.jsonl \
  --baseline /private/benchmark/legacy-pipeline.jsonl \
  --output /private/benchmark/release-gates.json \
  --enforce
```

The command exits non-zero when any configured plan threshold fails. It deliberately fails unavailable gates such as diarization rather than treating missing evidence as zero or success.
