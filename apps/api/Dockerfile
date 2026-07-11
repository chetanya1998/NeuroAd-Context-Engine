FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEUROAD_STORAGE_DIR=/data/neuroad/storage \
    NEUROAD_DB_PATH=/data/neuroad/neuroad.db \
    NEUROAD_WORKERS=1 \
    NEUROAD_MAX_SOURCE_SECONDS=600 \
    NEUROAD_MAX_ANALYSIS_SECONDS=180 \
    NEUROAD_MODEL_DIR=/opt/neuroad/models \
    NEUROAD_ENABLE_AUDIO_CLEANUP=0 \
    NEUROAD_AUDIO_CLEANUP_ENGINE=uvr \
    NEUROAD_ENABLE_VAD=0 \
    NEUROAD_ENABLE_TRANSCRIPTION=1 \
    NEUROAD_TRANSCRIPTION_ENGINE=vosk \
    NEUROAD_ENABLE_OBJECT_DETECTION=1 \
    NEUROAD_OBJECT_DETECTION_ENGINE=yolo \
    VOSK_MODEL_DIR=/opt/neuroad/models/vosk-model-small-en-us-0.15 \
    MOBILENET_SSD_GRAPH=/opt/neuroad/models/mobilenet-ssd/frozen_inference_graph.pb \
    MOBILENET_SSD_CONFIG=/opt/neuroad/models/mobilenet-ssd/ssd_mobilenet_v1_coco.pbtxt \
    WHISPER_MODEL=tiny \
    YOLO_MODEL=yolov8n.pt

WORKDIR /app

ARG INSTALL_VOSK=1
ARG INSTALL_MOBILENET_SSD=1
ARG INSTALL_WHISPER=0
ARG INSTALL_YOLO=1
ARG INSTALL_UVR=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        python3-dev \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/neuroad/storage /opt/neuroad/models

COPY requirements.txt requirements-vosk.txt requirements-whisper.txt requirements-yolo.txt requirements-uvr.txt .
RUN pip install --upgrade pip \
    && pip install --default-timeout=1000 -r requirements.txt \
    && if [ "$INSTALL_VOSK" = "1" ]; then pip install --default-timeout=1000 -r requirements-vosk.txt; fi \
    && if [ "$INSTALL_WHISPER" = "1" ]; then pip install --default-timeout=1000 -r requirements-whisper.txt; fi \
    && if [ "$INSTALL_YOLO" = "1" ]; then pip install --default-timeout=1000 -r requirements-yolo.txt; fi \
    && if [ "$INSTALL_UVR" = "1" ]; then pip install --default-timeout=1000 -r requirements-uvr.txt; fi

RUN if [ "$INSTALL_YOLO" = "1" ]; then \
        python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"; \
    fi

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
    fi

COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

CMD uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
