FROM python:3.11-slim

ARG NEUROAD_GIT_SHA=development
ARG NEUROAD_GIT_BRANCH=main
ARG NEUROAD_BUILD_TIME=unknown
ARG NEUROAD_RELEASE_ID=unreleased
ARG NEUROAD_SCORING_MANIFEST_VERSION=attention-proxy-v1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEUROAD_STORAGE_DIR=/data/neuroad/storage \
    NEUROAD_DB_PATH=/data/neuroad/neuroad.db \
    NEUROAD_WORKERS=1 \
    NEUROAD_LOCAL_EXTRACTOR_WORKERS=3 \
    NEUROAD_ENABLE_EXTRACTOR_CACHE=1 \
    NEUROAD_MAX_SOURCE_SECONDS=600 \
    NEUROAD_MAX_ANALYSIS_SECONDS=600 \
    NEUROAD_MODEL_DIR=/data/neuroad/models \
    NEUROAD_ENABLE_AUDIO_CLEANUP=0 \
    NEUROAD_AUDIO_CLEANUP_ENGINE=uvr \
    NEUROAD_ENABLE_VAD=0 \
    NEUROAD_ENABLE_TRANSCRIPTION=1 \
    NEUROAD_TRANSCRIPTION_ENGINE=faster_whisper \
    NEUROAD_ENABLE_OBJECT_DETECTION=1 \
    NEUROAD_OBJECT_DETECTION_ENGINE=yolo \
    NEUROAD_ENABLE_OCR=1 \
    NEUROAD_ENABLE_SILERO_VAD=1 \
    NEUROAD_ENABLE_LIBROSA=1 \
    NEUROAD_ENABLE_SEMANTIC_MODELS=1 \
    VOSK_MODEL_DIR=/opt/neuroad/models/vosk-model-small-en-us-0.15 \
    MOBILENET_SSD_GRAPH=/opt/neuroad/models/mobilenet-ssd/frozen_inference_graph.pb \
    MOBILENET_SSD_CONFIG=/opt/neuroad/models/mobilenet-ssd/ssd_mobilenet_v1_coco.pbtxt \
    MEDIAPIPE_FACE_MODEL=/opt/neuroad/models/face_landmarker.task \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    WHISPER_WORD_TIMESTAMPS=1 \
    WHISPER_VAD_FILTER=1 \
    YOLO_MODEL=/opt/neuroad/models/yolo26s.pt \
    YOLOE_MODEL=/opt/neuroad/models/yoloe-26l-seg.pt \
    NEUROAD_GIT_SHA=$NEUROAD_GIT_SHA \
    NEUROAD_GIT_BRANCH=$NEUROAD_GIT_BRANCH \
    NEUROAD_BUILD_TIME=$NEUROAD_BUILD_TIME \
    NEUROAD_RELEASE_ID=$NEUROAD_RELEASE_ID \
    NEUROAD_SCORING_MANIFEST_VERSION=$NEUROAD_SCORING_MANIFEST_VERSION

WORKDIR /app

ARG INSTALL_VOSK=1
ARG INSTALL_MOBILENET_SSD=1
ARG INSTALL_WHISPER=1
ARG INSTALL_YOLO=1
ARG INSTALL_YOLOE=0
ARG INSTALL_UVR=0
ARG INSTALL_SIGNALS=1
ARG INSTALL_OCR=1
ARG INSTALL_SEMANTIC=1
ARG INSTALL_JOBS=1
ARG TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
ARG TORCH_VERSION="2.10.0+cpu"
ARG TORCHVISION_VERSION="0.25.0+cpu"
ARG TORCHAUDIO_VERSION="2.10.0+cpu"
ARG YOLO_MODEL_SHA256="646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b"
ARG YOLOE_MODEL_SHA256=""
ARG MEDIAPIPE_FACE_MODEL_SHA256=""

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsndfile1 \
        python3-dev \
        tesseract-ocr \
        fonts-dejavu-core \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/neuroad/storage /opt/neuroad/models

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --default-timeout=1000 -r requirements.txt
COPY requirements-vosk.txt .
RUN if [ "$INSTALL_VOSK" = "1" ]; then pip install --default-timeout=1000 -r requirements-vosk.txt; fi
COPY requirements-whisper.txt .
RUN if [ "$INSTALL_WHISPER" = "1" ]; then pip install --default-timeout=1000 -r requirements-whisper.txt; fi
RUN if [ "$INSTALL_YOLO" = "1" ] || [ "$INSTALL_SIGNALS" = "1" ] || [ "$INSTALL_SEMANTIC" = "1" ]; then \
        pip install --default-timeout=1000 --index-url "$TORCH_INDEX_URL" \
            "torch==$TORCH_VERSION" "torchvision==$TORCHVISION_VERSION" \
            "torchaudio==$TORCHAUDIO_VERSION"; \
    fi
COPY requirements-yolo.txt .
RUN if [ "$INSTALL_YOLO" = "1" ]; then pip install --default-timeout=1000 -r requirements-yolo.txt; fi
COPY requirements-uvr.txt .
RUN if [ "$INSTALL_UVR" = "1" ]; then pip install --default-timeout=1000 -r requirements-uvr.txt; fi
COPY requirements-signals.txt .
RUN if [ "$INSTALL_SIGNALS" = "1" ]; then pip install --default-timeout=1000 -r requirements-signals.txt; fi
COPY requirements-ocr.txt .
RUN if [ "$INSTALL_OCR" = "1" ]; then pip install --default-timeout=1000 -r requirements-ocr.txt; fi
COPY requirements-semantic.txt .
RUN if [ "$INSTALL_SEMANTIC" = "1" ]; then pip install --default-timeout=1000 -r requirements-semantic.txt; fi
COPY requirements-jobs.txt .
RUN if [ "$INSTALL_JOBS" = "1" ]; then pip install --default-timeout=1000 -r requirements-jobs.txt; fi

COPY smoke_detector.py .

RUN if [ "$INSTALL_VOSK" = "1" ]; then \
        curl -fL --retry 5 --retry-delay 5 --retry-connrefused --continue-at - -o /tmp/vosk-model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip \
        && unzip -q /tmp/vosk-model.zip -d /opt/neuroad/models \
        && rm /tmp/vosk-model.zip; \
    fi \
    && if [ "$INSTALL_MOBILENET_SSD" = "1" ]; then \
        mkdir -p /opt/neuroad/models/mobilenet-ssd \
        && curl -fL --retry 5 --retry-delay 5 --retry-connrefused --continue-at - -o /tmp/ssd_mobilenet.tar.gz http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v1_coco_2017_11_17.tar.gz \
        && tar -xzf /tmp/ssd_mobilenet.tar.gz -C /tmp \
        && cp /tmp/ssd_mobilenet_v1_coco_2017_11_17/frozen_inference_graph.pb /opt/neuroad/models/mobilenet-ssd/frozen_inference_graph.pb \
        && curl -fL --retry 5 --retry-delay 5 --retry-connrefused -o /opt/neuroad/models/mobilenet-ssd/ssd_mobilenet_v1_coco.pbtxt https://raw.githubusercontent.com/opencv/opencv_extra/master/testdata/dnn/ssd_mobilenet_v1_coco.pbtxt \
        && rm -rf /tmp/ssd_mobilenet.tar.gz /tmp/ssd_mobilenet_v1_coco_2017_11_17; \
    fi \
    && if [ "$INSTALL_YOLO" = "1" ]; then \
        python -c "from pathlib import Path; import shutil; from ultralytics import YOLO; model = YOLO('yolo26s.pt'); source = Path(model.ckpt_path); target = Path('/opt/neuroad/models/yolo26s.pt'); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target) if source.resolve() != target.resolve() else None" \
        && test -s /opt/neuroad/models/yolo26s.pt \
        && actual_checksum="$(sha256sum /opt/neuroad/models/yolo26s.pt | cut -d' ' -f1)" \
        && if [ -n "$YOLO_MODEL_SHA256" ] && [ "$actual_checksum" != "$YOLO_MODEL_SHA256" ]; then echo "YOLO model checksum mismatch"; exit 1; fi \
        && echo "$actual_checksum" > /opt/neuroad/models/yolo26s.pt.sha256 \
        && python smoke_detector.py --engine yolo --model /opt/neuroad/models/yolo26s.pt; \
    fi \
    && if [ "$INSTALL_YOLOE" = "1" ]; then \
        python -c "from pathlib import Path; import shutil; from ultralytics import YOLOE; model = YOLOE('yoloe-26l-seg.pt'); source = Path(model.ckpt_path); target = Path('/opt/neuroad/models/yoloe-26l-seg.pt'); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target) if source.resolve() != target.resolve() else None" \
        && test -s /opt/neuroad/models/yoloe-26l-seg.pt \
        && yoloe_checksum="$(sha256sum /opt/neuroad/models/yoloe-26l-seg.pt | cut -d' ' -f1)" \
        && if [ -n "$YOLOE_MODEL_SHA256" ] && [ "$yoloe_checksum" != "$YOLOE_MODEL_SHA256" ]; then echo "YOLOE model checksum mismatch"; exit 1; fi \
        && echo "$yoloe_checksum" > /opt/neuroad/models/yoloe-26l-seg.pt.sha256 \
        && python smoke_detector.py --engine yoloe --model /opt/neuroad/models/yoloe-26l-seg.pt; \
    fi \
    && if [ "$INSTALL_SIGNALS" = "1" ]; then \
        curl -fL --retry 5 --retry-delay 5 --retry-connrefused -o /opt/neuroad/models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
        && test -s /opt/neuroad/models/face_landmarker.task \
        && face_checksum="$(sha256sum /opt/neuroad/models/face_landmarker.task | cut -d' ' -f1)" \
        && if [ -n "$MEDIAPIPE_FACE_MODEL_SHA256" ] && [ "$face_checksum" != "$MEDIAPIPE_FACE_MODEL_SHA256" ]; then echo "MediaPipe face model checksum mismatch"; exit 1; fi \
        && echo "$face_checksum" > /opt/neuroad/models/face_landmarker.task.sha256; \
    fi

COPY main.py object_storage.py content_signals.py celery_app.py runpod_client.py insight_report.py analytics.py admin_platform.py ./

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
