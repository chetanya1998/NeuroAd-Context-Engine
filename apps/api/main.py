from __future__ import annotations

import csv
import hashlib
from collections import Counter
from html.parser import HTMLParser
import importlib.util
from importlib.metadata import PackageNotFoundError, version as package_version
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import shutil
import sqlite3
import socket
import subprocess
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, Request as FastAPIRequest, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analytics import AnalyticsContext, capture_event, shutdown_analytics
from insight_report import (
    BRAND_PROSPECT_DISCLAIMER,
    COMPARISON_PROMPT_VERSION,
    COMPARISON_SYSTEM_PROMPT,
    VIDEO_PROMPT_VERSION,
    VIDEO_SYSTEM_PROMPT,
    normalize_report,
    write_report_pdf,
)
from runpod_client import RunPodClient, RunPodError, RunPodSettings
from admin_platform import AdminServices, create_admin_router, init_admin_platform, record_admin_metric_event
try:
    from .object_storage import ObjectStorage, content_type_for_suffix
except ImportError:
    from object_storage import ObjectStorage, content_type_for_suffix
try:
    from .content_signals import ANALYSIS_SCHEMA_VERSION, build_signal_payload, enrich_segments_with_signals
except ImportError:
    from content_signals import ANALYSIS_SCHEMA_VERSION, build_signal_payload, enrich_segments_with_signals


APP_DIR = Path(__file__).resolve().parent
INSIGHT_LOGGER = logging.getLogger("neuroad.insights")


def path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def float_from_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def cors_origins_from_env() -> list[str]:
    value = os.getenv("CORS_ORIGINS")
    if value:
        return [origin.strip() for origin in value.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def local_network_cors_origin_regex() -> str | None:
    """Allow browser testing from a private LAN only outside production.

    Production deployments must retain the explicit CORS_ORIGINS allow-list. This
    development-only regex lets a phone or another computer reach a local API
    without hard-coding the developer's current router address.
    """
    production = os.getenv("NEUROAD_ENVIRONMENT", "development").lower() == "production"
    if not env_enabled("NEUROAD_ALLOW_LOCAL_NETWORK_CORS", not production):
        return None
    return r"^http://(?:(?:localhost)|(?:127\.0\.0\.1)|(?:10(?:\.\d{1,3}){3})|(?:192\.168(?:\.\d{1,3}){2})|(?:172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}))(?::\d{2,5})?$"


def admin_cors_origins_from_env() -> set[str]:
    value = os.getenv("ADMIN_CORS_ORIGINS")
    if value:
        return {origin.strip() for origin in value.split(",") if origin.strip()}
    return {"http://localhost:3001"}


def build_metadata() -> dict[str, str]:
    """Build metadata is injected by CI and displayed only in the internal app."""
    return {
        "git_sha": os.getenv("NEUROAD_GIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA", "development"),
        "git_branch": os.getenv("NEUROAD_GIT_BRANCH") or os.getenv("RAILWAY_GIT_BRANCH", "local"),
        "build_time": os.getenv("NEUROAD_BUILD_TIME") or os.getenv("RAILWAY_DEPLOYMENT_CREATED_AT", "deployment time unavailable"),
        "release_id": os.getenv("NEUROAD_RELEASE_ID") or os.getenv("RAILWAY_DEPLOYMENT_ID", "local"),
        "scoring_manifest_version": os.getenv("NEUROAD_SCORING_MANIFEST_VERSION", "attention-proxy-v1"),
    }


STORAGE_DIR = path_from_env("NEUROAD_STORAGE_DIR", APP_DIR / "storage")
UPLOAD_DIR = STORAGE_DIR / "uploads"
FRAME_DIR = STORAGE_DIR / "frames"
AUDIO_DIR = STORAGE_DIR / "audio"
REPORT_DIR = STORAGE_DIR / "reports"
SCRATCH_DIR = path_from_env("NEUROAD_SCRATCH_DIR", Path("/tmp/neuroad"))
DB_PATH = path_from_env("NEUROAD_DB_PATH", STORAGE_DIR / "neuroad.db")
MODEL_DIR = path_from_env("NEUROAD_MODEL_DIR", STORAGE_DIR.parent / "models")
VOSK_MODEL_DIR = path_from_env("VOSK_MODEL_DIR", MODEL_DIR / "vosk-model-small-en-us-0.15")
MOBILENET_SSD_GRAPH = path_from_env("MOBILENET_SSD_GRAPH", MODEL_DIR / "mobilenet-ssd" / "frozen_inference_graph.pb")
MOBILENET_SSD_CONFIG = path_from_env(
    "MOBILENET_SSD_CONFIG",
    MODEL_DIR / "mobilenet-ssd" / "ssd_mobilenet_v1_coco.pbtxt",
)
YOLO_MODEL_PATH = path_from_env("YOLO_MODEL", MODEL_DIR / "yolo11n.pt")
MEDIAPIPE_FACE_MODEL = path_from_env("MEDIAPIPE_FACE_MODEL", MODEL_DIR / "face_landmarker.task")

MAX_UPLOAD_BYTES = int_from_env("NEUROAD_MAX_UPLOAD_MB", 200) * 1024 * 1024
MAX_SOURCE_SECONDS = int_from_env("NEUROAD_MAX_SOURCE_SECONDS", 0)
MAX_ANALYSIS_SECONDS = int_from_env("NEUROAD_MAX_ANALYSIS_SECONDS", 600)
COMPARISON_MIN_VIDEOS = max(2, int_from_env("COMPARISON_MIN_VIDEOS", 2))
COMPARISON_MAX_VIDEOS = max(COMPARISON_MIN_VIDEOS, int_from_env("COMPARISON_MAX_VIDEOS", 5))
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
CONVERTIBLE_VIDEO_EXTENSIONS = ALLOWED_EXTENSIONS | {
    ".avi",
    ".mkv",
    ".flv",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".3g2",
    ".ogv",
}
EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int_from_env("NEUROAD_WORKERS", 1)))
OBJECT_STORAGE = ObjectStorage()
INSIGHT_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int_from_env("NEUROAD_INSIGHT_WORKERS", 1)))
FRAME_SAMPLE_RATE = float(os.getenv("NEUROAD_FRAME_SAMPLE_RATE", "1.0") or "1.0")
MAX_FRAMES_PER_SEGMENT = max(1, int_from_env("NEUROAD_MAX_FRAMES_PER_SEGMENT", 6))
DETECTION_MAX_FRAMES = max(1, int_from_env("NEUROAD_DETECTION_MAX_FRAMES", 90))
DETECTION_FRAMES_PER_SEGMENT = max(1, int_from_env("NEUROAD_DETECTION_FRAMES_PER_SEGMENT", 2))
YOLO_CONFIDENCE = float_from_env("NEUROAD_YOLO_CONFIDENCE", 0.25)
YOLO_IMAGE_SIZE = max(320, int_from_env("NEUROAD_YOLO_IMAGE_SIZE", 640))
MAX_OBJECTS_PER_SEGMENT = max(1, int_from_env("NEUROAD_MAX_OBJECTS_PER_SEGMENT", 12))
OCR_MAX_FRAMES = max(1, int_from_env("NEUROAD_OCR_MAX_FRAMES", 45))
OCR_CONFIDENCE = float_from_env("NEUROAD_OCR_CONFIDENCE", 55)
PRODUCT_PROFILE_VERSION = "2.0"
PRODUCT_FIT_SCORING_VERSION = "2.0"
PRODUCT_RESOLUTION_TTL_SECONDS = 24 * 60 * 60
FRAME_SAMPLE_RATE = float(os.getenv("NEUROAD_FRAME_SAMPLE_RATE", "3.0") or "3.0")
MAX_FRAMES_PER_SEGMENT = max(1, int_from_env("NEUROAD_MAX_FRAMES_PER_SEGMENT", 40))
YOLO_MODEL_PATH = path_from_env("YOLO_MODEL", MODEL_DIR / "yolo26s.pt")
YOLOE_MODEL_PATH = path_from_env("YOLOE_MODEL", MODEL_DIR / "yoloe-26l-seg.pt")
YOLO_CONFIDENCE = float_from_env("NEUROAD_YOLO_CONFIDENCE", 0.25)
YOLO_IMAGE_SIZE = max(320, int_from_env("NEUROAD_YOLO_IMAGE_SIZE", 640))
YOLO_BATCH_SIZE = max(1, int_from_env("NEUROAD_YOLO_BATCH_SIZE", 12))
MAX_OBJECTS_PER_FRAME = max(1, int_from_env("NEUROAD_MAX_OBJECTS_PER_FRAME", 30))
MAX_OBJECTS_PER_SEGMENT = max(MAX_OBJECTS_PER_FRAME, int_from_env("NEUROAD_MAX_OBJECTS_PER_SEGMENT", 90))
VOSK_MODEL_CACHE: Any | None = None
FASTER_WHISPER_MODEL_CACHE: Any | None = None
FASTER_WHISPER_MODEL_SIGNATURE: tuple[str, str, str] | None = None
MOBILENET_SSD_NET_CACHE: Any | None = None
YOLO_MODEL_CACHE: Any | None = None
YOLO_MODEL_CACHE_PATH: str | None = None
OBJECT_DETECTOR_FALLBACK_REASON: str | None = None
YOLO_MODEL_SIGNATURE: str | None = None
YOLOE_MODEL_CACHE: Any | None = None
YOLOE_MODEL_SIGNATURE: tuple[str, tuple[str, ...]] | None = None
PADDLE_OCR_CACHE: dict[str, Any] = {}
SILERO_VAD_MODEL_CACHE: Any | None = None
SENTENCE_MODEL_CACHE: Any | None = None
GLINER_MODEL_CACHE: Any | None = None
OBJECT_DETECTION_RUNTIME: dict[str, Any] = {
    "requested_engine": None,
    "active_detector": "unavailable",
    "model": None,
    "fallback_reason": None,
    "degraded": True,
}

PROCESSING_STEPS = [
    ("metadata", "Metadata fetched"),
    ("frames", "Frames extracted"),
    ("audio", "Audio prepared"),
    ("transcript", "Transcript processed"),
    ("objects", "Object detection and provenance recorded"),
    ("topics", "Topics extracted"),
    ("attention", "Attention timeline scored"),
    ("ad_scoring", "Ad-match scoring complete"),
    ("report", "Report generated"),
]

TOPIC_KEYWORDS = {
    "fitness": ["workout", "gym", "training", "protein", "exercise", "run"],
    "finance": ["money", "invest", "budget", "stock", "revenue", "profit"],
    "beauty": ["makeup", "beauty", "routine", "glow", "hair"],
    "skincare": ["skin", "serum", "moisturizer", "spf", "acne"],
    "gaming": ["game", "stream", "console", "level", "player"],
    "education": ["learn", "course", "student", "lesson", "explain"],
    "productivity": ["workflow", "dashboard", "team", "automation", "focus", "productivity"],
    "startup": ["startup", "founder", "launch", "growth", "product"],
    "travel": ["travel", "flight", "hotel", "city", "trip"],
    "food": ["food", "cook", "recipe", "coffee", "restaurant"],
    "fashion": ["fashion", "outfit", "shoes", "style", "clothing"],
    "entertainment": ["show", "music", "movie", "story", "fun"],
    "parenting": ["child", "kid", "parent", "family", "baby"],
    "technology": ["ai", "software", "laptop", "phone", "camera", "tech"],
    "health": ["health", "sleep", "doctor", "wellness", "stress"],
    "functional beverage": [
        "hydration",
        "hydrate",
        "electrolyte",
        "electrolytes",
        "sports drink",
        "zero sugar",
        "wellness drink",
        "functional beverage",
        "oral rehydration",
        "sachet",
    ],
    "luxury": ["luxury", "watch", "premium", "designer", "brand"],
    "automobiles": ["car", "vehicle", "drive", "engine", "auto"],
}

BASE_AD_CATALOG = [
    {
        "category": "Productivity SaaS",
        "keywords": ["workflow", "team", "dashboard", "automation", "productivity", "focus"],
        "objects": ["laptop", "cell phone", "phone", "keyboard", "mouse", "book"],
    },
    {
        "category": "AI Note-taking App",
        "keywords": ["meeting", "notes", "summary", "call", "productivity", "work"],
        "objects": ["laptop", "cell phone", "phone", "microphone"],
    },
    {
        "category": "Coffee Brand",
        "keywords": ["morning", "coffee", "energy", "routine", "work"],
        "objects": ["cup", "bottle", "dining table"],
    },
    {
        "category": "Fitness Product",
        "keywords": ["workout", "gym", "protein", "training", "health"],
        "objects": ["sports ball", "bottle", "person"],
    },
    {
        "category": "Functional Beverage",
        "keywords": [
            "hydration",
            "hydrate",
            "electrolyte",
            "electrolytes",
            "sports drink",
            "wellness drink",
            "clean label",
            "zero sugar",
            "beverage",
            "sachet",
            "oral rehydration",
        ],
        "objects": ["bottle", "cup", "sports ball", "person"],
        "audience": ["athlete", "wellness", "fitness", "health", "outdoor"],
    },
    {
        "category": "Creator Gear",
        "keywords": ["camera", "video", "recording", "studio", "content"],
        "objects": ["camera", "laptop", "cell phone", "tv"],
    },
    {
        "category": "Fashion / Apparel",
        "keywords": ["outfit", "style", "fashion", "shoes", "clothing"],
        "objects": ["shoe", "handbag", "tie", "backpack", "suitcase"],
    },
]

AD_AUDIENCE_TERMS = {
    "Productivity SaaS": ["team", "founder", "office", "workflow", "meeting", "dashboard"],
    "AI Note-taking App": ["meeting", "notes", "summary", "call", "student", "team"],
    "Coffee Brand": ["morning", "routine", "energy", "work", "break", "lifestyle"],
    "Fitness Product": ["workout", "gym", "protein", "training", "health", "wellness"],
    "Functional Beverage": ["hydration", "electrolyte", "wellness", "fitness", "athlete", "zero sugar"],
    "Creator Gear": ["creator", "camera", "video", "studio", "recording", "editing"],
    "Fashion / Apparel": ["outfit", "style", "fashion", "shoes", "clothing", "look"],
}

AD_VERTICALS = {
    "Productivity": {"keywords": ["workflow", "focus", "tasks", "team", "dashboard"], "objects": ["laptop", "keyboard", "cell phone"], "audience": ["founder", "team", "office"]},
    "AI Software": {"keywords": ["ai", "automation", "summary", "assistant", "model"], "objects": ["laptop", "cell phone"], "audience": ["creator", "founder", "developer"]},
    "Finance": {"keywords": ["money", "budget", "invest", "saving", "profit"], "objects": ["laptop", "cell phone", "book"], "audience": ["investor", "student", "founder"]},
    "Banking": {"keywords": ["bank", "card", "payment", "account", "saving"], "objects": ["cell phone", "laptop"], "audience": ["shopper", "family", "professional"]},
    "Insurance": {"keywords": ["protect", "safe", "family", "health", "coverage"], "objects": ["person", "car", "house"], "audience": ["family", "parent", "owner"]},
    "Fitness": {"keywords": ["workout", "gym", "training", "protein", "health"], "objects": ["person", "sports ball", "bottle"], "audience": ["athlete", "coach", "wellness"]},
    "Functional Beverage": {"keywords": ["hydration", "electrolyte", "sports drink", "zero sugar", "wellness drink", "sachet"], "objects": ["bottle", "cup", "sports ball", "person"], "audience": ["athlete", "fitness", "wellness"]},
    "Nutrition": {"keywords": ["protein", "meal", "healthy", "diet", "vitamin"], "objects": ["bottle", "bowl", "cup"], "audience": ["fitness", "parent", "wellness"]},
    "Beauty": {"keywords": ["makeup", "beauty", "glow", "hair", "routine"], "objects": ["person", "mirror", "hair brush"], "audience": ["style", "beauty", "creator"]},
    "Skincare": {"keywords": ["skin", "serum", "spf", "acne", "moisturizer"], "objects": ["person", "bottle", "mirror"], "audience": ["beauty", "wellness", "lifestyle"]},
    "Fashion": {"keywords": ["outfit", "style", "shoes", "clothing", "look"], "objects": ["shoe", "handbag", "tie"], "audience": ["style", "shopping", "lifestyle"]},
    "Luxury": {"keywords": ["luxury", "premium", "designer", "watch", "exclusive"], "objects": ["watch", "handbag", "tie"], "audience": ["premium", "fashion", "travel"]},
    "Travel": {"keywords": ["travel", "flight", "hotel", "trip", "city"], "objects": ["suitcase", "backpack", "airplane"], "audience": ["traveler", "family", "creator"]},
    "Hospitality": {"keywords": ["hotel", "stay", "restaurant", "service", "booking"], "objects": ["bed", "dining table", "cup"], "audience": ["traveler", "couple", "family"]},
    "Food": {"keywords": ["food", "recipe", "cook", "restaurant", "taste"], "objects": ["bowl", "plate", "pizza", "sandwich"], "audience": ["home", "family", "foodie"]},
    "Coffee": {"keywords": ["coffee", "morning", "energy", "routine", "break"], "objects": ["cup", "bottle", "dining table"], "audience": ["student", "professional", "creator"]},
    "Gaming": {"keywords": ["game", "stream", "console", "player", "level"], "objects": ["tv", "laptop", "keyboard", "mouse"], "audience": ["gamer", "streamer", "student"]},
    "Entertainment": {"keywords": ["show", "music", "movie", "story", "fun"], "objects": ["tv", "person", "cell phone"], "audience": ["fan", "creator", "viewer"]},
    "Education": {"keywords": ["learn", "course", "student", "lesson", "explain"], "objects": ["book", "laptop", "desk"], "audience": ["student", "teacher", "professional"]},
    "Parenting": {"keywords": ["kid", "child", "family", "baby", "parent"], "objects": ["person", "book", "chair"], "audience": ["parent", "family", "home"]},
    "Home": {"keywords": ["home", "clean", "setup", "room", "decor"], "objects": ["chair", "couch", "bed", "potted plant"], "audience": ["family", "owner", "lifestyle"]},
    "Automotive": {"keywords": ["car", "drive", "vehicle", "engine", "auto"], "objects": ["car", "truck", "motorcycle"], "audience": ["driver", "traveler", "family"]},
    "Mobility": {"keywords": ["ride", "commute", "bike", "scooter", "transport"], "objects": ["bicycle", "motorcycle", "car"], "audience": ["commuter", "student", "city"]},
    "Creator Tools": {"keywords": ["camera", "video", "recording", "studio", "content"], "objects": ["camera", "laptop", "cell phone"], "audience": ["creator", "editor", "streamer"]},
    "Camera Gear": {"keywords": ["camera", "lens", "shoot", "photo", "studio"], "objects": ["camera", "tripod", "cell phone"], "audience": ["creator", "photographer", "traveler"]},
    "Audio Gear": {"keywords": ["audio", "mic", "sound", "podcast", "recording"], "objects": ["microphone", "headphones", "laptop"], "audience": ["podcaster", "creator", "musician"]},
    "Mobile Apps": {"keywords": ["app", "phone", "download", "mobile", "notification"], "objects": ["cell phone", "laptop"], "audience": ["student", "creator", "shopper"]},
    "Ecommerce": {"keywords": ["shop", "buy", "deal", "product", "cart"], "objects": ["cell phone", "laptop", "handbag"], "audience": ["shopper", "style", "family"]},
    "Retail": {"keywords": ["store", "sale", "shopping", "brand", "product"], "objects": ["handbag", "shoe", "backpack"], "audience": ["shopper", "family", "style"]},
    "Health": {"keywords": ["health", "doctor", "sleep", "stress", "wellness"], "objects": ["person", "bed", "bottle"], "audience": ["wellness", "family", "professional"]},
    "Mental Wellness": {"keywords": ["stress", "sleep", "focus", "calm", "mind"], "objects": ["person", "bed", "book"], "audience": ["student", "professional", "wellness"]},
    "Pets": {"keywords": ["pet", "dog", "cat", "care", "animal"], "objects": ["dog", "cat", "person"], "audience": ["pet owner", "family", "home"]},
    "Sports": {"keywords": ["sport", "team", "match", "training", "player"], "objects": ["sports ball", "person", "tennis racket"], "audience": ["athlete", "fan", "coach"]},
    "Outdoor": {"keywords": ["outdoor", "hike", "camp", "travel", "adventure"], "objects": ["backpack", "bottle", "person"], "audience": ["traveler", "fitness", "creator"]},
    "Sustainability": {"keywords": ["green", "eco", "recycle", "sustainable", "clean"], "objects": ["potted plant", "bottle", "person"], "audience": ["family", "student", "home"]},
    "Real Estate": {"keywords": ["home", "rent", "property", "room", "mortgage"], "objects": ["house", "bed", "couch"], "audience": ["buyer", "family", "owner"]},
    "Careers": {"keywords": ["career", "job", "interview", "resume", "work"], "objects": ["laptop", "book", "desk"], "audience": ["student", "professional", "founder"]},
}

AD_INTENTS = [
    "Awareness", "Tutorial", "Review", "Comparison", "Demo", "Routine", "Challenge", "Launch",
    "Discount", "Premium", "Beginner", "Professional", "Family", "Student", "Creator", "Travel",
]


def build_ad_catalog() -> list[dict[str, Any]]:
    catalog = [dict(item) for item in BASE_AD_CATALOG]
    for vertical, signals in AD_VERTICALS.items():
        for intent in AD_INTENTS:
            catalog.append(
                {
                    "category": f"{vertical} - {intent}",
                    "keywords": list(dict.fromkeys(signals["keywords"] + [vertical.lower(), intent.lower()])),
                    "objects": signals["objects"],
                    "audience": list(dict.fromkeys(signals["audience"] + [intent.lower()])),
                }
            )
    return catalog


AD_CATALOG = build_ad_catalog()

HOOK_TERMS = [
    "how", "why", "what if", "today", "before", "after", "mistake", "secret", "show you", "watch",
    "कैसे", "क्यों", "क्या", "आज", "गलती", "राज़", "kaise", "kyun", "kya", "dekho",
]
CTA_TERMS = [
    "subscribe", "try", "buy", "click", "comment", "save", "share", "check out", "download", "follow",
    "खरीदें", "खरीदो", "क्लिक", "सब्सक्राइब", "फॉलो", "डाउनलोड", "शेयर", "kharido", "subscribe karo", "follow karo",
]
CLAIM_TERMS = ["guaranteed", "cure", "best", "number one", "risk free", "instant", "always", "never", "proven"]
RISK_TERMS = {
    "profanity": ["damn", "hell", "shit", "fuck"],
    "hate_or_abuse": ["hate", "kill", "attack", "idiot", "stupid"],
    "sexual_content": ["sex", "nude", "explicit"],
    "violence": ["weapon", "gun", "blood", "fight", "violent"],
    "drug_alcohol": ["drugs", "weed", "cocaine", "alcohol", "drunk"],
    "political_sensitive": ["election", "politics", "government", "party"],
}

GENERIC_CONTEXT_OBJECTS = {
    "person",
    "detailed scene",
    "colorful scene",
    "bright scene",
    "low light scene",
}

PRODUCT_CONTEXT_OBJECTS = {
    "bottle",
    "cup",
    "sports ball",
    "bowl",
    "plate",
    "laptop",
    "cell phone",
    "camera",
    "keyboard",
    "shoe",
    "handbag",
    "suitcase",
    "backpack",
}

COCO_LABELS = [
    "background",
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "street sign",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "hat",
    "backpack",
    "umbrella",
    "shoe",
    "eye glasses",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "plate",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "mirror",
    "dining table",
    "window",
    "desk",
    "toilet",
    "door",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "blender",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
    "hair brush",
]


def ensure_storage_dirs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for directory in [UPLOAD_DIR, FRAME_DIR, AUDIO_DIR, REPORT_DIR, MODEL_DIR, SCRATCH_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def enforce_source_duration(duration_seconds: int | float) -> None:
    if MAX_SOURCE_SECONDS > 0 and duration_seconds > MAX_SOURCE_SECONDS:
        limit_minutes = MAX_SOURCE_SECONDS / 60
        raise ValueError(f"Video duration exceeds the configured {limit_minutes:g} minute limit.")


def runtime_dependency_status() -> dict[str, Any]:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    uvr_command = os.getenv("NEUROAD_UVR_COMMAND", "audio-separator")
    uvr_path = shutil.which(uvr_command)
    yt_dlp_available = importlib.util.find_spec("yt_dlp") is not None
    vosk_available = importlib.util.find_spec("vosk") is not None
    faster_whisper_available = importlib.util.find_spec("faster_whisper") is not None
    ultralytics_available = importlib.util.find_spec("ultralytics") is not None
    pytesseract_available = importlib.util.find_spec("pytesseract") is not None
    tesseract_path = shutil.which("tesseract")
    runpod_settings = RunPodSettings.from_env()
    scenedetect_available = importlib.util.find_spec("scenedetect") is not None
    mediapipe_available = importlib.util.find_spec("mediapipe") is not None
    paddleocr_available = importlib.util.find_spec("paddleocr") is not None
    celery_enabled = env_enabled("NEUROAD_USE_CELERY", False)
    celery_available = importlib.util.find_spec("celery") is not None
    queue_ready = not celery_enabled
    queue_error: str | None = None
    if celery_enabled and celery_available:
        try:
            import redis

            client = redis.Redis.from_url(
                os.getenv("NEUROAD_REDIS_URL", "redis://redis:6379/0"),
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            queue_ready = bool(client.ping())
        except Exception as exc:
            queue_error = f"{type(exc).__name__}: {exc}"
    object_detection_enabled = env_enabled("NEUROAD_ENABLE_OBJECT_DETECTION", True)
    object_detection_engine = os.getenv("NEUROAD_OBJECT_DETECTION_ENGINE", "mobilenet_ssd").lower()
    production_environment = os.getenv("NEUROAD_ENVIRONMENT", "development").lower() == "production"
    ultralytics_license_accepted = env_enabled("NEUROAD_ULTRALYTICS_LICENSE_ACCEPTED", False)
    detector_license_ready = bool(
        object_detection_engine not in {"yolo", "yoloe"} or not production_environment or ultralytics_license_accepted
    )
    yolo_model_ready = YOLO_MODEL_PATH.is_file() and YOLO_MODEL_PATH.stat().st_size > 0
    yoloe_model_ready = YOLOE_MODEL_PATH.is_file() and YOLOE_MODEL_PATH.stat().st_size > 0
    mobilenet_ready = MOBILENET_SSD_GRAPH.is_file() and MOBILENET_SSD_CONFIG.is_file()
    primary_detector_ready = (
        not object_detection_enabled
        or (object_detection_engine == "yolo" and ultralytics_available and yolo_model_ready and detector_license_ready)
        or (object_detection_engine == "yoloe" and ultralytics_available and yoloe_model_ready and detector_license_ready)
        or (object_detection_engine == "mobilenet_ssd" and mobilenet_ready)
        or object_detection_engine in {"heuristic", "lightweight"}
    )
    return {
        "ffmpeg": {"available": bool(ffmpeg_path), "path": ffmpeg_path},
        "ffprobe": {"available": bool(ffprobe_path), "path": ffprobe_path},
        "yt_dlp": {"available": yt_dlp_available, "path": None},
        "audio_cleanup": {
            "enabled": env_enabled("NEUROAD_ENABLE_AUDIO_CLEANUP", False),
            "engine": os.getenv("NEUROAD_AUDIO_CLEANUP_ENGINE", "uvr"),
            "available": bool(uvr_path),
            "command": uvr_command,
            "path": uvr_path,
        },
        "vad": {
            "enabled": env_enabled("NEUROAD_ENABLE_VAD", False),
            "engine": "energy",
            "rms_threshold": float_from_env("NEUROAD_VAD_RMS_THRESHOLD", 0.012),
        },
        "vosk": {"available": vosk_available, "model_path": str(VOSK_MODEL_DIR), "model_ready": VOSK_MODEL_DIR.exists()},
        "faster_whisper": {
            "available": faster_whisper_available,
            "model": os.getenv("WHISPER_MODEL", "small"),
            "device": os.getenv("WHISPER_DEVICE", "cpu"),
            "compute_type": os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            "model_dir": str(MODEL_DIR),
        },
        "mobilenet_ssd": {
            "available": mobilenet_ready,
            "graph_path": str(MOBILENET_SSD_GRAPH),
            "config_path": str(MOBILENET_SSD_CONFIG),
        },
        "ultralytics": {
            "available": ultralytics_available, "model_path": str(YOLO_MODEL_PATH), "model_ready": YOLO_MODEL_PATH.exists(),
            "cached": YOLO_MODEL_CACHE is not None, "confidence": YOLO_CONFIDENCE, "image_size": YOLO_IMAGE_SIZE,
            "fallback_reason": OBJECT_DETECTOR_FALLBACK_REASON,
        },
        "ocr": {"enabled": env_enabled("NEUROAD_ENABLE_OCR", True), "available": bool(pytesseract_available and tesseract_path), "tesseract_path": tesseract_path, "confidence": OCR_CONFIDENCE},
        "runpod": {
            **runpod_settings.public_status(),
            "enabled": runpod_insights_enabled(runpod_settings),
        },
        "object_detection": {
            "enabled": object_detection_enabled,
            "requested_engine": object_detection_engine,
            "primary_ready": primary_detector_ready,
            "active_detector": OBJECT_DETECTION_RUNTIME.get("active_detector", "unavailable"),
            "fallback_reason": OBJECT_DETECTION_RUNTIME.get("fallback_reason"),
            "degraded": bool(object_detection_enabled and not primary_detector_ready),
            "license_gate": {
                "required": bool(production_environment and object_detection_engine in {"yolo", "yoloe"}),
                "passed": detector_license_ready,
                "acknowledged": ultralytics_license_accepted,
            },
        },
        "scene_detection": {"available": scenedetect_available, "engine": "pyscenedetect"},
        "face_landmarker": {
            "available": mediapipe_available,
            "model_path": str(MEDIAPIPE_FACE_MODEL),
            "model_ready": MEDIAPIPE_FACE_MODEL.is_file(),
            "identity_or_emotion_inference": False,
        },
        "ocr": {"available": paddleocr_available, "engine": "paddleocr_ppocrv5"},
        "jobs": {
            "engine": "celery" if celery_enabled else "in_process",
            "available": celery_available if celery_enabled else True,
            "ready": queue_ready,
            "broker": os.getenv("NEUROAD_REDIS_URL", "redis://redis:6379/0") if celery_enabled else None,
            "error": queue_error,
        },
    }


def runpod_insights_enabled(settings: RunPodSettings | None = None) -> bool:
    settings = settings or RunPodSettings.from_env()
    configured_default = settings.configured
    return env_enabled("NEUROAD_ENABLE_RUNPOD_INSIGHTS", configured_default)


def runpod_configuration_error(settings: RunPodSettings | None = None) -> str:
    settings = settings or RunPodSettings.from_env()
    missing: list[str] = []
    if not settings.api_key:
        missing.append("RUNPOD_API_KEY")
    if not settings.base_url:
        missing.append("RUNPOD_ENDPOINT_ID or RUNPOD_BASE_URL")
    if not runpod_insights_enabled(settings):
        missing.append("NEUROAD_ENABLE_RUNPOD_INSIGHTS=1")
    if not missing:
        return "RunPod insight generation is not configured."
    return f"Detailed reports require {', '.join(missing)} on the Railway API service."


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    init_admin_platform(ADMIN_SERVICES)
    recover_insight_jobs()
    try:
        yield
    finally:
        shutdown_analytics()


ensure_storage_dirs()
app = FastAPI(title="NeuroAd Context Engine API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(set(cors_origins_from_env()).union(admin_cors_origins_from_env())),
    allow_origin_regex=local_network_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=str(STORAGE_DIR)), name="media")


@app.middleware("http")
async def internal_admin_boundary_and_metrics(request: FastAPIRequest, call_next: Any) -> Response:
    """Keep the private control plane origin-bound and capture privacy-safe metrics."""
    path = request.url.path
    origin = request.headers.get("origin")
    if path.startswith("/internal/admin/") and origin and origin not in admin_cors_origins_from_env():
        return Response(status_code=403, content="Internal dashboard origin is not allowed.")
    started = time.perf_counter()
    response = await call_next(request)
    if not path.startswith("/media/") and not path.startswith("/internal/admin/"):
        elapsed = int((time.perf_counter() - started) * 1000)
        route = re.sub(r"/(video|job|comparison|report|product|fit|batch)_[A-Za-z0-9]+", r"/{\1_id}", path)
        distinct_id = request.headers.get("x-posthog-distinct-id")
        event_name = {
            "/api/videos/upload": "video_upload",
            "/api/videos/url": "video_url_created",
            "/api/videos/youtube/ingest": "youtube_ingest",
            "/api/telemetry/pageview": "page_view",
            "/api/comparisons": "comparison_created",
        }.get(path, "api_request")
        if path.endswith("/product-fit"):
            event_name = "brand_fit_requested"
        elif path.endswith("/insight-reports"):
            event_name = "insight_report_requested"
        if event_name in {"comparison_created", "brand_fit_requested", "insight_report_requested"} and request.method != "POST":
            event_name = "api_request"
        record_admin_metric_event(
            ADMIN_SERVICES,
            scope="api",
            event_name=event_name,
            route=route[:180],
            status_code=response.status_code,
            duration_ms=elapsed,
            actor_id=distinct_id,
        )
        if event_name != "api_request":
            record_admin_metric_event(
                ADMIN_SERVICES,
                scope="product",
                event_name=event_name,
                route=route[:180],
                status_code=response.status_code,
                duration_ms=elapsed,
                actor_id=distinct_id,
            )
    return response


@app.post("/api/telemetry/pageview")
def record_privacy_safe_pageview() -> dict[str, bool]:
    """Creates a privacy-filtered activity record through the request middleware."""
    return {"ok": True}


class YouTubeRequest(BaseModel):
    url: str


class YouTubeIngestRequest(BaseModel):
    url: str
    has_permission: bool = False


class VideoUrlRequest(BaseModel):
    url: str


class ComparisonCreateRequest(BaseModel):
    title: Optional[str] = None


class ComparisonAnalyzeRequest(BaseModel):
    video_ids: Optional[list[str]] = None


class DirectUploadInitRequest(BaseModel):
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    comparison_id: Optional[str] = None
    allow_internal_training: bool = False


class DirectUploadCompleteRequest(BaseModel):
    comparison_id: Optional[str] = None


class ProductResolveRequest(BaseModel):
    url: str


class ProductCreateRequest(BaseModel):
    source_url: str
    name: str
    brand_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    keywords: Optional[list[str]] = None
    features: Optional[list[str]] = None
    use_cases: Optional[list[str]] = None
    audience: Optional[list[str]] = None
    prohibited_contexts: Optional[list[str]] = None
    image_url: Optional[str] = None
    extraction_confidence: Optional[int] = None
    field_sources: Optional[dict[str, str]] = None
    field_confidence: Optional[dict[str, int]] = None
    warnings: Optional[list[str]] = None
    profile_version: Optional[str] = None


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    brand_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    keywords: Optional[list[str]] = None
    features: Optional[list[str]] = None
    use_cases: Optional[list[str]] = None
    audience: Optional[list[str]] = None
    prohibited_contexts: Optional[list[str]] = None
    image_url: Optional[str] = None
    field_sources: Optional[dict[str, str]] = None
    field_confidence: Optional[dict[str, int]] = None
    warnings: Optional[list[str]] = None


class ProductFitRequest(BaseModel):
    product_id: str


class EvidenceReviewCreateRequest(BaseModel):
    analysis_run_id: str
    segment_id: Optional[str] = None
    assignment: Optional[str] = None


class EvidenceReviewUpdateRequest(BaseModel):
    state: str
    notes: Optional[str] = None
    reviewer: Optional[str] = None
    assignment: Optional[str] = None


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def media_url(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        rel = path.resolve().relative_to(STORAGE_DIR.resolve())
    except ValueError:
        return None
    if OBJECT_STORAGE.ready:
        return f"/api/media/{rel.as_posix()}"
    return f"/media/{rel.as_posix()}"


def object_key_for_local_path(path: Path) -> str:
    """Return the durable object key matching a local storage artifact."""
    try:
        return path.resolve().relative_to(STORAGE_DIR.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Only NeuroAd storage artifacts can be uploaded to object storage.") from exc


def r2_key_from_reference(reference: str | None) -> str | None:
    return OBJECT_STORAGE.key_from_uri(reference or "") if OBJECT_STORAGE.ready else None


def media_url_for_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    key = r2_key_from_reference(reference)
    if key:
        return f"/api/media/{key}"
    return media_url(Path(reference))


def materialize_source_for_processing(reference: str, video_id: str) -> Path:
    """Download an R2 source to local scratch; local legacy paths pass through."""
    key = r2_key_from_reference(reference)
    if not key:
        return Path(reference)
    suffix = Path(key).suffix or ".mp4"
    target = SCRATCH_DIR / video_id / f"source{suffix}"
    return OBJECT_STORAGE.download_file(key, target)


def upload_durable_artifacts(video_id: str) -> None:
    """Persist user-visible evidence and exports after local analysis completes."""
    if not OBJECT_STORAGE.ready:
        return
    roots = [FRAME_DIR / video_id, REPORT_DIR / video_id]
    roots.extend([REPORT_DIR / f"{video_id}.json", REPORT_DIR / f"{video_id}.csv"])
    for root in roots:
        paths = root.rglob("*") if root.is_dir() else [root]
        for path in paths:
            if path.is_file():
                OBJECT_STORAGE.upload_file(path, object_key_for_local_path(path), content_type_for_suffix(path.suffix))


def cleanup_r2_scratch(video_id: str) -> None:
    shutil.rmtree(SCRATCH_DIR / video_id, ignore_errors=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)
        conn.commit()


def query_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def analytics_context_from_request(request: FastAPIRequest) -> AnalyticsContext:
    return AnalyticsContext.from_headers(request.headers)


def analytics_context_from_row(row: sqlite3.Row | dict[str, Any] | None) -> AnalyticsContext:
    if not row:
        return AnalyticsContext()
    keys = set(row.keys())
    return AnalyticsContext(
        distinct_id=row["analytics_distinct_id"] if "analytics_distinct_id" in keys else None,
        session_id=row["analytics_session_id"] if "analytics_session_id" in keys else None,
    )


def duration_bucket(duration_seconds: int | float) -> str:
    duration = max(0, float(duration_seconds or 0))
    if duration < 60:
        return "under_1m"
    if duration < 300:
        return "1_5m"
    if duration < 600:
        return "5_10m"
    return "over_10m"


def elapsed_ms(created_at: str | None) -> int | None:
    if not created_at:
        return None
    try:
        return max(0, int((datetime.now() - datetime.fromisoformat(created_at)).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def analytics_error_code(error: Exception | str) -> str:
    message = str(error).lower()
    if "too large" in message or "exceeds" in message:
        return "upload_too_large"
    if "timeout" in message or "taking too long" in message:
        return "processing_timeout"
    if "youtube" in message or "sign in to confirm" in message:
        return "youtube_access_blocked"
    if "ffmpeg" in message or "media processing" in message:
        return "media_processing_failed"
    if "transcri" in message or "whisper" in message:
        return "transcription_failed"
    if "runpod" in message or "insight" in message:
        return "insight_generation_failed"
    return "processing_failed"


def init_db() -> None:
    ensure_storage_dirs()
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists videos (
              id text primary key,
              source_type text not null,
              source_url text,
              title text not null,
              description text,
              thumbnail_url text,
              duration_seconds integer default 0,
              status text not null,
              file_path text,
              embed_url text,
              created_at text not null
            );

            create table if not exists jobs (
              id text primary key,
              video_id text not null,
              status text not null,
              progress integer default 0,
              current_step text,
              error text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists segments (
              id text primary key,
              video_id text not null,
              start_time real not null,
              end_time real not null,
              attention_score real not null,
              ad_fit_score real not null,
              drop_risk_score real default 0,
              brand_safety_score real default 100,
              label text not null,
              summary text not null,
              transcript text,
              transcript_insights text,
              visual_evidence text,
              score_reasons text,
              recommendation text,
              recommendation_tier text default 'Edit before monetization',
              recommendation_confidence real default 0,
              evidence_mode text default 'weak_evidence',
              strong_signals text,
              failed_or_weak_signals text,
              thumbnail_url text,
              created_at text not null
            );

            create table if not exists detected_objects (
              id text primary key,
              segment_id text not null,
              label text not null,
              confidence real not null,
              bbox text,
              frame_timestamp real,
              track_id text,
              detector text,
              instance_index integer default 0,
              mask text,
              evidence_kind text default 'object',
              created_at text not null
            );

            create table if not exists analysis_runs (
              id text primary key,
              video_id text not null,
              schema_version text not null,
              state text not null,
              source_hash text,
              model_manifest text,
              signal_availability text,
              timings text,
              error text,
              started_at text not null,
              completed_at text
            );

            create table if not exists segment_signals (
              id text primary key,
              analysis_run_id text not null,
              segment_id text not null,
              family text not null,
              summary text not null,
              confidence real not null,
              created_at text not null
            );

            create table if not exists signal_samples (
              id text primary key,
              analysis_run_id text not null,
              segment_id text,
              family text not null,
              signal_name text not null,
              timestamp real not null,
              value real,
              confidence real,
              metadata text,
              created_at text not null
            );

            create table if not exists object_tracks (
              id text primary key,
              analysis_run_id text not null,
              video_id text not null,
              track_id text not null,
              label text not null,
              confidence real not null,
              first_seen real not null,
              last_seen real not null,
              detector text not null,
              observations text,
              created_at text not null,
              unique(analysis_run_id, track_id)
            );

            create table if not exists evidence_artifacts (
              id text primary key,
              analysis_run_id text not null,
              segment_id text,
              artifact_type text not null,
              timestamp real,
              uri text,
              payload text,
              confidence real,
              created_at text not null
            );

            create table if not exists decision_metrics (
              id text primary key,
              analysis_run_id text not null,
              metric_key text not null,
              label text not null,
              internal_score real,
              confidence real not null,
              start_time real,
              end_time real,
              reasons text,
              next_action text,
              created_at text not null
            );

            create table if not exists evidence_review_tasks (
              id text primary key,
              analysis_run_id text not null,
              segment_id text,
              assignment text,
              state text not null default 'unreviewed',
              notes text,
              reviewer text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists model_manifests (
              id text primary key,
              analysis_run_id text not null,
              extractor text not null,
              library_version text,
              model_version text,
              weight_checksum text,
              configuration text,
              calibration_version text,
              created_at text not null
            );

            create table if not exists detected_text (
              id text primary key,
              segment_id text not null,
              text text not null,
              confidence real not null,
              bbox text,
              frame_timestamp real,
              created_at text not null
            );

            create table if not exists extractor_cache (
              cache_key text primary key,
              source_hash text not null,
              extractor text not null,
              extractor_version text not null,
              configuration_hash text not null,
              payload text not null,
              created_at text not null,
              last_accessed_at text not null
            );

            create index if not exists idx_extractor_cache_source
            on extractor_cache(source_hash, extractor);

            create table if not exists topics (
              id text primary key,
              segment_id text not null,
              label text not null,
              confidence real not null,
              created_at text not null
            );

            create table if not exists ad_matches (
              id text primary key,
              segment_id text not null,
              ad_category text not null,
              ad_fit_score real not null,
              reason text not null,
              confidence real not null,
              created_at text not null
            );

            create table if not exists reports (
              id text primary key,
              video_id text not null,
              summary text not null,
              csv_path text,
              json_path text,
              created_at text not null
            );

            create table if not exists ai_insights (
              video_id text primary key,
              provider text not null,
              model text not null,
              status text not null,
              content_json text,
              error text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists insight_reports (
              id text primary key,
              target_type text not null,
              target_id text not null,
              report_type text not null,
              input_fingerprint text not null,
              prompt_version text not null,
              provider text not null,
              model text not null,
              status text not null,
              content_json text,
              pdf_path text,
              json_path text,
              created_at text not null,
              updated_at text not null,
              unique(target_type, target_id, input_fingerprint, prompt_version)
            );

            create table if not exists insight_jobs (
              id text primary key,
              report_id text not null,
              target_type text not null,
              target_id text not null,
              input_fingerprint text not null,
              prompt_version text not null,
              status text not null,
              progress integer default 0,
              stage text not null,
              model text not null,
              error text,
              attempts integer default 0,
              created_at text not null,
              updated_at text not null
            );

            create index if not exists idx_insight_jobs_target
              on insight_jobs(target_type, target_id, input_fingerprint, prompt_version);
            create index if not exists idx_insight_reports_target
              on insight_reports(target_type, target_id, input_fingerprint, prompt_version);

            create table if not exists comparisons (
              id text primary key,
              title text not null,
              status text not null,
              comparison_mode text default 'pending',
              inferred_category text,
              total_videos integer default 0,
              completed_videos integer default 0,
              failed_videos integer default 0,
              summary text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists comparison_videos (
              id text primary key,
              comparison_id text not null,
              video_id text not null,
              display_order integer not null,
              inferred_category text,
              category_confidence real default 0,
              processing_status text not null default 'uploaded',
              error text,
              created_at text not null,
              unique(comparison_id, video_id)
            );

            create table if not exists comparison_reports (
              id text primary key,
              comparison_id text not null,
              summary text not null,
              csv_path text,
              json_path text,
              created_at text not null
            );

            create table if not exists products (
              id text primary key,
              source_url text not null,
              canonical_url text,
              name text not null,
              brand_name text,
              description text,
              category text,
              keywords text,
              features text,
              use_cases text,
              audience text,
              prohibited_contexts text,
              image_url text,
              extraction_confidence integer default 0,
              field_sources text,
              field_confidence text,
              warnings text,
              profile_fingerprint text,
              profile_version text default '2.0',
              status text not null default 'verified',
              created_at text not null,
              updated_at text not null
            );

            create table if not exists product_snapshots (
              id text primary key,
              product_id text not null,
              raw_metadata text not null,
              extracted_at text not null,
              fetch_status text not null
            );

            create table if not exists product_resolution_cache (
              canonical_url text primary key,
              payload text not null,
              fetched_at text not null
            );

            create table if not exists product_fit_runs (
              id text primary key,
              product_id text not null,
              video_id text not null,
              comparison_id text,
              overall_fit_score integer not null,
              fit_confidence integer not null,
              suitability_tier text not null,
              summary text not null,
              product_fingerprint text,
              video_fingerprint text,
              scoring_version text,
              details_json text,
              created_at text not null
            );

            create table if not exists product_placements (
              id text primary key,
              product_fit_run_id text not null,
              segment_id text not null,
              placement_score integer not null,
              placement_type text not null,
              recommendation text not null,
              reasons text not null,
              product_relevance_score integer default 0,
              placement_readiness_score integer default 0,
              component_breakdown text,
              positive_evidence text,
              conflicting_evidence text,
              limitations text,
              evidence_coverage text,
              transcript_excerpt text,
              relevant_topics text,
              relevant_objects text,
              suggested_duration text,
              is_best_placement integer default 0,
              created_at text not null
            );
            """
        )
        ensure_table_columns(
            conn,
            "segments",
            {
                "drop_risk_score": "real default 0",
                "brand_safety_score": "real default 100",
                "transcript_insights": "text",
                "visual_evidence": "text",
                "score_reasons": "text",
                "recommendation_tier": "text default 'Edit before monetization'",
                "recommendation_confidence": "real default 0",
                "evidence_mode": "text default 'weak_evidence'",
                "strong_signals": "text",
                "failed_or_weak_signals": "text",
                "ad_slot_score": "real default 0",
                "ad_slot_reasons": "text",
                "is_best_ad_slot": "integer default 0",
                "audio_evidence": "text",
                "narrative_evidence": "text",
                "social_evidence": "text",
                "ocr_evidence": "text",
                "signal_summary": "text",
                "detector_provenance": "text",
                "review_state": "text default 'unreviewed'",
            },
        )
        ensure_table_columns(
            conn,
            "detected_objects",
            {
                "track_id": "text",
                "detector": "text",
                "instance_index": "integer default 0",
                "mask": "text",
                "evidence_kind": "text default 'object'",
            },
        )
        ensure_table_columns(
            conn,
            "jobs",
            {
                "comparison_id": "text",
                "comparison_video_id": "text",
                "analytics_distinct_id": "text",
                "analytics_session_id": "text",
            },
        )
        ensure_table_columns(
            conn,
            "comparisons",
            {
                "analytics_distinct_id": "text",
                "analytics_session_id": "text",
            },
        )
        ensure_table_columns(
            conn,
            "insight_jobs",
            {
                "analytics_distinct_id": "text",
                "analytics_session_id": "text",
            },
        )
        ensure_table_columns(
            conn,
            "products",
            {
                "features": "text",
                "use_cases": "text",
                "field_sources": "text",
                "field_confidence": "text",
                "warnings": "text",
                "profile_fingerprint": "text",
                "profile_version": "text default '2.0'",
            },
        )
        ensure_table_columns(
            conn,
            "product_fit_runs",
            {
                "product_fingerprint": "text",
                "video_fingerprint": "text",
                "scoring_version": "text",
                "details_json": "text",
            },
        )
        ensure_table_columns(
            conn,
            "product_placements",
            {
                "product_relevance_score": "integer default 0",
                "placement_readiness_score": "integer default 0",
                "component_breakdown": "text",
                "positive_evidence": "text",
                "conflicting_evidence": "text",
                "limitations": "text",
                "evidence_coverage": "text",
                "transcript_excerpt": "text",
                "relevant_topics": "text",
                "relevant_objects": "text",
                "suggested_duration": "text",
            },
        )
        conn.commit()


def ensure_table_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"alter table {table} add column {column} {definition}")


def parse_youtube_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    if "youtube.com" in parsed.netloc:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2]
    return None


def video_suffix_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in ALLOWED_EXTENSIONS else None


def convertible_video_suffix_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in CONVERTIBLE_VIDEO_EXTENSIONS else None


class ProductPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            value = values.get("content")
            if key and value and key not in self.meta:
                self.meta[key] = value.strip()
        elif tag.lower() == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()
        elif tag.lower() == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld.append("".join(self._json_ld_parts))
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_json_ld:
            self._json_ld_parts.append(data)


def validate_public_product_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Use a public http(s) product or brand URL.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "0.0.0.0", "::1"} or hostname.endswith(".local"):
        raise HTTPException(status_code=400, detail="Local or private product URLs are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)}
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="The product URL host could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="Private network product URLs are not allowed.")
    return parsed.geturl()


class ProductRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        safe_url = validate_public_product_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def normalize_profile_terms(values: list[str] | None) -> list[str]:
    if not values:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = re.sub(r"\s+", " ", str(value).strip().lower())
        if term and term not in seen:
            seen.add(term)
            output.append(term[:80])
    return output[:30]


PRODUCT_GENERIC_TERMS = {
    "best", "brand", "buy", "company", "great", "high", "item", "new", "official",
    "person", "premium", "product", "quality", "shop", "solution", "store", "thing",
}

PRODUCT_CATEGORY_ALIASES = {
    "beverage": ["drink"],
    "functional beverage": ["electrolyte drink", "hydration drink", "sports drink"],
    "fitness": ["exercise", "training", "workout", "running"],
    "food": ["meal", "snack"],
    "skincare": ["skin care", "beauty"],
    "technology": ["tech", "software", "device"],
    "travel": ["trip", "journey"],
}


def normalize_product_term(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    words = []
    for word in normalized.split():
        if len(word) > 4 and word.endswith("ies"):
            word = f"{word[:-3]}y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return " ".join(words)


def canonical_product_url(url: str) -> str:
    safe_url = validate_public_product_url(url)
    parsed = urlparse(safe_url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    netloc = hostname if not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443) else f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, fragment="").geturl()


def meaningful_product_terms(text: str, limit: int = 12) -> list[str]:
    tokens = [
        normalize_product_term(token)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", text)
    ]
    tokens = [token for token in tokens if token and token not in PRODUCT_GENERIC_TERMS]
    counts = Counter(tokens)
    return [term for term, _ in counts.most_common(limit)]


def product_profile_fingerprint(profile: dict[str, Any]) -> str:
    stable = {
        "source_url": str(profile.get("canonical_url") or profile.get("source_url") or "").strip(),
        "name": str(profile.get("name") or "").strip(),
        "brand_name": str(profile.get("brand_name") or "").strip(),
        "description": str(profile.get("description") or "").strip(),
        "category": str(profile.get("category") or "").strip(),
        "keywords": normalize_profile_terms(profile.get("keywords", [])),
        "features": normalize_profile_terms(profile.get("features", [])),
        "use_cases": normalize_profile_terms(profile.get("use_cases", [])),
        "audience": normalize_profile_terms(profile.get("audience", [])),
        "prohibited_contexts": normalize_profile_terms(profile.get("prohibited_contexts", [])),
        "profile_version": PRODUCT_PROFILE_VERSION,
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def product_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nodes = [value]
        graph = value.get("@graph")
        if isinstance(graph, list):
            nodes.extend(item for item in graph if isinstance(item, dict))
        return nodes
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def extract_product_profile(url: str) -> dict[str, Any]:
    safe_url = validate_public_product_url(url)
    request = Request(safe_url, headers={"User-Agent": "NeuroAdProductFit/1.0", "Accept": "text/html,application/xhtml+xml"})
    opener = build_opener(ProductRedirectHandler())
    try:
        with opener.open(request, timeout=10) as response:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "html" not in content_type and "xhtml" not in content_type:
                raise HTTPException(status_code=400, detail="The product URL did not return an HTML product page.")
            final_url = validate_public_product_url(response.geturl())
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise HTTPException(status_code=400, detail="The product page is too large to analyze safely.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not retrieve product metadata from this URL. Add the product details manually.") from exc

    parser = ProductPageParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    structured: dict[str, Any] = {}
    for source in parser.json_ld:
        try:
            payload = json.loads(source)
        except json.JSONDecodeError:
            continue
        for node in product_nodes(payload):
            types = node.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any(str(item).lower() == "product" for item in types):
                structured = node
                break
        if structured:
            break

    brand = structured.get("brand") if structured else None
    brand_name = brand.get("name") if isinstance(brand, dict) else brand
    image = structured.get("image") if structured else None
    if isinstance(image, list):
        image = image[0] if image else None
    name = (
        structured.get("name") if structured else None
    ) or parser.meta.get("og:title") or parser.meta.get("twitter:title") or parser.title
    description = (
        structured.get("description") if structured else None
    ) or parser.meta.get("og:description") or parser.meta.get("description") or ""
    category = (structured.get("category") if structured else None) or parser.meta.get("product:category") or ""
    image_url = image or parser.meta.get("og:image") or parser.meta.get("twitter:image")
    additional_properties = structured.get("additionalProperty", []) if structured else []
    if isinstance(additional_properties, dict):
        additional_properties = [additional_properties]
    structured_features = []
    for item in additional_properties if isinstance(additional_properties, list) else []:
        if not isinstance(item, dict):
            continue
        feature = " ".join(str(item.get(key) or "").strip() for key in ("name", "value")).strip()
        if feature:
            structured_features.append(feature)
    ingredients = structured.get("ingredients") if structured else None
    if isinstance(ingredients, str):
        structured_features.extend(part.strip() for part in re.split(r"[,;]", ingredients) if part.strip())
    keyword_seed = " ".join([str(name or ""), str(description), str(category), str(brand_name or "")])
    keywords = meaningful_product_terms(keyword_seed)
    features = normalize_profile_terms(structured_features + meaningful_product_terms(str(description), 8))
    confidence = 0
    if structured:
        confidence += 45
    if parser.meta.get("og:title") or parser.title:
        confidence += 20
    if description:
        confidence += 20
    if brand_name or category:
        confidence += 15
    structured_source = "JSON-LD" if structured else "Page metadata"
    field_sources = {
        "name": structured_source if structured.get("name") else "Page metadata",
        "brand_name": "JSON-LD" if brand_name else "Page metadata",
        "description": "JSON-LD" if structured.get("description") else "Page metadata",
        "category": "JSON-LD" if structured.get("category") else "Page metadata",
        "features": "JSON-LD" if structured_features else "Derived from description",
        "keywords": "Derived from public metadata",
    }
    field_confidence = {
        "name": 95 if structured.get("name") else (75 if name else 20),
        "brand_name": 90 if brand_name else (55 if parser.meta.get("og:site_name") else 0),
        "description": 90 if structured.get("description") else (70 if description else 0),
        "category": 90 if structured.get("category") else (60 if category else 0),
        "features": 85 if structured_features else (45 if features else 0),
        "keywords": 60 if keywords else 0,
    }
    warnings = []
    if not brand_name:
        warnings.append("Brand name was not found; confirm it before analysis.")
    if not category:
        warnings.append("Category was not found; adding it will improve relevance scoring.")
    if not description:
        warnings.append("Product description was not found; add features and use cases manually.")
    return {
        "source_url": safe_url,
        "canonical_url": canonical_product_url(final_url),
        "name": str(name or "Product page").strip()[:160],
        "brand_name": str(brand_name or parser.meta.get("og:site_name") or "").strip()[:120] or None,
        "description": str(description).strip()[:2000],
        "category": str(category).strip()[:120] or None,
        "keywords": keywords,
        "features": features,
        "use_cases": [],
        "audience": [],
        "prohibited_contexts": [],
        "image_url": str(image_url).strip()[:1000] if image_url else None,
        "extraction_confidence": min(100, confidence),
        "field_sources": field_sources,
        "field_confidence": field_confidence,
        "warnings": warnings,
        "profile_version": PRODUCT_PROFILE_VERSION,
        "raw_metadata": {"title": parser.title, "meta": parser.meta, "structured_product": structured},
        "status": "needs_review",
    }


def extract_video_url_from_json(data: Any) -> str | None:
    """Recursively search for a valid video download URL in a generic JSON response."""
    if isinstance(data, dict):
        for key in ["link", "url", "downloadUrl", "download_url", "dlink"]:
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                if "googlevideo.com" in val or ".mp4" in val:
                    return val
        for val in data.values():
            result = extract_video_url_from_json(val)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = extract_video_url_from_json(item)
            if result:
                return result
    return None

def download_remote_video(url: str, video_id: str | None = None) -> tuple[Path, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Use an http(s) video URL.")
    if parse_youtube_id(url):
        raise HTTPException(
            status_code=400,
            detail="Use the YouTube permission path for YouTube URLs.",
        )

    suffix = convertible_video_suffix_from_url(url)
    if not suffix:
        return download_extractable_video(url, video_id)

    video_id = video_id or new_id("video")
    target = UPLOAD_DIR / f"{video_id}{suffix}"
    request = Request(url, headers={"User-Agent": "NeuroAdContextEngine/0.1"})
    size = 0
    try:
        with urlopen(request, timeout=30) as response, target.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=400, detail="Remote video exceeds the 200 MB MVP limit.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="Remote video exceeds the 200 MB MVP limit.")
                output.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not download the video URL: {exc}") from exc

    return target, video_id


def ytdlp_base_options(video_id: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/best[height<=720]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(UPLOAD_DIR / f"{video_id}.%(ext)s"),
        "noplaylist": True,
        "max_filesize": MAX_UPLOAD_BYTES,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "overwrites": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "force_ipv4": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
    }
    cookies_file = os.getenv("YTDLP_COOKIES_FILE")
    cookies_browser = os.getenv("YTDLP_COOKIES_BROWSER")

    default_storage_cookies = STORAGE_DIR / "cookies.txt"
    default_app_cookies = APP_DIR / "cookies.txt"

    if cookies_file:
        options["cookiefile"] = cookies_file
    elif default_storage_cookies.exists():
        options["cookiefile"] = str(default_storage_cookies)
    elif default_app_cookies.exists():
        options["cookiefile"] = str(default_app_cookies)
    elif cookies_browser:
        parts = cookies_browser.split(":", 1)
        browser = parts[0]
        profile = parts[1] if len(parts) > 1 and parts[1] else None
        options["cookiesfrombrowser"] = (browser, profile, None, None)
    return options


def find_downloaded_media(video_id: str, before: set[Path]) -> Path:
    downloaded = [path for path in UPLOAD_DIR.glob(f"{video_id}.*") if path not in before and path.suffix.lower() in CONVERTIBLE_VIDEO_EXTENSIONS]
    if not downloaded:
        downloaded = [path for path in UPLOAD_DIR.glob(f"{video_id}.*") if path.suffix.lower() in CONVERTIBLE_VIDEO_EXTENSIONS]
    if not downloaded:
        raise HTTPException(status_code=400, detail="The URL was reachable, but no downloadable video file was produced.")

    target = max(downloaded, key=lambda path: path.stat().st_size)
    if target.stat().st_size > MAX_UPLOAD_BYTES:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Downloaded video exceeds the 200 MB MVP limit.")
    return target


def download_extractable_video(url: str, video_id: str | None = None) -> tuple[Path, str]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(status_code=400, detail="FFmpeg and FFprobe are required before URL extraction can run.")
    try:
        import yt_dlp
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="yt-dlp is not installed in the API environment.") from exc

    video_id = video_id or new_id("video")
    before = set(UPLOAD_DIR.glob(f"{video_id}.*"))
    try:
        with yt_dlp.YoutubeDL(ytdlp_base_options(video_id)) as downloader:
            downloader.extract_info(url, download=True)
    except Exception as exc:
        for path in UPLOAD_DIR.glob(f"{video_id}.*"):
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not extract a real video file from this URL. Paste a direct video file URL, use a supported public media page, "
                "or upload the file directly."
            ),
        ) from exc

    return find_downloaded_media(video_id, before), video_id


def download_youtube_video(url: str, video_id: str | None = None) -> tuple[Path, str, dict[str, Any]]:
    youtube_id = parse_youtube_id(url)
    if not youtube_id:
        raise HTTPException(status_code=400, detail="Use a valid public YouTube URL.")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(status_code=400, detail="FFmpeg and FFprobe are required before YouTube ingestion can run.")

    try:
        import yt_dlp
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="yt-dlp is not installed in the API environment.") from exc

    video_id = video_id or new_id("video")

    # 1. Try RapidAPI Proxy first
    rapidapi_key = os.getenv("RAPIDAPI_KEY")
    rapidapi_host = os.getenv("RAPIDAPI_HOST")
    rapidapi_url = os.getenv("RAPIDAPI_URL")
    proxy_target = None
    proxy_error_msg = None

    if rapidapi_key and rapidapi_host and rapidapi_url:
        # Some APIs expect ?id=, others ?url= or ?videoId=
        # We append all of them to be safe if the user didn't specify query params
        fetch_url = rapidapi_url
        if "?" not in fetch_url:
            fetch_url += f"?id={youtube_id}&url={url}&videoId={youtube_id}"

        headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": rapidapi_host,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        req = Request(fetch_url, headers=headers)

        try:
            with urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))

            download_url = extract_video_url_from_json(payload)
            if download_url:
                target_path = UPLOAD_DIR / f"{video_id}.mp4"
                req_file = Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
                size = 0
                with urlopen(req_file, timeout=60) as response_file, target_path.open("wb") as output:
                    while True:
                        chunk = response_file.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            target_path.unlink(missing_ok=True)
                            raise ValueError("Exceeds max upload bytes")
                        output.write(chunk)
                proxy_target = target_path
            else:
                proxy_error_msg = "RapidAPI returned success, but no MP4/Video link was found in the JSON."
        except Exception as exc:
            import urllib.error
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    proxy_error_msg = f"HTTP {exc.code} - {exc.read().decode()}"
                except Exception:
                    proxy_error_msg = f"HTTP {exc.code}"
            else:
                proxy_error_msg = str(exc)
            print(f"RapidAPI download failed: {proxy_error_msg}")

    if proxy_target and proxy_target.exists():
        metadata = fetch_youtube_metadata(url, youtube_id)
        return proxy_target, video_id, metadata

    # 2. Fallback to yt-dlp if proxy fails or is unconfigured
    base_opts = ytdlp_base_options(video_id)
    has_cookies = "cookiefile" in base_opts or "cookiesfrombrowser" in base_opts

    if has_cookies:
        # When cookies are present, try web clients first, then fallbacks.
        strategies = [
            ["web_safari", "web", "web_creator"],
            ["mweb", "tv"],
            ["tv_embedded", "web"]
        ]
    else:
        # Without cookies, try ios first (often bypasses bot checks), then tv/mweb.
        strategies = [
            ["ios", "android", "web_safari", "web"],
            ["tv", "mweb"],
            ["web_creator", "web"]
        ]

    last_exc = None
    info = None
    target = None

    for clients in strategies:
        options = ytdlp_base_options(video_id)
        options["http_headers"]["Referer"] = "https://www.youtube.com/"
        options["extractor_args"] = {"youtube": {"player_client": clients}}

        before = set(UPLOAD_DIR.glob(f"{video_id}.*"))
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
            target = find_downloaded_media(video_id, before)
            break  # Success!
        except Exception as exc:
            for path in UPLOAD_DIR.glob(f"{video_id}.*"):
                path.unlink(missing_ok=True)
            last_exc = exc
            message = str(exc)
            if "video not found" in message.lower() or "private video" in message.lower():
                # For definitive structural errors, stop retrying yt-dlp
                break
    else:
        # If we exhausted all yt-dlp strategies and still failed, try pytubefix as the ultimate fallback
        try:
            from pytubefix import YouTube
            import pytubefix.exceptions

            yt = YouTube(url)
            stream = yt.streams.get_highest_resolution()
            if not stream:
                raise Exception("No suitable video stream found by pytubefix.")

            target = UPLOAD_DIR / f"{video_id}.mp4"
            stream.download(output_path=str(UPLOAD_DIR), filename=f"{video_id}.mp4")

            metadata = {
                "youtube_id": yt.video_id,
                "title": yt.title or f"YouTube Video {yt.video_id}",
                "description": yt.description or "",
                "thumbnail_url": yt.thumbnail_url or f"https://img.youtube.com/vi/{yt.video_id}/hqdefault.jpg",
                "duration_seconds": int(yt.length or 0),
                "embed_url": f"https://www.youtube.com/embed/{yt.video_id}",
            }
            return target, video_id, metadata

        except Exception as p_exc:
            message = str(last_exc) if last_exc else "Unknown error"
            if "403" in message or "Forbidden" in message or "Sign in to confirm" in message:
                detail = (
                    "YouTube blocked the video stream on both yt-dlp and pytubefix. "
                    "Try a video you own that is public/unlisted, or upload the video file directly."
                )
            elif "The downloaded file is empty" in message:
                detail = (
                    "YouTube blocked the stream chunks. This usually means your server's IP is blocked via anti-bot checks. "
                    "Try uploading the MP4 video file directly."
                )
            else:
                detail = f"Could not ingest this YouTube URL. yt-dlp error: {message}. pytubefix error: {str(p_exc)}"

            if proxy_error_msg:
                detail = f"RapidAPI failed with: {proxy_error_msg}. Fallback also failed: {detail}"

            raise HTTPException(status_code=400, detail=detail) from p_exc

    if not info or not target:
        raise HTTPException(status_code=400, detail=f"Failed to fetch video information or file. {last_exc or ''}")

    metadata = {
        "youtube_id": youtube_id,
        "title": info.get("title") or f"YouTube Video {youtube_id}",
        "description": info.get("description") or "",
        "thumbnail_url": info.get("thumbnail") or f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg",
        "duration_seconds": int(info.get("duration") or 0),
        "embed_url": f"https://www.youtube.com/embed/{youtube_id}",
    }
    return target, video_id, metadata


def fetch_youtube_metadata(url: str, video_id: str) -> dict[str, Any]:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if api_key:
        api_url = (
            "https://www.googleapis.com/youtube/v3/videos"
            f"?part=snippet,contentDetails,statistics,topicDetails,paidProductPlacementDetails"
            f"&id={video_id}&key={api_key}"
        )
        with urlopen(api_url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("items", [])
        if items:
            item = items[0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            return {
                "title": snippet.get("title") or f"YouTube Video {video_id}",
                "description": snippet.get("description") or "",
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url")
                or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                "duration_seconds": parse_iso8601_duration(item.get("contentDetails", {}).get("duration", "")),
                "channel_title": snippet.get("channelTitle"),
                "view_count": int(stats.get("viewCount", 0)) if stats.get("viewCount") else None,
                "comment_count": int(stats.get("commentCount", 0)) if stats.get("commentCount") else None,
                "category_id": snippet.get("categoryId"),
            }
    return {
        "title": f"YouTube Video {video_id}",
        "description": "Metadata preview. Add YOUTUBE_API_KEY for full YouTube Data API fields.",
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration_seconds": 0,
    }


def parse_iso8601_duration(value: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    hours, minutes, seconds = [int(group or 0) for group in match.groups()]
    return hours * 3600 + minutes * 60 + seconds


def get_video_or_404(video_id: str) -> sqlite3.Row:
    video = query_one("select * from videos where id = ?", (video_id,))
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def get_product_or_404(product_id: str) -> sqlite3.Row:
    product = query_one("select * from products where id = ?", (product_id,))
    if not product:
        raise HTTPException(status_code=404, detail="Product profile not found")
    return product


def product_payload(product: sqlite3.Row) -> dict[str, Any]:
    payload = dict(product)
    for field in ("keywords", "features", "use_cases", "audience", "prohibited_contexts", "warnings"):
        try:
            payload[field] = json.loads(payload.get(field) or "[]")
        except (TypeError, json.JSONDecodeError):
            payload[field] = []
    for field in ("field_sources", "field_confidence"):
        try:
            payload[field] = json.loads(payload.get(field) or "{}")
        except (TypeError, json.JSONDecodeError):
            payload[field] = {}
    payload["profile_version"] = payload.get("profile_version") or PRODUCT_PROFILE_VERSION
    payload["profile_fingerprint"] = payload.get("profile_fingerprint") or product_profile_fingerprint(payload)
    return payload


def product_terms(product: dict[str, Any]) -> dict[str, list[str]]:
    names = normalize_profile_terms([product.get("name", ""), product.get("brand_name", "")])
    category_values = normalize_profile_terms([product.get("category", "")])
    category_aliases = []
    for category in category_values:
        category_aliases.extend(PRODUCT_CATEGORY_ALIASES.get(normalize_product_term(category), []))
    keyword_values = normalize_profile_terms(product.get("keywords", []))
    feature_values = normalize_profile_terms((product.get("features") or []) + keyword_values)
    use_case_values = normalize_profile_terms(product.get("use_cases", []))
    audience_values = normalize_profile_terms(product.get("audience", []))
    prohibited_values = normalize_profile_terms(product.get("prohibited_contexts", []))

    def usable(values: list[str]) -> list[str]:
        output = []
        for value in values:
            normalized = normalize_product_term(value)
            if normalized and normalized not in PRODUCT_GENERIC_TERMS and normalized not in output:
                output.append(normalized)
        return output[:30]

    return {
        "names": usable(names),
        "categories": usable(category_values + category_aliases),
        "features": usable(feature_values),
        "use_cases": usable(use_case_values),
        "audience": usable(audience_values),
        "prohibited": usable(prohibited_values),
    }


def save_product_profile(profile: dict[str, Any], raw_metadata: dict[str, Any], fetch_status: str = "manual") -> dict[str, Any]:
    source_url = validate_public_product_url(str(profile.get("source_url") or ""))
    now = utc_now()
    canonical_url = canonical_product_url(str(profile.get("canonical_url") or source_url))
    keywords = normalize_profile_terms(profile.get("keywords", []))
    features = normalize_profile_terms(profile.get("features", []))
    use_cases = normalize_profile_terms(profile.get("use_cases", []))
    audience = normalize_profile_terms(profile.get("audience", []))
    prohibited = normalize_profile_terms(profile.get("prohibited_contexts", []))
    name = str(profile.get("name") or "").strip()[:160]
    if not name:
        raise HTTPException(status_code=400, detail="A product name is required before analysis.")
    confidence = int(profile.get("extraction_confidence") or 0)
    prepared = {
        **profile,
        "source_url": source_url,
        "canonical_url": canonical_url,
        "name": name,
        "keywords": keywords,
        "features": features,
        "use_cases": use_cases,
        "audience": audience,
        "prohibited_contexts": prohibited,
        "profile_version": PRODUCT_PROFILE_VERSION,
    }
    fingerprint = product_profile_fingerprint(prepared)
    existing = query_one(
        "select * from products where canonical_url = ? order by updated_at desc limit 1",
        (canonical_url,),
    )
    product_id = existing["id"] if existing else new_id("product")
    field_sources = profile.get("field_sources") if isinstance(profile.get("field_sources"), dict) else {}
    field_confidence = profile.get("field_confidence") if isinstance(profile.get("field_confidence"), dict) else {}
    warnings = [str(item)[:240] for item in (profile.get("warnings") or [])][:12]
    with connect() as conn:
        values = (
            source_url, canonical_url[:2000], name,
            str(profile.get("brand_name") or "").strip()[:120] or None,
            str(profile.get("description") or "").strip()[:2000],
            str(profile.get("category") or "").strip()[:120] or None,
            json.dumps(keywords), json.dumps(features), json.dumps(use_cases), json.dumps(audience), json.dumps(prohibited),
            str(profile.get("image_url") or "").strip()[:1000] or None,
            max(0, min(100, confidence)), json.dumps(field_sources), json.dumps(field_confidence), json.dumps(warnings),
            fingerprint, PRODUCT_PROFILE_VERSION,
        )
        if existing:
            conn.execute(
                """
                update products set source_url = ?, canonical_url = ?, name = ?, brand_name = ?, description = ?, category = ?,
                keywords = ?, features = ?, use_cases = ?, audience = ?, prohibited_contexts = ?, image_url = ?, extraction_confidence = ?,
                field_sources = ?, field_confidence = ?, warnings = ?, profile_fingerprint = ?, profile_version = ?, status = 'verified', updated_at = ?
                where id = ?
                """,
                values + (now, product_id),
            )
        else:
            conn.execute(
                """
                insert into products
                (id, source_url, canonical_url, name, brand_name, description, category, keywords, features, use_cases, audience,
                prohibited_contexts, image_url, extraction_confidence, field_sources, field_confidence, warnings, profile_fingerprint,
                profile_version, status, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?)
                """,
                (product_id,) + values + (now, now),
            )
        conn.execute(
            "insert into product_snapshots (id, product_id, raw_metadata, extracted_at, fetch_status) values (?, ?, ?, ?, ?)",
            (new_id("product_snapshot"), product_id, json.dumps(raw_metadata), now, fetch_status),
        )
        conn.commit()
    return product_payload(get_product_or_404(product_id))


def update_product_profile(product: sqlite3.Row, updates: ProductUpdateRequest) -> dict[str, Any]:
    current = product_payload(product)
    incoming = updates.model_dump(exclude_unset=True) if hasattr(updates, "model_dump") else updates.dict(exclude_unset=True)
    for field, value in incoming.items():
        if field in {"keywords", "features", "use_cases", "audience", "prohibited_contexts"}:
            current[field] = normalize_profile_terms(value)
        elif field in {"field_sources", "field_confidence"} and isinstance(value, dict):
            current[field] = value
        elif field == "warnings" and isinstance(value, list):
            current[field] = [str(item)[:240] for item in value][:12]
        elif value is not None:
            current[field] = str(value).strip()
    name = str(current.get("name") or "").strip()[:160]
    if not name:
        raise HTTPException(status_code=400, detail="A product name is required.")
    now = utc_now()
    current["profile_version"] = PRODUCT_PROFILE_VERSION
    fingerprint = product_profile_fingerprint(current)
    execute(
        """
        update products set name = ?, brand_name = ?, description = ?, category = ?, keywords = ?, features = ?, use_cases = ?,
        audience = ?, prohibited_contexts = ?, image_url = ?, field_sources = ?, field_confidence = ?, warnings = ?,
        profile_fingerprint = ?, profile_version = ?, updated_at = ?
        where id = ?
        """,
        (
            name,
            str(current.get("brand_name") or "").strip()[:120] or None,
            str(current.get("description") or "").strip()[:2000],
            str(current.get("category") or "").strip()[:120] or None,
            json.dumps(current.get("keywords", [])),
            json.dumps(current.get("features", [])),
            json.dumps(current.get("use_cases", [])),
            json.dumps(current.get("audience", [])),
            json.dumps(current.get("prohibited_contexts", [])),
            str(current.get("image_url") or "").strip()[:1000] or None,
            json.dumps(current.get("field_sources", {})),
            json.dumps(current.get("field_confidence", {})),
            json.dumps(current.get("warnings", [])),
            fingerprint,
            PRODUCT_PROFILE_VERSION,
            now,
            product["id"],
        ),
    )
    return product_payload(get_product_or_404(product["id"]))


@app.get("/health")
def health() -> dict[str, Any]:
    dependencies = runtime_dependency_status()
    storage_ready = STORAGE_DIR.exists() and os.access(STORAGE_DIR, os.W_OK)
    db_ready = DB_PATH.parent.exists() and os.access(DB_PATH.parent, os.W_OK)
    media_ready = bool(dependencies["ffmpeg"]["available"] and dependencies["ffprobe"]["available"])
    detector_ready = bool(dependencies["object_detection"]["primary_ready"])
    queue_ready = bool(dependencies["jobs"]["ready"])
    ready = bool(storage_ready and db_ready and media_ready and detector_ready and queue_ready)
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "storage_ready": storage_ready,
        "database_ready": db_ready,
        "detector_ready": detector_ready,
        "queue_ready": queue_ready,
        "storage_dir": str(STORAGE_DIR),
        "scratch_dir": str(SCRATCH_DIR),
        "database_path": str(DB_PATH),
        "object_storage": {
            "backend": OBJECT_STORAGE.settings.backend,
            "enabled": OBJECT_STORAGE.enabled,
            "ready": OBJECT_STORAGE.ready,
            "bucket": OBJECT_STORAGE.settings.bucket if OBJECT_STORAGE.ready else None,
            "missing_fields": OBJECT_STORAGE.settings.missing_fields if OBJECT_STORAGE.enabled else [],
        },
        "limits": {
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_source_seconds": MAX_SOURCE_SECONDS,
            "max_analysis_seconds": MAX_ANALYSIS_SECONDS,
            "workers": int_from_env("NEUROAD_WORKERS", 1),
        },
        "dependencies": dependencies,
    }


@app.get("/api/media/{key:path}", include_in_schema=False)
def get_object_media(key: str) -> RedirectResponse:
    """Provide legacy media URLs through short-lived R2 download URLs."""
    if not OBJECT_STORAGE.ready:
        raise HTTPException(status_code=404, detail="Object media storage is not enabled.")
    try:
        return RedirectResponse(OBJECT_STORAGE.presign_get(key), status_code=307)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid media object key.") from exc


@app.post("/api/uploads/init")
def initialize_direct_upload(payload: DirectUploadInitRequest) -> dict[str, Any]:
    """Create a video record and a short-lived, browser-safe R2 PUT URL.

    Returning ``storage=local`` keeps older deployments working while the API is
    upgraded before the R2 Railway variables are enabled.
    """
    if not OBJECT_STORAGE.enabled:
        return {"storage": "local"}
    try:
        OBJECT_STORAGE.require_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    suffix = Path(payload.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format. Use MP4, MOV, WebM, or M4V.")
    if payload.size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Upload an non-empty video file.")
    if payload.size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    if payload.comparison_id:
        get_comparison_or_404(payload.comparison_id)

    video_id = new_id("video")
    object_key = f"uploads/{video_id}/source{suffix}"
    content_type = payload.content_type or content_type_for_suffix(suffix)
    execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values (?, 'upload', null, ?, '', null, 0, 'uploading', ?, null, ?)
        """,
        (video_id, Path(payload.filename).stem[:240] or "Uploaded video", OBJECT_STORAGE.uri(object_key), utc_now()),
    )
    execute(
        """insert or replace into data_asset_consents
           (video_id, consent_status, policy_version, recorded_at, withdrawn_at)
           values (?, ?, ?, ?, null)""",
        (
            video_id,
            "opted_in" if payload.allow_internal_training else "not_opted_in",
            os.getenv("NEUROAD_TRAINING_CONSENT_POLICY_VERSION", "2026-08-01"),
            utc_now(),
        ),
    )
    return {
        "storage": "r2",
        "video_id": video_id,
        "object_key": object_key,
        "upload_url": OBJECT_STORAGE.presign_put(object_key, content_type),
        "content_type": content_type,
        "expires_in_seconds": OBJECT_STORAGE.settings.presign_ttl_seconds,
    }


@app.post("/api/uploads/{video_id}/complete")
def complete_direct_upload(video_id: str, payload: Optional[DirectUploadCompleteRequest] = None) -> dict[str, Any]:
    if not OBJECT_STORAGE.ready:
        raise HTTPException(status_code=409, detail="Direct object uploads are not enabled.")
    video = get_video_or_404(video_id)
    key = r2_key_from_reference(video["file_path"])
    if not key or video["status"] != "uploading":
        raise HTTPException(status_code=409, detail="This video is not waiting for a direct upload.")
    try:
        metadata = OBJECT_STORAGE.head(key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The R2 upload could not be verified. Upload the file again.") from exc
    size = int(metadata.get("ContentLength") or 0)
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="The uploaded object is empty or exceeds the current upload limit.")
    if payload and payload.comparison_id:
        add_video_to_comparison(payload.comparison_id, video_id)
    execute("update videos set status = 'uploaded' where id = ?", (video_id,))
    return {"video_id": video_id, "status": "uploaded", "duration_seconds": 0}


async def store_uploaded_video(file: UploadFile, allow_internal_training: bool = False) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format. Use MP4, MOV, WebM, or M4V.")

    video_id = new_id("video")
    target = UPLOAD_DIR / f"{video_id}{suffix}"
    size = 0
    with target.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="Upload exceeds the 200 MB MVP limit.")
            output.write(chunk)

    duration = probe_duration(target)
    try:
        enforce_source_duration(duration)
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = Path(file.filename or "Uploaded video").stem
    execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values (?, 'upload', null, ?, '', null, ?, 'uploaded', ?, null, ?)
        """,
        (video_id, title, duration, str(target), utc_now()),
    )
    execute(
        """insert or replace into data_asset_consents
           (video_id, consent_status, policy_version, recorded_at, withdrawn_at)
           values (?, ?, ?, ?, null)""",
        (
            video_id,
            "opted_in" if allow_internal_training else "not_opted_in",
            os.getenv("NEUROAD_TRAINING_CONSENT_POLICY_VERSION", "2026-08-01"),
            utc_now(),
        ),
    )
    return {"video_id": video_id, "status": "uploaded", "duration_seconds": duration, "internal_training_opt_in": allow_internal_training}


def get_comparison_or_404(comparison_id: str) -> sqlite3.Row:
    comparison = query_one("select * from comparisons where id = ?", (comparison_id,))
    if not comparison:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return comparison


def add_video_to_comparison(comparison_id: str, video_id: str) -> None:
    comparison = get_comparison_or_404(comparison_id)
    existing = query_one(
        "select id from comparison_videos where comparison_id = ? and video_id = ?",
        (comparison_id, video_id),
    )
    if existing:
        return
    count = int(query_one("select count(*) as count from comparison_videos where comparison_id = ?", (comparison_id,))["count"])
    if count >= COMPARISON_MAX_VIDEOS:
        raise HTTPException(status_code=400, detail=f"A comparison supports up to {COMPARISON_MAX_VIDEOS} videos.")
    execute(
        """
        insert into comparison_videos (id, comparison_id, video_id, display_order, processing_status, created_at)
        values (?, ?, ?, ?, 'uploaded', ?)
        """,
        (new_id("comparison_video"), comparison_id, video_id, count + 1, utc_now()),
    )
    execute(
        "update comparisons set total_videos = ?, status = 'uploaded', updated_at = ? where id = ?",
        (count + 1, utc_now(), comparison["id"]),
    )


@app.post("/api/comparisons")
def create_comparison(request: FastAPIRequest, payload: Optional[ComparisonCreateRequest] = None) -> dict[str, Any]:
    comparison_id = new_id("comparison")
    title = (payload.title if payload and payload.title else "Video comparison").strip()
    analytics_context = analytics_context_from_request(request)
    execute(
        """
        insert into comparisons
        (id, title, status, comparison_mode, total_videos, completed_videos, failed_videos, analytics_distinct_id, analytics_session_id, created_at, updated_at)
        values (?, ?, 'created', 'pending', 0, 0, 0, ?, ?, ?, ?)
        """,
        (
            comparison_id,
            title[:160] or "Video comparison",
            analytics_context.distinct_id,
            analytics_context.session_id,
            utc_now(),
            utc_now(),
        ),
    )
    capture_event(
        "comparison_created",
        analytics_context,
        {"comparison_id": comparison_id, "workflow": "comparison"},
        insert_id=f"comparison:{comparison_id}:created",
    )
    return {"comparison_id": comparison_id, "status": "created"}


@app.post("/api/comparisons/{comparison_id}/videos/upload")
async def upload_comparison_videos(
    request: FastAPIRequest,
    comparison_id: str,
    files: list[UploadFile] = File(...),
    allow_internal_training: bool = Form(default=False),
) -> dict[str, Any]:
    get_comparison_or_404(comparison_id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one video.")
    existing_count = int(query_one("select count(*) as count from comparison_videos where comparison_id = ?", (comparison_id,))["count"])
    if existing_count + len(files) > COMPARISON_MAX_VIDEOS:
        raise HTTPException(status_code=400, detail=f"A comparison supports up to {COMPARISON_MAX_VIDEOS} videos.")
    uploaded = []
    for file in files:
        result = await store_uploaded_video(file, allow_internal_training=allow_internal_training)
        add_video_to_comparison(comparison_id, result["video_id"])
        uploaded.append(result)
        capture_event(
            "video_upload_completed",
            analytics_context_from_request(request),
            {
                "video_id": result["video_id"],
                "comparison_id": comparison_id,
                "workflow": "comparison",
                "source_type": "upload",
                "duration_bucket": duration_bucket(result["duration_seconds"]),
            },
            insert_id=f"video:{result['video_id']}:upload_completed",
        )
    return {"comparison_id": comparison_id, "status": "uploaded", "videos": uploaded}


@app.post("/api/videos/upload")
async def upload_video(
    request: FastAPIRequest,
    file: UploadFile = File(...),
    allow_internal_training: bool = Form(default=False),
) -> dict[str, Any]:
    result = await store_uploaded_video(file, allow_internal_training=allow_internal_training)
    capture_event(
        "video_upload_completed",
        analytics_context_from_request(request),
        {
            "video_id": result["video_id"],
            "workflow": "single",
            "source_type": "upload",
            "duration_bucket": duration_bucket(result["duration_seconds"]),
        },
        insert_id=f"video:{result['video_id']}:upload_completed",
    )
    return result


@app.post("/api/videos/youtube")
def create_youtube_video(payload: YouTubeRequest) -> dict[str, Any]:
    youtube_id = parse_youtube_id(payload.url)
    if not youtube_id:
        raise HTTPException(status_code=400, detail="Use a valid public YouTube URL.")
    metadata = fetch_youtube_metadata(payload.url, youtube_id)
    video_id = new_id("video")
    embed_url = f"https://www.youtube.com/embed/{youtube_id}"
    execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values (?, 'youtube', ?, ?, ?, ?, ?, 'metadata_fetched', null, ?, ?)
        """,
        (
            video_id,
            payload.url,
            metadata["title"],
            metadata.get("description", ""),
            metadata.get("thumbnail_url"),
            int(metadata.get("duration_seconds") or 0),
            embed_url,
            utc_now(),
        ),
    )
    return {"video_id": video_id, "status": "metadata_fetched", **metadata, "embed_url": embed_url}


@app.post("/api/videos/youtube/ingest")
def ingest_youtube_video(payload: YouTubeIngestRequest) -> dict[str, Any]:
    if not payload.has_permission:
        raise HTTPException(status_code=400, detail="Confirm that you own or have permission to analyze this YouTube video.")

    youtube_id = parse_youtube_id(payload.url)
    if not youtube_id:
        raise HTTPException(status_code=400, detail="Use a valid public YouTube URL.")

    video_id = new_id("video")
    metadata = fetch_youtube_metadata(payload.url, youtube_id)
    embed_url = f"https://www.youtube.com/embed/{youtube_id}"
    execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values (?, 'youtube_ingest', ?, ?, ?, ?, ?, 'uploaded', null, ?, ?)
        """,
        (
            video_id,
            payload.url,
            metadata["title"],
            metadata.get("description", ""),
            metadata.get("thumbnail_url"),
            int(metadata.get("duration_seconds") or 0),
            embed_url,
            utc_now(),
        ),
    )
    return {"video_id": video_id, "status": "uploaded", "duration_seconds": int(metadata.get("duration_seconds") or 0), "title": metadata["title"]}


@app.post("/api/videos/url")
def create_video_from_url(payload: VideoUrlRequest) -> dict[str, Any]:
    parsed = urlparse(payload.url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Use an http(s) video URL.")
    if parse_youtube_id(payload.url):
        raise HTTPException(status_code=400, detail="Use the YouTube permission checkbox path for YouTube URLs.")

    video_id = new_id("video")
    title = Path(parsed.path).name or parsed.netloc or "Remote video"
    description = (
        "Direct video URL queued for real media analysis."
        if convertible_video_suffix_from_url(payload.url)
        else "Media page URL queued for real extraction and analysis."
    )
    execute(
        """
        insert into videos
        (id, source_type, source_url, title, description, thumbnail_url, duration_seconds, status, file_path, embed_url, created_at)
        values (?, 'url', ?, ?, ?, null, 0, 'uploaded', null, null, ?)
        """,
        (video_id, payload.url, title, description, utc_now()),
    )
    return {"video_id": video_id, "status": "uploaded", "duration_seconds": 0}


def dispatch_processing_task(task_name: str, args: list[Any], local_callable: Any) -> None:
    if env_enabled("NEUROAD_USE_CELERY", False):
        try:
            from celery_app import celery_app

            celery_app.send_task(task_name, args=args)
            return
        except Exception as exc:
            raise RuntimeError(f"Celery could not queue {task_name}: {exc}") from exc
    EXECUTOR.submit(local_callable, *args)


def create_video_analysis_job(
    video_id: str,
    comparison_id: str | None = None,
    comparison_video_id: str | None = None,
    submit: bool = True,
    analytics_context: AnalyticsContext | None = None,
) -> dict[str, Any]:
    video = get_video_or_404(video_id)
    existing = query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (video_id,))
    if existing and existing["status"] in {"queued", "processing"}:
        return {"job_id": existing["id"], "status": existing["status"]}

    if analytics_context is None and comparison_id:
        analytics_context = analytics_context_from_row(get_comparison_or_404(comparison_id))
    analytics_context = analytics_context or AnalyticsContext()
    job_id = new_id("job")
    execute(
        """
        insert into jobs
        (id, video_id, comparison_id, comparison_video_id, status, progress, current_step, error, analytics_distinct_id, analytics_session_id, created_at, updated_at)
        values (?, ?, ?, ?, 'queued', 0, 'metadata', null, ?, ?, ?, ?)
        """,
        (
            job_id,
            video_id,
            comparison_id,
            comparison_video_id,
            analytics_context.distinct_id,
            analytics_context.session_id,
            utc_now(),
            utc_now(),
        ),
    )
    capture_event(
        "analysis_requested",
        analytics_context,
        {
            "analysis_id": job_id,
            "video_id": video_id,
            "comparison_id": comparison_id,
            "workflow": "comparison" if comparison_id else "single",
            "source_type": video["source_type"],
            "duration_bucket": duration_bucket(video["duration_seconds"]),
        },
        insert_id=f"analysis:{job_id}:requested",
    )

    if not video["file_path"] and video["source_type"] not in {"url", "youtube_ingest"}:
        error = "No analyzable media file is attached. Upload a video or provide a direct MP4/MOV/WebM URL."
        update_job(
            job_id,
            "failed",
            100,
            "metadata",
            error,
        )
        execute("update videos set status = 'failed' where id = ?", (video_id,))
        capture_event(
            "analysis_failed",
            analytics_context,
            {
                "analysis_id": job_id,
                "video_id": video_id,
                "comparison_id": comparison_id,
                "workflow": "comparison" if comparison_id else "single",
                "source_type": video["source_type"],
                "error_code": analytics_error_code(error),
            },
            insert_id=f"analysis:{job_id}:failed",
        )
        return {"job_id": job_id, "status": "failed"}

    if submit:
        try:
            dispatch_processing_task("neuroad.process_upload_job", [job_id, video_id], process_upload_job)
        except RuntimeError as exc:
            update_job(job_id, "failed", 100, "queue", public_job_error(exc))
            execute("update videos set status = 'failed' where id = ?", (video_id,))
            raise HTTPException(status_code=503, detail="The analysis queue is unavailable. Try again shortly.") from exc
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/videos/{video_id}/analyze")
def analyze_video(video_id: str, request: FastAPIRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return create_video_analysis_job(video_id, analytics_context=analytics_context_from_request(request))


@app.post("/api/comparisons/{comparison_id}/analyze")
def analyze_comparison(request: FastAPIRequest, comparison_id: str, payload: Optional[ComparisonAnalyzeRequest] = None) -> dict[str, Any]:
    comparison = get_comparison_or_404(comparison_id)
    members = query_all("select * from comparison_videos where comparison_id = ? order by display_order", (comparison_id,))
    if payload and payload.video_ids:
        selected = set(payload.video_ids)
        members = [member for member in members if member["video_id"] in selected]
    if len(members) < COMPARISON_MIN_VIDEOS:
        raise HTTPException(status_code=400, detail=f"Add at least {COMPARISON_MIN_VIDEOS} videos before starting a comparison.")
    if comparison["status"] == "processing":
        return {"comparison_id": comparison_id, "status": "processing"}
    analytics_context = analytics_context_from_request(request)
    execute(
        """
        update comparisons
        set status = 'queued', analytics_distinct_id = coalesce(?, analytics_distinct_id),
            analytics_session_id = coalesce(?, analytics_session_id), updated_at = ?
        where id = ?
        """,
        (analytics_context.distinct_id, analytics_context.session_id, utc_now(), comparison_id),
    )
    capture_event(
        "comparison_analysis_requested",
        analytics_context,
        {"comparison_id": comparison_id, "workflow": "comparison", "video_count": len(members)},
        insert_id=f"comparison:{comparison_id}:analysis_requested",
    )
    EXECUTOR.submit(process_comparison_job, comparison_id, [dict(member) for member in members])
    execute("update comparisons set status = 'queued', updated_at = ? where id = ?", (utc_now(), comparison_id))
    try:
        dispatch_processing_task(
            "neuroad.process_comparison_job",
            [comparison_id, [dict(member) for member in members]],
            process_comparison_job,
        )
    except RuntimeError as exc:
        execute("update comparisons set status = 'failed', updated_at = ? where id = ?", (utc_now(), comparison_id))
        raise HTTPException(status_code=503, detail="The comparison queue is unavailable. Try again shortly.") from exc
    return {"comparison_id": comparison_id, "status": "queued", "total_videos": len(members)}


@app.post("/api/products/resolve")
def resolve_product(payload: ProductResolveRequest) -> dict[str, Any]:
    canonical_url = canonical_product_url(payload.url)
    cached = query_one("select payload, fetched_at from product_resolution_cache where canonical_url = ?", (canonical_url,))
    if cached:
        try:
            age_seconds = (datetime.utcnow() - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
            if age_seconds <= PRODUCT_RESOLUTION_TTL_SECONDS:
                result = json.loads(cached["payload"])
                result["cache_status"] = "hit"
                return result
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    result = extract_product_profile(canonical_url)
    execute(
        "insert or replace into product_resolution_cache (canonical_url, payload, fetched_at) values (?, ?, ?)",
        (canonical_url, json.dumps(result), utc_now()),
    )
    result["cache_status"] = "miss"
    return result


@app.post("/api/products")
def create_product(payload: ProductCreateRequest) -> dict[str, Any]:
    profile = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    profile["canonical_url"] = profile["source_url"]
    return save_product_profile(profile, {"created_from": "reviewed_profile"}, "reviewed")


@app.get("/api/products")
def list_products(limit: int = Query(default=8, ge=1, le=25)) -> dict[str, Any]:
    products = query_all("select * from products order by updated_at desc limit ?", (limit,))
    return {"products": [product_payload(product) for product in products]}


@app.get("/api/products/{product_id}")
def get_product(product_id: str) -> dict[str, Any]:
    return product_payload(get_product_or_404(product_id))


@app.patch("/api/products/{product_id}")
def patch_product(product_id: str, payload: ProductUpdateRequest) -> dict[str, Any]:
    return update_product_profile(get_product_or_404(product_id), payload)


@app.post("/api/videos/{video_id}/product-fit")
def analyze_video_product_fit(request: FastAPIRequest, video_id: str, payload: ProductFitRequest) -> dict[str, Any]:
    result = run_product_fit(get_product_or_404(payload.product_id), get_video_or_404(video_id))
    capture_event(
        "product_fit_completed",
        analytics_context_from_request(request),
        {
            "fit_run_id": result["fit_run_id"],
            "video_id": video_id,
            "product_id": payload.product_id,
            "workflow": "single",
            "fit_score": result["overall_fit_score"],
            "suitability_tier": result["suitability_tier"],
        },
        insert_id=f"product_fit:{result['fit_run_id']}:completed",
    )
    return result


@app.get("/api/videos/{video_id}/product-fit/{fit_run_id}")
def get_video_product_fit(video_id: str, fit_run_id: str) -> dict[str, Any]:
    fit_run = query_one("select * from product_fit_runs where id = ? and video_id = ?", (fit_run_id, video_id))
    if not fit_run:
        raise HTTPException(status_code=404, detail="Product fit analysis not found")
    return product_fit_payload(fit_run)


@app.post("/api/comparisons/{comparison_id}/product-fit")
def analyze_comparison_product_fit(request: FastAPIRequest, comparison_id: str, payload: ProductFitRequest) -> dict[str, Any]:
    get_comparison_or_404(comparison_id)
    product = get_product_or_404(payload.product_id)
    members = query_all("select video_id from comparison_videos where comparison_id = ? order by display_order", (comparison_id,))
    results = []
    for member in members:
        video = get_video_or_404(member["video_id"])
        if video["status"] == "completed":
            results.append(run_product_fit(product, video, comparison_id))
    if not results:
        raise HTTPException(status_code=400, detail="Complete at least one video analysis before running product fit.")
    ranked = sorted(results, key=lambda item: item["overall_fit_score"], reverse=True)
    capture_event(
        "product_fit_completed",
        analytics_context_from_request(request),
        {
            "comparison_id": comparison_id,
            "product_id": payload.product_id,
            "workflow": "comparison",
            "video_count": len(ranked),
            "fit_score": ranked[0]["overall_fit_score"],
            "suitability_tier": ranked[0]["suitability_tier"],
        },
        insert_id=f"product_fit:comparison:{comparison_id}:{payload.product_id}:completed",
    )
    return {
        "comparison_id": comparison_id,
        "product": product_payload(product),
        "rankings": ranked,
        "summary": f"{len(ranked)} completed videos ranked for {product['name']} using product-context and placement-window evidence.",
    }


def create_insight_report_job(
    target_type: str,
    target_id: str,
    analytics_context: AnalyticsContext | None = None,
) -> dict[str, Any]:
    analytics_context = analytics_context or AnalyticsContext()
    settings = RunPodSettings.from_env()
    if not runpod_insights_enabled(settings) or not settings.configured:
        raise HTTPException(status_code=503, detail=runpod_configuration_error(settings))
    if target_type == "video":
        video = get_video_or_404(target_id)
        if video["status"] != "completed":
            raise HTTPException(status_code=400, detail="Complete video analysis before generating a detailed insight report.")
        fingerprint = video_insight_fingerprint(target_id)
    else:
        comparison = get_comparison_or_404(target_id)
        completed = int(comparison["completed_videos"] or 0)
        if completed < COMPARISON_MIN_VIDEOS:
            raise HTTPException(status_code=400, detail=f"At least {COMPARISON_MIN_VIDEOS} completed videos are required.")
        fingerprint = comparison_insight_fingerprint(target_id)
    prompt_version = insight_prompt_version(target_type)
    report = query_one(
        "select * from insight_reports where target_type = ? and target_id = ? and input_fingerprint = ? and prompt_version = ?",
        (target_type, target_id, fingerprint, prompt_version),
    )
    if report and report["status"] == "completed":
        return {"report_id": report["id"], "status": "completed", "report_url": f"/api/insight-reports/{report['id']}"}
    if not report:
        report_id = new_id("insight_report")
        now = utc_now()
        execute(
            """insert into insight_reports
               (id, target_type, target_id, report_type, input_fingerprint, prompt_version, provider, model, status, created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, 'runpod', ?, 'queued', ?, ?)""",
            (report_id, target_type, target_id, target_type, fingerprint, prompt_version, settings.model, now, now),
        )
        report = query_one("select * from insight_reports where id = ?", (report_id,))
    latest = query_one("select * from insight_jobs where report_id = ? order by updated_at desc limit 1", (report["id"],))
    if latest and latest["status"] in {"queued", "processing"}:
        return {"job_id": latest["id"], "report_id": report["id"], "status": latest["status"], "progress": latest["progress"], "stage": latest["stage"]}
    if latest and int(latest["attempts"] or 0) >= INSIGHT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Insight retry limit reached. Re-run the analysis to create a new evidence fingerprint.")
    job_id = new_id("insight_job")
    attempts = int(latest["attempts"] or 0) if latest else 0
    now = utc_now()
    execute(
        """insert into insight_jobs
           (id, report_id, target_type, target_id, input_fingerprint, prompt_version, status, progress, stage, model, attempts,
            analytics_distinct_id, analytics_session_id, created_at, updated_at)
           values (?, ?, ?, ?, ?, ?, 'queued', 0, 'queued', ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            report["id"],
            target_type,
            target_id,
            fingerprint,
            prompt_version,
            settings.model,
            attempts,
            analytics_context.distinct_id,
            analytics_context.session_id,
            now,
            now,
        ),
    )
    execute("update insight_reports set status = 'queued', updated_at = ? where id = ?", (now, report["id"]))
    capture_event(
        "insight_report_requested",
        analytics_context,
        {
            "insight_job_id": job_id,
            "report_id": report["id"],
            "target_type": target_type,
            "video_id": target_id if target_type == "video" else None,
            "comparison_id": target_id if target_type == "comparison" else None,
        },
        insert_id=f"insight_report:{job_id}:requested",
    )
    INSIGHT_EXECUTOR.submit(process_insight_job, job_id)
    return {"job_id": job_id, "report_id": report["id"], "status": "queued", "progress": 0, "stage": "queued"}


@app.post("/api/videos/{video_id}/insight-reports")
def create_video_insight_report(video_id: str, request: FastAPIRequest) -> dict[str, Any]:
    return create_insight_report_job("video", video_id, analytics_context_from_request(request))


@app.post("/api/comparisons/{comparison_id}/insight-reports")
def create_comparison_insight_report(comparison_id: str, request: FastAPIRequest) -> dict[str, Any]:
    return create_insight_report_job("comparison", comparison_id, analytics_context_from_request(request))


@app.get("/api/insight-jobs/{job_id}")
def get_insight_job(job_id: str) -> dict[str, Any]:
    job = query_one("select * from insight_jobs where id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="Insight job not found")
    data = dict(job)
    data["report_url"] = f"/api/insight-reports/{job['report_id']}" if job["status"] == "completed" else None
    return data


@app.get("/api/insight-reports/{report_id}")
def get_insight_report(report_id: str) -> dict[str, Any]:
    report = query_one("select * from insight_reports where id = ?", (report_id,))
    if not report:
        raise HTTPException(status_code=404, detail="Insight report not found")
    if report["status"] != "completed" or not report["content_json"]:
        raise HTTPException(status_code=409, detail="Insight report is not complete yet.")
    try:
        content = json.loads(report["content_json"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Insight report data is invalid.") from exc
    return content


@app.get("/api/insight-reports/{report_id}/export")
def export_insight_report(report_id: str, format: str = Query("pdf", pattern="^(pdf|json)$")) -> Response:
    """Create a download from the same validated report object rendered by the dashboard."""
    report = query_one("select * from insight_reports where id = ?", (report_id,))
    if not report or report["status"] != "completed" or not report["content_json"]:
        raise HTTPException(status_code=404, detail="Completed insight report not found")
    try:
        content = json.loads(report["content_json"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Insight report data is invalid.") from exc
    if format == "json":
        return Response(
            content=json.dumps(content, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.json"'},
        )
    path = REPORT_DIR / "insights" / f"{report_id}.pdf"
    try:
        write_report_pdf(content, path)
    except Exception as exc:
        INSIGHT_LOGGER.exception("Insight PDF export failed: report_id=%s", report_id)
        raise HTTPException(status_code=500, detail="The insight PDF could not be created.") from exc
    return FileResponse(path, media_type="application/pdf", filename=f"{report_id}.pdf")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = query_one("select * from jobs where id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(job)


@app.get("/api/system/dependencies")
def get_system_dependencies() -> dict[str, Any]:
    dependencies = runtime_dependency_status()
    ffmpeg_available = dependencies["ffmpeg"]["available"]
    ffprobe_available = dependencies["ffprobe"]["available"]
    yt_dlp_available = dependencies["yt_dlp"]["available"]

    cookies_configured = bool(
        os.getenv("YTDLP_COOKIES_FILE") or
        os.getenv("YTDLP_COOKIES_BROWSER") or
        (STORAGE_DIR / "cookies.txt").exists()
    )

    return {
        "ready": bool(ffmpeg_available and ffprobe_available),
        "youtube_ingest_ready": bool(ffmpeg_available and ffprobe_available and yt_dlp_available),
        "youtube_cookies_configured": cookies_configured,
        "limits": {
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_source_seconds": MAX_SOURCE_SECONDS,
            "max_analysis_seconds": MAX_ANALYSIS_SECONDS,
        },
        "dependencies": dependencies,
    }


@app.post("/api/system/cookies")
async def upload_cookies(file: UploadFile = File(...)) -> dict[str, Any]:
    target = STORAGE_DIR / "cookies.txt"
    content = await file.read()
    if not content.startswith(b"# Netscape HTTP Cookie File"):
        raise HTTPException(status_code=400, detail="Invalid cookies.txt file format. Must be a Netscape HTTP Cookie File.")

    with target.open("wb") as output:
        output.write(content)

    return {"status": "ok", "message": "Cookies uploaded successfully"}


@app.get("/api/videos/{video_id}/analysis")
def get_analysis(video_id: str) -> dict[str, Any]:
    video = get_video_or_404(video_id)
    segments = query_all("select * from segments where video_id = ? order by start_time", (video_id,))
    if not segments and video["status"] not in {"completed", "metadata_fetched", "uploaded", "processing"}:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return build_analysis_payload(video)


@app.get("/api/videos/{video_id}/timeline")
def get_signal_timeline(
    video_id: str,
    resolution: str = Query("auto", pattern="^(auto|segment)$"),
    families: str = Query("visual,audio,narrative,social"),
) -> dict[str, Any]:
    payload = get_analysis(video_id)
    requested = [family.strip() for family in families.split(",") if family.strip()]
    allowed = {"visual", "audio", "narrative", "social"}
    selected = [family for family in requested if family in allowed]
    if not selected:
        raise HTTPException(status_code=400, detail="Choose at least one supported signal family.")
    timeline = payload.get("timeline_summary", {})
    points = []
    for point in timeline.get("points", []):
        points.append(
            {
                "segment_id": point.get("segment_id"),
                "start": point.get("start"),
                "end": point.get("end"),
                "label": point.get("label"),
                "reliability": point.get("reliability"),
                **{family: point.get(family, {}) for family in selected},
            }
        )
    return {
        "video_id": video_id,
        "analysis_version": payload.get("analysis_version"),
        "resolution": "segment" if resolution == "auto" else resolution,
        "families": selected,
        "points": points,
        "signal_availability": payload.get("signal_availability", {}),
    }


@app.get("/api/videos/{video_id}/segments/{segment_id}/evidence")
def get_segment_evidence(video_id: str, segment_id: str) -> dict[str, Any]:
    segment = query_one("select * from segments where id = ? and video_id = ?", (segment_id, video_id))
    if not segment:
        raise HTTPException(status_code=404, detail="Segment evidence not found")
    payload = get_analysis(video_id)
    public_segment = next((item for item in payload.get("segments", []) if item.get("id") == segment_id), None)
    if not public_segment:
        raise HTTPException(status_code=404, detail="Segment evidence not found")
    run = query_one(
        "select * from analysis_runs where video_id = ? order by started_at desc limit 1",
        (video_id,),
    )
    manifests = []
    review = None
    evidence_by_type: dict[str, dict[str, Any]] = {}
    if run:
        manifests = [dict(row) for row in query_all("select * from model_manifests where analysis_run_id = ?", (run["id"],))]
        for manifest in manifests:
            manifest["configuration"] = json.loads(manifest["configuration"]) if manifest.get("configuration") else {}
        artifact_rows = query_all(
            "select artifact_type, payload, uri, confidence from evidence_artifacts where analysis_run_id = ? and segment_id = ?",
            (run["id"], segment_id),
        )
        for artifact in artifact_rows:
            try:
                artifact_payload = json.loads(artifact["payload"]) if artifact["payload"] else {}
            except json.JSONDecodeError:
                artifact_payload = {}
            evidence_by_type[artifact["artifact_type"]] = {
                **artifact_payload,
                "uri": artifact["uri"],
                "confidence": artifact["confidence"],
            }
        review_row = query_one(
            "select * from evidence_review_tasks where analysis_run_id = ? and segment_id = ? order by updated_at desc limit 1",
            (run["id"], segment_id),
        )
        review = dict(review_row) if review_row else None
    transcript = public_segment.get("transcript", "")
    transcript_insights = public_segment.get("transcript_insights", {})
    transcript_confidence = transcript_insights.get("transcript_confidence")
    transcript_words = transcript_insights.get("words") or [
        {"word": word, "confidence": transcript_confidence} for word in transcript.split()
    ]
    return {
        "video_id": video_id,
        "segment_id": segment_id,
        "timestamp": {"start": public_segment["start"], "end": public_segment["end"]},
        "frame": {
            "thumbnail_url": public_segment.get("thumbnail_url"),
            "objects": evidence_by_type.get("frame", {}).get("objects", public_segment.get("objects", [])),
            "face_subject_boxes": [
                item for item in public_segment.get("objects", []) if str(item.get("label", "")).lower() == "person"
            ],
            "face_landmark_boxes": evidence_by_type.get("face_behavior", {}).get("face_boxes", []),
        },
        "ocr": evidence_by_type.get(
            "ocr", public_segment.get("ocr_evidence", {"status": "unavailable", "texts": []})
        ),
        "transcript": {
            "text": transcript,
            "words": transcript_words,
            "confidence": transcript_confidence,
            "language": transcript_insights.get("language"),
            "language_method": transcript_insights.get("language_method"),
        },
        "audio": evidence_by_type.get("audio", public_segment.get("audio_evidence", {})),
        "scenes": {
            **evidence_by_type.get("scene", {}),
            "change_strength": public_segment.get("visual_evidence", {}).get("visual_novelty"),
            "boundary_confirmed": None,
        },
        "signals": public_segment.get("signal_summary", {}),
        "model_manifests": manifests,
        "human_review": review or {"state": "unreviewed"},
    }


@app.post("/api/videos/{video_id}/reanalyze")
def reanalyze_video(video_id: str) -> dict[str, Any]:
    video = get_video_or_404(video_id)
    if not video["file_path"] or (
        not r2_key_from_reference(video["file_path"]) and not Path(video["file_path"]).is_file()
    ):
        raise HTTPException(status_code=409, detail="The original source is no longer available for reanalysis.")
    previous_run = query_one(
        "select id, schema_version, state from analysis_runs where video_id = ? order by started_at desc limit 1",
        (video_id,),
    )
    job = create_video_analysis_job(video_id)
    return {
        **job,
        "video_id": video_id,
        "previous_analysis": dict(previous_run) if previous_run else None,
        "target_analysis_version": ANALYSIS_SCHEMA_VERSION,
    }


def require_review_access(x_neuroad_review_key: str | None) -> None:
    configured = os.getenv("NEUROAD_REVIEW_API_KEY")
    if not configured:
        raise HTTPException(status_code=503, detail="Evidence review API is not configured.")
    if not x_neuroad_review_key or not secrets.compare_digest(configured, x_neuroad_review_key):
        raise HTTPException(status_code=401, detail="Invalid evidence review credentials.")


@app.post("/api/admin/evidence-reviews")
def create_evidence_review(
    payload: EvidenceReviewCreateRequest,
    x_neuroad_review_key: Optional[str] = Header(None),
) -> dict[str, Any]:
    require_review_access(x_neuroad_review_key)
    run = query_one("select * from analysis_runs where id = ?", (payload.analysis_run_id,))
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if payload.segment_id and not query_one(
        "select id from segments where id = ? and video_id = ?", (payload.segment_id, run["video_id"])
    ):
        raise HTTPException(status_code=404, detail="Segment not found")
    task_id = new_id("review")
    now = utc_now()
    execute(
        """
        insert into evidence_review_tasks
        (id, analysis_run_id, segment_id, assignment, state, notes, reviewer, created_at, updated_at)
        values (?, ?, ?, ?, 'unreviewed', null, null, ?, ?)
        """,
        (task_id, payload.analysis_run_id, payload.segment_id, payload.assignment, now, now),
    )
    return dict(query_one("select * from evidence_review_tasks where id = ?", (task_id,)))


@app.patch("/api/admin/evidence-reviews/{task_id}")
def update_evidence_review(
    task_id: str,
    payload: EvidenceReviewUpdateRequest,
    x_neuroad_review_key: Optional[str] = Header(None),
) -> dict[str, Any]:
    require_review_access(x_neuroad_review_key)
    allowed_states = {"unreviewed", "assigned", "submitted", "approved", "changes_requested"}
    if payload.state not in allowed_states:
        raise HTTPException(status_code=400, detail="Unsupported review state.")
    task = query_one("select * from evidence_review_tasks where id = ?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="Evidence review task not found")
    execute(
        """
        update evidence_review_tasks
        set state = ?, notes = ?, reviewer = ?, assignment = coalesce(?, assignment), updated_at = ?
        where id = ?
        """,
        (payload.state, payload.notes, payload.reviewer, payload.assignment, utc_now(), task_id),
    )
    return dict(query_one("select * from evidence_review_tasks where id = ?", (task_id,)))


@app.get("/api/comparisons/{comparison_id}/status")
def get_comparison_status(comparison_id: str) -> dict[str, Any]:
    comparison = get_comparison_or_404(comparison_id)
    members = query_all("select * from comparison_videos where comparison_id = ? order by display_order", (comparison_id,))
    videos = []
    for member in members:
        job = query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (member["video_id"],))
        videos.append(
            {
                "video_id": member["video_id"],
                "status": member["processing_status"],
                "progress": int(job["progress"]) if job else 0,
                "job_id": job["id"] if job else None,
                "error": member["error"],
            }
        )
    return {
        "comparison_id": comparison_id,
        "status": comparison["status"],
        "total_videos": comparison["total_videos"],
        "completed_videos": comparison["completed_videos"],
        "failed_videos": comparison["failed_videos"],
        "consolidated_report_ready": int(comparison["completed_videos"] or 0) >= COMPARISON_MIN_VIDEOS,
        "videos": videos,
    }


@app.get("/api/comparisons/{comparison_id}")
def get_comparison(comparison_id: str) -> dict[str, Any]:
    return build_comparison_payload(get_comparison_or_404(comparison_id))


@app.get("/api/comparisons/{comparison_id}/export")
def export_comparison(comparison_id: str, format: str = Query("csv", pattern="^(csv|json)$")) -> FileResponse:
    comparison = get_comparison_or_404(comparison_id)
    if int(comparison["completed_videos"] or 0) < COMPARISON_MIN_VIDEOS:
        raise HTTPException(status_code=400, detail=f"At least {COMPARISON_MIN_VIDEOS} completed videos are required before export.")
    persist_comparison_report(comparison_id)
    report = query_one("select * from comparison_reports where comparison_id = ? order by created_at desc limit 1", (comparison_id,))
    if not report:
        raise HTTPException(status_code=404, detail="Comparison report not found")
    path = Path(report["csv_path"] if format == "csv" else report["json_path"])
    return FileResponse(path, media_type="text/csv" if format == "csv" else "application/json", filename=f"{comparison_id}-comparison.{format}")


@app.get("/api/videos/{video_id}/export")
def export_analysis(video_id: str, format: str = Query("csv", pattern="^(csv|json)$")) -> FileResponse:
    video = get_video_or_404(video_id)
    if video["status"] != "completed":
        raise HTTPException(status_code=400, detail="Analysis is not complete yet.")
    paths = generate_exports(video_id)
    path = paths[format]
    media_type = "text/csv" if format == "csv" else "application/json"
    return FileResponse(path, media_type=media_type, filename=f"{video_id}-analysis.{format}")


def update_job(job_id: str, status: str, progress: int, step: str, error: str | None = None) -> None:
    execute(
        "update jobs set status = ?, progress = ?, current_step = ?, error = ?, updated_at = ? where id = ?",
        (status, progress, step, error, utc_now(), job_id),
    )


RUNPOD_INSIGHT_SYSTEM_PROMPT = """
You are NeuroAd's evidence synthesis layer. Analyze only the supplied deterministic video evidence.
Do not invent objects, transcript, audience facts, performance claims, or brand-safety events.
Treat scores as inputs, not facts to override. If evidence is missing or weak, say so explicitly.
Return only one JSON object with exactly these keys:
{
  "executive_summary": "2-4 concise sentences",
  "placement_strategy": "1-3 concise sentences",
  "creative_actions": ["up to 5 concrete actions"],
  "brand_safety_notes": ["up to 4 evidence-grounded notes"],
  "confidence_notes": ["up to 3 limitations or confidence notes"]
}
Do not include markdown or hidden reasoning.
""".strip()


def bounded_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def bounded_string_list(value: Any, limit: int, item_limit: int = 280) -> list[str]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value:
        text = bounded_text(item, item_limit)
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def normalize_runpod_insights(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "executive_summary": bounded_text(payload.get("executive_summary"), 1200),
        "placement_strategy": bounded_text(payload.get("placement_strategy"), 900),
        "creative_actions": bounded_string_list(payload.get("creative_actions"), 5),
        "brand_safety_notes": bounded_string_list(payload.get("brand_safety_notes"), 4),
        "confidence_notes": bounded_string_list(payload.get("confidence_notes"), 3),
    }


def build_runpod_evidence_payload(video: sqlite3.Row, segments: list[dict[str, Any]]) -> dict[str, Any]:
    summary_segments = []
    for segment in segments:
        normalized_matches = [
            {
                **match,
                "ad_category": match.get("ad_category") or match.get("category") or "Unknown",
            }
            for match in segment.get("ad_matches", [])
        ]
        summary_segments.append({**segment, "ad_matches": normalized_matches})
    summary = summarize(video, summary_segments)
    ranked = sorted(segments, key=lambda item: float(item.get("ad_slot_score", 0) or 0), reverse=True)[:5]
    weakest = sorted(segments, key=lambda item: float(item.get("attention_score", 0) or 0))[:2]
    selected: list[dict[str, Any]] = []
    seen_ranges: set[tuple[float, float]] = set()
    for segment in ranked + weakest:
        key = (float(segment.get("start", 0)), float(segment.get("end", 0)))
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        selected.append(
            {
                "start": segment.get("start"),
                "end": segment.get("end"),
                "attention_score": segment.get("attention_score"),
                "ad_fit_score": segment.get("ad_fit_score"),
                "drop_risk_score": segment.get("drop_risk_score"),
                "brand_safety_score": segment.get("brand_safety_score"),
                "recommendation_tier": segment.get("recommendation_tier"),
                "recommendation_confidence": segment.get("recommendation_confidence"),
                "transcript": bounded_text(segment.get("transcript"), 700),
                "topics": [
                    {"label": topic.get("label"), "confidence": topic.get("confidence")}
                    for topic in segment.get("topics", [])[:4]
                ],
                "objects": [
                    {"label": item.get("label"), "confidence": item.get("confidence")}
                    for item in segment.get("objects", [])[:5]
                ],
                "ad_matches": [
                    {
                        "category": match.get("category") or match.get("ad_category"),
                        "score": match.get("ad_fit_score"),
                        "confidence": match.get("confidence"),
                    }
                    for match in segment.get("ad_matches", [])[:4]
                ],
                "strong_signals": segment.get("strong_signals", [])[:5],
                "weak_signals": segment.get("failed_or_weak_signals", [])[:5],
            }
        )
    return {
        "video": {
            "title": bounded_text(video["title"], 240),
            "description": bounded_text(video["description"], 800),
            "duration_seconds": video["duration_seconds"],
        },
        "deterministic_summary": {
            "overall_attention_score": summary.get("overall_attention_score"),
            "monetization_opportunity_score": summary.get("monetization_opportunity_score"),
            "overall_drop_risk_score": summary.get("overall_drop_risk_score"),
            "brand_safety_score": summary.get("brand_safety_score"),
            "transcript_clarity_score": summary.get("transcript_clarity_score"),
            "visual_quality_score": summary.get("visual_quality_score"),
            "creator_readiness_score": summary.get("creator_readiness_score"),
            "recommendation_status": summary.get("recommendation_status"),
            "recommendation_message": summary.get("recommendation_message"),
            "top_ad_category": summary.get("top_ad_category"),
        },
        "selected_segments": selected,
    }


def persist_runpod_insights(
    video_id: str,
    settings: RunPodSettings,
    status: str,
    content: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = utc_now()
    execute(
        """
        insert into ai_insights (video_id, provider, model, status, content_json, error, created_at, updated_at)
        values (?, 'runpod', ?, ?, ?, ?, ?, ?)
        on conflict(video_id) do update set
          provider = excluded.provider,
          model = excluded.model,
          status = excluded.status,
          content_json = excluded.content_json,
          error = excluded.error,
          updated_at = excluded.updated_at
        """,
        (
            video_id,
            settings.model,
            status,
            json.dumps(content) if content is not None else None,
            bounded_text(error, 500) if error else None,
            now,
            now,
        ),
    )


def generate_runpod_insights(video: sqlite3.Row, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    settings = RunPodSettings.from_env()
    if not runpod_insights_enabled(settings):
        return None
    if not settings.configured:
        persist_runpod_insights(video["id"], settings, "not_configured", error="RunPod configuration is incomplete.")
        return None
    try:
        result = RunPodClient(settings).chat_json(
            system_prompt=RUNPOD_INSIGHT_SYSTEM_PROMPT,
            user_payload=build_runpod_evidence_payload(video, segments),
            temperature=0.2,
        )
        normalized = normalize_runpod_insights(result)
        if not normalized["executive_summary"]:
            raise RunPodError("RunPod response did not include an executive summary.")
        persist_runpod_insights(video["id"], settings, "completed", content=normalized)
        return normalized
    except RunPodError as exc:
        persist_runpod_insights(video["id"], settings, "failed", error=str(exc))
        if env_enabled("NEUROAD_REQUIRE_RUNPOD_INSIGHTS", False):
            raise
        return None


def get_runpod_insights(video_id: str) -> dict[str, Any] | None:
    row = query_one("select * from ai_insights where video_id = ?", (video_id,))
    if not row:
        return None
    content: dict[str, Any] | None = None
    if row["content_json"]:
        try:
            parsed = json.loads(row["content_json"])
            content = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            content = None
    return {
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "content": content,
        "error": row["error"],
        "updated_at": row["updated_at"],
    }


INSIGHT_MAX_ATTEMPTS = max(1, int_from_env("NEUROAD_INSIGHT_JOB_MAX_ATTEMPTS", 3))


def redact_insight_text(value: Any) -> str:
    """Remove contact identifiers before OCR or transcript snippets leave Railway."""
    text = str(value or "")
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted email]", text)
    text = re.sub(r"\b(?:https?://|www\.)\S+\b", "[redacted URL]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d() .-]{7,}\d)(?!\w)", "[redacted phone]", text)
    return bounded_text(text, 1200)


def video_insight_fingerprint(video_id: str) -> str:
    video = get_video_or_404(video_id)
    segments = query_all("select * from segments where video_id = ? order by start_time", (video_id,))
    evidence: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = segment["id"]
        evidence.append(
            {
                "segment": {key: segment[key] for key in (
                    "id", "start_time", "end_time", "attention_score", "ad_fit_score", "drop_risk_score",
                    "brand_safety_score", "transcript", "transcript_insights", "visual_evidence", "score_reasons",
                    "recommendation", "ad_slot_score", "ad_slot_reasons",
                )},
                "objects": [dict(row) for row in query_all("select label, confidence, bbox, frame_timestamp from detected_objects where segment_id = ? order by confidence desc", (segment_id,))],
                "topics": [dict(row) for row in query_all("select label, confidence from topics where segment_id = ? order by confidence desc", (segment_id,))],
                "matches": [dict(row) for row in query_all("select ad_category, ad_fit_score, reason, confidence from ad_matches where segment_id = ? order by ad_fit_score desc", (segment_id,))],
                "ocr": [dict(row) for row in query_all("select text, confidence, bbox, frame_timestamp from detected_text where segment_id = ? order by confidence desc", (segment_id,))],
            }
        )
    raw = json.dumps({"video_id": video_id, "title": video["title"], "duration": video["duration_seconds"], "evidence": evidence}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def comparison_insight_fingerprint(comparison_id: str) -> str:
    members = query_all("select video_id, display_order from comparison_videos where comparison_id = ? order by display_order", (comparison_id,))
    raw = json.dumps(
        {"comparison_id": comparison_id, "videos": [{"video_id": row["video_id"], "fingerprint": video_insight_fingerprint(row["video_id"])} for row in members]},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def insight_prompt_version(target_type: str) -> str:
    return VIDEO_PROMPT_VERSION if target_type == "video" else COMPARISON_PROMPT_VERSION


def detailed_insight_status(target_type: str, target_id: str) -> dict[str, Any] | None:
    try:
        fingerprint = video_insight_fingerprint(target_id) if target_type == "video" else comparison_insight_fingerprint(target_id)
    except HTTPException:
        return None
    row = query_one(
        "select * from insight_reports where target_type = ? and target_id = ? and input_fingerprint = ? and prompt_version = ?",
        (target_type, target_id, fingerprint, insight_prompt_version(target_type)),
    )
    if not row:
        return None
    job = query_one("select * from insight_jobs where report_id = ? order by updated_at desc limit 1", (row["id"],))
    return {
        "report_id": row["id"], "status": row["status"], "job_id": job["id"] if job else None,
        "progress": job["progress"] if job else (100 if row["status"] == "completed" else 0),
        "stage": job["stage"] if job else row["status"],
        "report_url": f"/api/insight-reports/{row['id']}" if row["status"] == "completed" else None,
    }


def build_video_insight_evidence(video_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str]]:
    video = get_video_or_404(video_id)
    payload = build_analysis_payload(video)
    valid_segments: dict[str, dict[str, Any]] = {}
    evidence_segments: list[dict[str, Any]] = []
    ranked = sorted(payload["segments"], key=lambda item: (item.get("ad_slot_score", 0), item.get("ad_fit_score", 0)), reverse=True)
    selected_ids = {item["id"] for item in (ranked[:6] + sorted(payload["segments"], key=lambda item: item.get("attention_score", 0))[:2])}
    for segment in payload["segments"]:
        segment_evidence = {
            "video_id": video_id, "start": segment["start"], "end": segment["end"],
            "transcript": redact_insight_text(segment.get("transcript")),
            "objects": [{"label": item["label"], "confidence": item["confidence"], "timestamp": item.get("frame_timestamp")} for item in segment.get("objects", [])[:12]],
            "topics": [{"label": item["label"], "confidence": item["confidence"]} for item in segment.get("topics", [])[:8]],
            "ocr": [redact_insight_text(item.get("text")) for item in segment.get("detected_text", [])[:6]],
            "scores": {key: segment.get(key, 0) for key in ("attention_score", "ad_fit_score", "ad_slot_score", "brand_safety_score", "drop_risk_score")},
            "ad_matches": [{"category": item["ad_category"], "score": item["ad_fit_score"], "reason": item["reason"]} for item in segment.get("ad_matches", [])[:5]],
        }
        valid_segments[segment["id"]] = segment_evidence
        if segment["id"] in selected_ids:
            evidence_segments.append({"segment_id": segment["id"], **segment_evidence})
    return {
        "target": {"type": "video", "id": video_id, "title": video["title"], "summary": payload["summary"]},
        "keywords": extract_video_keywords(payload), "segments": evidence_segments,
        "instructions": "Only cite listed segment_id values as evidence_refs.",
    }, valid_segments, {video_id}


def build_comparison_insight_evidence(comparison_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str]]:
    comparison = get_comparison_or_404(comparison_id)
    member_rows = query_all("select video_id from comparison_videos where comparison_id = ? order by display_order limit 5", (comparison_id,))
    valid_segments: dict[str, dict[str, Any]] = {}
    videos: list[dict[str, Any]] = []
    for member in member_rows:
        video = get_video_or_404(member["video_id"])
        if video["status"] != "completed":
            continue
        evidence, segments, _ = build_video_insight_evidence(video["id"])
        selected = sorted(segments.items(), key=lambda item: item[1]["scores"].get("ad_slot_score", 0), reverse=True)[:4]
        valid_segments.update(segments)
        videos.append({"video_id": video["id"], "title": video["title"], "summary": evidence["target"]["summary"], "segments": [{"segment_id": segment_id, **item} for segment_id, item in selected]})
    return {"target": {"type": "comparison", "id": comparison_id, "title": comparison["title"]}, "videos": videos, "instructions": "Only cite listed segment_id and video_id values."}, valid_segments, {item["video_id"] for item in videos}


def update_insight_job(job_id: str, status: str, progress: int, stage: str, error: str | None = None) -> None:
    execute("update insight_jobs set status = ?, progress = ?, stage = ?, error = ?, updated_at = ? where id = ?", (status, progress, stage, bounded_text(error, 800) if error else None, utc_now(), job_id))


def process_insight_job(job_id: str) -> None:
    job = query_one("select * from insight_jobs where id = ?", (job_id,))
    if not job or job["status"] == "completed":
        return
    analytics_context = analytics_context_from_row(job)
    settings = RunPodSettings.from_env()
    if not runpod_insights_enabled(settings) or not settings.configured:
        INSIGHT_LOGGER.warning("Insight job %s cannot run because RunPod is not configured.", job_id)
        error = runpod_configuration_error(settings)
        update_insight_job(job_id, "failed", 100, "failed", error)
        execute("update insight_reports set status = 'failed', updated_at = ? where id = ?", (utc_now(), job["report_id"]))
        capture_event(
            "insight_report_failed",
            analytics_context,
            {
                "insight_job_id": job_id,
                "report_id": job["report_id"],
                "target_type": job["target_type"],
                "processing_duration_ms": elapsed_ms(job["created_at"]),
                "error_code": "insight_not_configured",
            },
            insert_id=f"insight_report:{job_id}:failed",
        )
        return
    execute("update insight_jobs set attempts = attempts + 1 where id = ?", (job_id,))
    try:
        update_insight_job(job_id, "processing", 15, "preparing_evidence")
        if job["target_type"] == "video":
            evidence, valid_segments, valid_video_ids = build_video_insight_evidence(job["target_id"])
            system_prompt = VIDEO_SYSTEM_PROMPT
        else:
            evidence, valid_segments, valid_video_ids = build_comparison_insight_evidence(job["target_id"])
            system_prompt = COMPARISON_SYSTEM_PROMPT
        if not valid_segments:
            raise RunPodError("No completed deterministic evidence is available for this report.")
        update_insight_job(job_id, "processing", 35, "generating")
        raw = RunPodClient(settings).chat_json(system_prompt=system_prompt, user_payload=evidence, temperature=0.2)
        update_insight_job(job_id, "processing", 75, "validating")
        report = normalize_report(raw, report_type=job["target_type"], report_id=job["report_id"], target_id=job["target_id"], fingerprint=job["input_fingerprint"], model=settings.model, valid_segments=valid_segments, valid_video_ids=valid_video_ids)
        update_insight_job(job_id, "processing", 90, "publishing")
        # The validated canonical report is stored in SQLite and rendered only in the NeuroAd dashboard.
        # We deliberately do not generate PDF/JSON files for this interactive report experience.
        execute("update insight_reports set status = 'completed', content_json = ?, json_path = null, pdf_path = null, updated_at = ? where id = ?", (json.dumps(report), utc_now(), job["report_id"]))
        update_insight_job(job_id, "completed", 100, "completed")
        capture_event(
            "insight_report_completed",
            analytics_context,
            {
                "insight_job_id": job_id,
                "report_id": job["report_id"],
                "target_type": job["target_type"],
                "video_id": job["target_id"] if job["target_type"] == "video" else None,
                "comparison_id": job["target_id"] if job["target_type"] == "comparison" else None,
                "processing_duration_ms": elapsed_ms(job["created_at"]),
                "result_status": "completed",
            },
            insert_id=f"insight_report:{job_id}:completed",
        )
    except Exception as exc:
        # Keep Railway logs actionable while the API/UI receive only the safe public error.
        INSIGHT_LOGGER.exception(
            "Insight job failed: job_id=%s target_type=%s target_id=%s stage=%s",
            job_id,
            job["target_type"],
            job["target_id"],
            "processing",
        )
        update_insight_job(job_id, "failed", 100, "failed", public_job_error(exc))
        execute("update insight_reports set status = 'failed', updated_at = ? where id = ?", (utc_now(), job["report_id"]))
        capture_event(
            "insight_report_failed",
            analytics_context,
            {
                "insight_job_id": job_id,
                "report_id": job["report_id"],
                "target_type": job["target_type"],
                "video_id": job["target_id"] if job["target_type"] == "video" else None,
                "comparison_id": job["target_id"] if job["target_type"] == "comparison" else None,
                "processing_duration_ms": elapsed_ms(job["created_at"]),
                "error_code": analytics_error_code(exc),
                "result_status": "failed",
            },
            insert_id=f"insight_report:{job_id}:failed",
        )


def recover_insight_jobs() -> None:
    """Requeue unfinished jobs after a Railway process restart."""
    jobs = query_all("select * from insight_jobs where status in ('queued', 'processing')")
    for job in jobs:
        if int(job["attempts"] or 0) >= INSIGHT_MAX_ATTEMPTS:
            update_insight_job(job["id"], "failed", 100, "failed", "Insight retry limit reached after restart.")
            continue
        update_insight_job(job["id"], "queued", 0, "queued")
        INSIGHT_EXECUTOR.submit(process_insight_job, job["id"])
def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def cache_json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported extractor-cache value: {type(value).__name__}")


def extractor_configuration_hash(configuration: dict[str, Any]) -> str:
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":"), default=cache_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extractor_cache_key(
    source_hash: str, extractor: str, extractor_version: str, configuration: dict[str, Any]
) -> tuple[str, str]:
    configuration_hash = extractor_configuration_hash(configuration)
    material = f"{source_hash}:{extractor}:{extractor_version}:{configuration_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), configuration_hash


def read_extractor_cache(
    source_hash: str, extractor: str, extractor_version: str, configuration: dict[str, Any]
) -> dict[str, Any] | None:
    if not env_enabled("NEUROAD_ENABLE_EXTRACTOR_CACHE", True):
        return None
    cache_key, _ = extractor_cache_key(source_hash, extractor, extractor_version, configuration)
    row = query_one("select payload from extractor_cache where cache_key = ?", (cache_key,))
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        execute("delete from extractor_cache where cache_key = ?", (cache_key,))
        return None
    execute("update extractor_cache set last_accessed_at = ? where cache_key = ?", (utc_now(), cache_key))
    return payload if isinstance(payload, dict) else None


def write_extractor_cache(
    source_hash: str,
    extractor: str,
    extractor_version: str,
    configuration: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    if not env_enabled("NEUROAD_ENABLE_EXTRACTOR_CACHE", True):
        return
    cache_key, configuration_hash = extractor_cache_key(
        source_hash, extractor, extractor_version, configuration
    )
    now = utc_now()
    serialized = json.dumps(payload, separators=(",", ":"), default=cache_json_default)
    execute(
        """
        insert into extractor_cache
        (cache_key, source_hash, extractor, extractor_version, configuration_hash, payload, created_at, last_accessed_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(cache_key) do update set payload = excluded.payload, last_accessed_at = excluded.last_accessed_at
        """,
        (cache_key, source_hash, extractor, extractor_version, configuration_hash, serialized, now, now),
    )


def indexed_cache_payload(value: Any) -> dict[int, Any]:
    if not isinstance(value, dict):
        return {}
    output: dict[int, Any] = {}
    for key, item in value.items():
        try:
            output[int(key)] = item
        except (TypeError, ValueError):
            continue
    return output


def serialize_frame_cache(frames: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {"frames": frames}


def restore_frame_cache(payload: dict[str, Any]) -> dict[int, dict[str, Any]] | None:
    frames = indexed_cache_payload(payload.get("frames"))
    if not frames:
        return None
    for frame in frames.values():
        path = Path(str(frame.get("path", "")))
        if not path.is_file():
            return None
        frame["path"] = path
        for sample in frame.get("sample_frames", []):
            sample_path = Path(str(sample.get("path", "")))
            if not sample_path.is_file():
                return None
            sample["path"] = sample_path
    return frames


def model_file_signature(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "ready": False}
    stats = path.stat()
    return {
        "path": str(path),
        "ready": True,
        "size": stats.st_size,
        "modified_ns": stats.st_mtime_ns,
    }


def create_analysis_run(video_id: str, source: Path, source_hash: str | None = None) -> str:
    run_id = new_id("run")
    dependencies = runtime_dependency_status()
    execute(
        """
        insert into analysis_runs
        (id, video_id, schema_version, state, source_hash, model_manifest, signal_availability, timings, error, started_at, completed_at)
        values (?, ?, ?, 'processing', ?, ?, ?, ?, null, ?, null)
        """,
        (
            run_id,
            video_id,
            ANALYSIS_SCHEMA_VERSION,
            source_hash or source_sha256(source),
            json.dumps(
                {
                    "object_detection": dependencies.get("object_detection"),
                    "ultralytics": dependencies.get("ultralytics"),
                    "faster_whisper": dependencies.get("faster_whisper"),
                }
            ),
            json.dumps({}),
            json.dumps({}),
            utc_now(),
        ),
    )
    return run_id


def finish_analysis_run(
    analysis_run_id: str, state: str, timings: dict[str, Any], signal_status: dict[str, Any] | None = None, error: str | None = None
) -> None:
    execute(
        """
        update analysis_runs
        set state = ?, timings = ?, signal_availability = ?, error = ?, completed_at = ?
        where id = ?
        """,
        (state, json.dumps(timings), json.dumps(signal_status or {}), error, utc_now(), analysis_run_id),
    )


def run_ocr_extractor_bundle(frames: dict[int, dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    return {
        "evidence": extract_ocr_signals(frames),
        "seconds": round(time.perf_counter() - started, 3),
    }


def run_audio_extractor_bundle(
    video_id: str, source: Path, segments: list[dict[str, Any]]
) -> dict[str, Any]:
    audio_started = time.perf_counter()
    audio_path = extract_audio(video_id, source)
    analysis_audio_path = prepare_audio_for_analysis(video_id, audio_path) if audio_path else None
    if analysis_audio_path:
        audio_metrics, audio_evidence = compute_audio_analysis(analysis_audio_path, segments)
    else:
        audio_metrics, audio_evidence = {}, {}
    audio_seconds = round(time.perf_counter() - audio_started, 3)

    transcript_started = time.perf_counter()
    transcript_segments = transcribe_audio(analysis_audio_path) if analysis_audio_path else []
    return {
        "metrics": audio_metrics,
        "evidence": audio_evidence,
        "transcript": transcript_segments,
        "audio_seconds": audio_seconds,
        "transcript_seconds": round(time.perf_counter() - transcript_started, 3),
    }


def run_object_extractor_bundle(
    frames: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    detector_started = time.perf_counter()
    detections = detect_objects(frames)
    detector_seconds = round(time.perf_counter() - detector_started, 3)

    face_started = time.perf_counter()
    social_evidence = extract_face_behavior_signals(frames, detections)
    return {
        "detections": detections,
        "social_evidence": social_evidence,
        "runtime": dict(OBJECT_DETECTION_RUNTIME),
        "detector_seconds": detector_seconds,
        "face_seconds": round(time.perf_counter() - face_started, 3),
    }


def process_upload_job(job_id: str, video_id: str) -> None:
    job = query_one("select * from jobs where id = ?", (job_id,))
    analytics_context = analytics_context_from_row(job)
    video = query_one("select * from videos where id = ?", (video_id,))
    if not video:
        error = "Video not found"
        update_job(job_id, "failed", 0, "metadata", error)
        capture_event(
            "analysis_failed",
            analytics_context,
            {"analysis_id": job_id, "video_id": video_id, "error_code": "video_not_found"},
            insert_id=f"analysis:{job_id}:failed",
        )
        return
    analysis_run_id: str | None = None
    source_reference: str | None = None
    run_started = time.perf_counter()
    timings: dict[str, Any] = {}
    try:
        execute("update videos set status = 'processing' where id = ?", (video_id,))
        update_job(job_id, "processing", 4, "metadata")
        if video["source_type"] == "youtube_ingest" and not video["file_path"]:
            if not video["source_url"]:
                raise RuntimeError("Missing YouTube URL for ingestion.")
            try:
                source, _, metadata = download_youtube_video(video["source_url"], video_id)
            except Exception as exc:
                if is_youtube_media_blocked(exc):
                    raise RuntimeError(
                        "YouTube blocked server-side media access, so a real media analysis cannot be generated. "
                        "Upload the video file directly to produce the report card and analysis from actual frames, audio, transcript, and objects."
                    ) from exc
                raise
            duration = probe_duration(source) or int(metadata.get("duration_seconds") or 0)
            execute(
                """
                update videos
                set file_path = ?, title = ?, description = ?, thumbnail_url = ?, duration_seconds = ?, embed_url = ?
                where id = ?
                """,
                (
                    str(source),
                    metadata["title"],
                    metadata.get("description", ""),
                    metadata.get("thumbnail_url"),
                    duration,
                    metadata.get("embed_url"),
                    video_id,
                ),
            )
            video = query_one("select * from videos where id = ?", (video_id,))
        elif video["source_type"] == "url" and not video["file_path"]:
            if not video["source_url"]:
                raise RuntimeError("Missing direct video URL for ingestion.")
            source, _ = download_remote_video(video["source_url"], video_id)
            execute("update videos set file_path = ? where id = ?", (str(source), video_id))
            video = query_one("select * from videos where id = ?", (video_id,))

        if not video or not video["file_path"]:
            raise RuntimeError("No analyzable media file is attached.")

        source_reference = str(video["file_path"])
        source = materialize_source_for_processing(source_reference, video_id)
        source = normalize_video_for_analysis(source, video_id)
        if not r2_key_from_reference(source_reference) and str(source) != video["file_path"]:
            execute("update videos set file_path = ? where id = ?", (str(source), video_id))
            video = query_one("select * from videos where id = ?", (video_id,))
        duration = probe_duration_or_raise(source)
        enforce_source_duration(duration)
        source_hash = source_sha256(source)
        analysis_run_id = create_analysis_run(video_id, source, source_hash=source_hash)
        update_job(job_id, "processing", 8, "metadata")

        segments = make_segments(duration)
        visual_configuration = {
            "schema": "shared-sequential-decode-v1",
            "opencv": installed_package_version("opencv-python-headless") or installed_package_version("opencv-python"),
            "scenedetect": installed_package_version("scenedetect"),
            "frame_sample_rate": FRAME_SAMPLE_RATE,
            "hook_sample_rate": 8.0,
            "max_frames_per_segment": MAX_FRAMES_PER_SEGMENT,
            "max_analysis_seconds": MAX_ANALYSIS_SECONDS,
            "adaptive_threshold": float_from_env("NEUROAD_SCENE_ADAPTIVE_THRESHOLD", 3.0),
            "fade_threshold": float_from_env("NEUROAD_FADE_THRESHOLD", 12.0),
        }
        cached_frames = read_extractor_cache(source_hash, "visual_decode", "v1", visual_configuration)
        frames = restore_frame_cache(cached_frames) if cached_frames else None
        visual_cache_hit = frames is not None
        if frames is None:
            step_started = time.perf_counter()
            frames = extract_frames(video_id, source, segments)
            timings["visual_decode_seconds"] = round(time.perf_counter() - step_started, 3)
            write_extractor_cache(
                source_hash, "visual_decode", "v1", visual_configuration, serialize_frame_cache(frames)
            )
        else:
            timings["visual_decode_seconds"] = 0.0
        update_job(job_id, "processing", 20, "frames")

        audio_path = extract_audio(video_id, source)
        analysis_audio_path = prepare_audio_for_analysis(video_id, audio_path) if audio_path else None
        audio_metrics = compute_audio_metrics(analysis_audio_path, segments) if analysis_audio_path else {}
        update_job(job_id, "processing", 32, "audio")

        transcript_segments = transcribe_audio(analysis_audio_path) if analysis_audio_path else []
        update_job(job_id, "processing", 48, "transcript")

        detections = detect_objects(frames)
        detected_text = detect_ocr_text(frames)
        update_job(job_id, "processing", 62, "objects")

        enriched_segments = assemble_segments(segments, frames, transcript_segments, detections, detected_text, audio_metrics, video)
        audio_configuration = {
            "schema": "multilingual-audio-speech-v1",
            "whisper_library": installed_package_version("faster-whisper"),
            "whisper_model": os.getenv("WHISPER_MODEL", "small"),
            "whisper_device": os.getenv("WHISPER_DEVICE", "cpu"),
            "whisper_compute_type": os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            "word_timestamps": env_enabled("WHISPER_WORD_TIMESTAMPS", True),
            "vad_filter": env_enabled("WHISPER_VAD_FILTER", True),
            "silero": env_enabled("NEUROAD_ENABLE_SILERO_VAD", True),
            "librosa": env_enabled("NEUROAD_ENABLE_LIBROSA", True),
            "audio_cleanup": env_enabled("NEUROAD_ENABLE_AUDIO_CLEANUP", False),
        }
        object_engine = os.getenv("NEUROAD_OBJECT_DETECTION_ENGINE", "mobilenet_ssd").lower()
        object_configuration = {
            "schema": "tracked-multi-object-v1",
            "library": installed_package_version("ultralytics"),
            "engine": object_engine,
            "environment": os.getenv("NEUROAD_ENVIRONMENT", "development").lower(),
            "license_acknowledged": env_enabled("NEUROAD_ULTRALYTICS_LICENSE_ACCEPTED", False),
            "model": model_file_signature(YOLOE_MODEL_PATH if object_engine == "yoloe" else YOLO_MODEL_PATH),
            "fallback_model": model_file_signature(YOLO_MODEL_PATH) if object_engine == "yoloe" else None,
            "prompts": yoloe_text_prompts() if object_engine == "yoloe" else [],
            "confidence": YOLO_CONFIDENCE,
            "image_size": YOLO_IMAGE_SIZE,
            "batch_size": YOLO_BATCH_SIZE,
            "face_model": model_file_signature(MEDIAPIPE_FACE_MODEL),
        }
        ocr_configuration = {
            "schema": "multilingual-keyframe-ocr-v1",
            "library": installed_package_version("paddleocr"),
            "languages": os.getenv("NEUROAD_OCR_LANGUAGES", "en,devanagari"),
            "confidence": float_from_env("NEUROAD_OCR_CONFIDENCE", 0.5),
        }
        audio_bundle = read_extractor_cache(source_hash, "audio_speech", "v1", audio_configuration)
        object_bundle = read_extractor_cache(source_hash, "object_social", "v1", object_configuration)
        ocr_bundle = read_extractor_cache(source_hash, "ocr", "v1", ocr_configuration)
        audio_cache_hit = audio_bundle is not None
        object_cache_hit = object_bundle is not None
        ocr_cache_hit = ocr_bundle is not None

        update_job(job_id, "processing", 24, "audio")
        extractor_workers = max(1, min(3, int_from_env("NEUROAD_LOCAL_EXTRACTOR_WORKERS", 3)))
        with ThreadPoolExecutor(max_workers=extractor_workers) as extractor_pool:
            audio_future = (
                None if audio_bundle is not None else extractor_pool.submit(run_audio_extractor_bundle, video_id, source, segments)
            )
            object_future = (
                None if object_bundle is not None else extractor_pool.submit(run_object_extractor_bundle, frames)
            )
            ocr_future = None if ocr_bundle is not None else extractor_pool.submit(run_ocr_extractor_bundle, frames)
            if audio_future is not None:
                audio_bundle = audio_future.result()
                write_extractor_cache(source_hash, "audio_speech", "v1", audio_configuration, audio_bundle)
            if object_future is not None:
                object_bundle = object_future.result()
                write_extractor_cache(source_hash, "object_social", "v1", object_configuration, object_bundle)
            if ocr_future is not None:
                ocr_bundle = ocr_future.result()
                write_extractor_cache(source_hash, "ocr", "v1", ocr_configuration, ocr_bundle)

        if not isinstance(audio_bundle, dict) or not isinstance(object_bundle, dict) or not isinstance(ocr_bundle, dict):
            raise RuntimeError("An extractor returned an invalid result bundle.")
        audio_bundle["metrics"] = indexed_cache_payload(audio_bundle.get("metrics"))
        audio_bundle["evidence"] = indexed_cache_payload(audio_bundle.get("evidence"))
        object_bundle["detections"] = indexed_cache_payload(object_bundle.get("detections"))
        object_bundle["social_evidence"] = indexed_cache_payload(object_bundle.get("social_evidence"))
        ocr_bundle["evidence"] = indexed_cache_payload(ocr_bundle.get("evidence"))
        if object_cache_hit and isinstance(object_bundle.get("runtime"), dict):
            OBJECT_DETECTION_RUNTIME.update(object_bundle["runtime"])

        audio_metrics = audio_bundle["metrics"]
        audio_evidence = audio_bundle["evidence"]
        transcript_segments = audio_bundle["transcript"]
        detections = object_bundle["detections"]
        social_evidence = object_bundle["social_evidence"]
        ocr_evidence = ocr_bundle["evidence"]
        detected_text = {
            segment_index: evidence.get("texts", []) if isinstance(evidence, dict) else []
            for segment_index, evidence in ocr_evidence.items()
        }
        timings["audio_extract_seconds"] = 0.0 if audio_cache_hit else audio_bundle["audio_seconds"]
        timings["transcript_seconds"] = 0.0 if audio_cache_hit else audio_bundle["transcript_seconds"]
        timings["object_detection_seconds"] = 0.0 if object_cache_hit else object_bundle["detector_seconds"]
        timings["face_behavior_seconds"] = 0.0 if object_cache_hit else object_bundle["face_seconds"]
        timings["ocr_seconds"] = 0.0 if ocr_cache_hit else ocr_bundle["seconds"]
        timings["extractor_cache_hits"] = {
            "visual_decode": visual_cache_hit,
            "audio_speech": audio_cache_hit,
            "object_social": object_cache_hit,
            "ocr": ocr_cache_hit,
        }
        update_job(job_id, "processing", 64, "objects")

        enriched_segments = assemble_segments(
            segments,
            frames,
            transcript_segments,
            detections,
            detected_text,
            audio_metrics,
            video,
            audio_evidence=audio_evidence,
            social_evidence=social_evidence,
            ocr_evidence=ocr_evidence,
        )
        semantic_configuration = {
            "schema": "multilingual-semantic-v1",
            "sentence_transformers": installed_package_version("sentence-transformers"),
            "sentence_model": os.getenv(
                "NEUROAD_SENTENCE_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
            ),
            "gliner": installed_package_version("gliner"),
            "gliner_model": os.getenv("NEUROAD_GLINER_MODEL", "urchade/gliner_multi-v2.1"),
        }
        semantic_bundle = read_extractor_cache(source_hash, "semantic", "v1", semantic_configuration)
        semantic_cache_hit = semantic_bundle is not None
        if semantic_bundle is None:
            step_started = time.perf_counter()
            semantic_evidence = extract_semantic_evidence(enriched_segments)
            timings["semantic_seconds"] = round(time.perf_counter() - step_started, 3)
            semantic_bundle = {"evidence": semantic_evidence}
            write_extractor_cache(source_hash, "semantic", "v1", semantic_configuration, semantic_bundle)
        else:
            semantic_evidence = indexed_cache_payload(semantic_bundle.get("evidence"))
            timings["semantic_seconds"] = 0.0
        timings["extractor_cache_hits"]["semantic"] = semantic_cache_hit
        for segment_index, segment in enumerate(enriched_segments):
            segment["narrative_evidence"] = semantic_evidence.get(segment_index, {"available": False})
        enrich_segments_with_signals(enriched_segments)
        update_job(job_id, "processing", 74, "topics")

        update_job(job_id, "processing", 82, "attention")
        write_analysis(video_id, enriched_segments, analysis_run_id=analysis_run_id)
        update_job(job_id, "processing", 90, "ad_scoring")

        generate_exports(video_id)
        upload_durable_artifacts(video_id)
        execute(
            "update videos set status = 'completed', duration_seconds = ?, thumbnail_url = ? where id = ?",
            (int(duration), enriched_segments[0].get("thumbnail_url") if enriched_segments else None, video_id),
        )
        timings["total_seconds"] = round(time.perf_counter() - run_started, 3)
        signal_status = build_signal_payload(enriched_segments).get("signal_availability", {})
        finish_analysis_run(analysis_run_id, "completed", timings, signal_status)
        update_job(job_id, "completed", 100, "report")
        capture_event(
            "analysis_completed",
            analytics_context,
            {
                "analysis_id": job_id,
                "video_id": video_id,
                "comparison_id": job["comparison_id"] if job and "comparison_id" in job.keys() else None,
                "workflow": "comparison" if job and job["comparison_id"] else "single",
                "source_type": video["source_type"],
                "duration_bucket": duration_bucket(duration),
                "processing_duration_ms": elapsed_ms(job["created_at"] if job else None),
                "result_status": "completed",
            },
            insert_id=f"analysis:{job_id}:completed",
        )
    except Exception as exc:
        if analysis_run_id:
            timings["total_seconds"] = round(time.perf_counter() - run_started, 3)
            finish_analysis_run(analysis_run_id, "failed", timings, error=public_job_error(exc))
        execute("update videos set status = 'failed' where id = ?", (video_id,))
        update_job(job_id, "failed", 100, "failed", public_job_error(exc))
        capture_event(
            "analysis_failed",
            analytics_context,
            {
                "analysis_id": job_id,
                "video_id": video_id,
                "comparison_id": job["comparison_id"] if job and "comparison_id" in job.keys() else None,
                "workflow": "comparison" if job and job["comparison_id"] else "single",
                "source_type": video["source_type"],
                "processing_duration_ms": elapsed_ms(job["created_at"] if job else None),
                "error_code": analytics_error_code(exc),
                "result_status": "failed",
            },
            insert_id=f"analysis:{job_id}:failed",
        )
    finally:
        if source_reference and r2_key_from_reference(source_reference):
            cleanup_r2_scratch(video_id)


def refresh_comparison_progress(comparison_id: str) -> dict[str, int]:
    rows = query_all("select processing_status from comparison_videos where comparison_id = ?", (comparison_id,))
    completed = sum(1 for row in rows if row["processing_status"] == "completed")
    failed = sum(1 for row in rows if row["processing_status"] == "failed")
    return {"total": len(rows), "completed": completed, "failed": failed}


def process_comparison_job(comparison_id: str, members: list[dict[str, Any]]) -> None:
    comparison = get_comparison_or_404(comparison_id)
    analytics_context = analytics_context_from_row(comparison)
    execute("update comparisons set status = 'processing', updated_at = ? where id = ?", (utc_now(), comparison_id))
    for member in members:
        member_id = member["id"]
        video_id = member["video_id"]
        execute(
            "update comparison_videos set processing_status = 'processing', error = null where id = ?",
            (member_id,),
        )
        job = create_video_analysis_job(video_id, comparison_id, member_id, submit=False)
        if job["status"] != "failed":
            process_upload_job(job["job_id"], video_id)
        result = query_one("select status, error from jobs where id = ?", (job["job_id"],))
        completed = bool(result and result["status"] == "completed")
        execute(
            "update comparison_videos set processing_status = ?, error = ? where id = ?",
            ("completed" if completed else "failed", None if completed else (result["error"] if result else "Analysis failed"), member_id),
        )
        progress = refresh_comparison_progress(comparison_id)
        if completed:
            video = get_video_or_404(video_id)
            payload = build_analysis_payload(video)
            category, confidence = infer_video_category(payload)
            execute(
                "update comparison_videos set inferred_category = ?, category_confidence = ? where id = ?",
                (category, confidence, member_id),
            )
        status = "processing" if progress["completed"] + progress["failed"] < progress["total"] else "partial"
        execute(
            """
            update comparisons
            set status = ?, completed_videos = ?, failed_videos = ?, updated_at = ?
            where id = ?
            """,
            (status, progress["completed"], progress["failed"], utc_now(), comparison_id),
        )
        if progress["completed"] >= COMPARISON_MIN_VIDEOS:
            persist_comparison_report(comparison_id)

    progress = refresh_comparison_progress(comparison_id)
    final_status = "completed" if progress["failed"] == 0 else ("partial" if progress["completed"] else "failed")
    execute(
        """
        update comparisons
        set status = ?, completed_videos = ?, failed_videos = ?, updated_at = ?
        where id = ?
        """,
        (final_status, progress["completed"], progress["failed"], utc_now(), comparison_id),
    )
    if progress["completed"] >= COMPARISON_MIN_VIDEOS:
        persist_comparison_report(comparison_id)
    capture_event(
        "comparison_failed" if final_status == "failed" else "comparison_completed",
        analytics_context,
        {
            "comparison_id": comparison_id,
            "workflow": "comparison",
            "video_count": progress["total"],
            "completed_video_count": progress["completed"],
            "failed_video_count": progress["failed"],
            "processing_duration_ms": elapsed_ms(comparison["created_at"]),
            "result_status": final_status,
        },
        insert_id=f"comparison:{comparison_id}:{'failed' if final_status == 'failed' else 'completed'}",
    )


def public_job_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = (exc.stderr or exc.stdout or "").strip()
        if output:
            last_line = output.splitlines()[-1]
            return f"Media processing failed: {last_line}"
        return "Media processing failed while running FFmpeg. Try a smaller MP4 file or upload the source video directly."
    return str(exc)


def is_youtube_media_blocked(exc: Exception) -> bool:
    if isinstance(exc, HTTPException):
        # We've already explicitly formatted this error message in the ingest endpoints.
        return False

    message = str(exc).lower()
    blocked_markers = [
        "sign in to confirm",
        "not a bot",
        "captcha",
        "confirm you're not a bot",
    ]
    return any(marker in message for marker in blocked_markers)


def probe_duration(path: Path) -> int:
    try:
        return int(probe_duration_or_raise(path))
    except Exception:
        return 0


def normalize_video_for_analysis(source: Path, video_id: str) -> Path:
    if source.suffix.lower() == ".mp4":
        return source

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to convert this video before analysis.")

    try:
        source.relative_to(SCRATCH_DIR)
        target = source.with_name(f"{video_id}.mp4")
    except ValueError:
        target = UPLOAD_DIR / f"{video_id}.mp4"
    if target == source:
        return source

    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        target.unlink(missing_ok=True)
        message = (exc.stderr or exc.stdout or str(exc)).strip().splitlines()
        detail = message[-1] if message else "FFmpeg could not convert this video."
        raise RuntimeError(f"Could not convert this video into MP4 for analysis: {detail}") from exc
    if target.stat().st_size > MAX_UPLOAD_BYTES:
        target.unlink(missing_ok=True)
        raise RuntimeError("Converted video exceeds the 200 MB MVP limit.")
    source.unlink(missing_ok=True)
    return target


def probe_duration_or_raise(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFmpeg/ffprobe is required. Install it with `brew install ffmpeg`.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def has_audio_stream(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return False
    return bool(result.stdout.strip())


def make_segments(duration: float) -> list[dict[str, Any]]:
    capped = min(duration, float(MAX_ANALYSIS_SECONDS)) if MAX_ANALYSIS_SECONDS > 0 else duration
    segment_size = 2.0 if capped < 60 else 5.0
    segments = []
    start = 0.0
    index = 1
    while start < capped:
        end = min(start + segment_size, capped)
        segments.append({"index": index, "start": start, "end": end})
        start = end
        index += 1
    return segments


def sample_timestamps(start: float, end: float) -> list[float]:
    duration = max(0.1, end - start)
    sample_rate = max(FRAME_SAMPLE_RATE, 8.0) if start < 5.0 else FRAME_SAMPLE_RATE
    interval = 1.0 / max(0.1, sample_rate)
    count = max(1, min(MAX_FRAMES_PER_SEGMENT, int(math.ceil(duration / interval))))
    if count == 1:
        return [(start + end) / 2]
    step = duration / count
    return [min(end - 0.05, start + step * index + step / 2) for index in range(count)]


def colorfulness_score(frame: Any) -> float:
    red, green, blue = frame[:, :, 2].astype(np.float32), frame[:, :, 1].astype(np.float32), frame[:, :, 0].astype(np.float32)
    rg = np.abs(red - green)
    yb = np.abs(0.5 * (red + green) - blue)
    value = math.sqrt(float(np.std(rg)) ** 2 + float(np.std(yb)) ** 2) + 0.3 * math.sqrt(float(np.mean(rg)) ** 2 + float(np.mean(yb)) ** 2)
    return clamp(value / 120)


def frame_metric_snapshot(frame: Any) -> dict[str, float]:
    try:
        import cv2
    except ImportError:
        return {
            "brightness": 0.5,
            "contrast": 0.0,
            "sharpness": 0.0,
            "colorfulness": 0.0,
            "saturation": 0.0,
            "edge_density": 0.0,
        }
    grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return {
        "brightness": float(np.mean(grayscale) / 255),
        "contrast": float(np.std(grayscale) / 90),
        "sharpness": clamp(float(cv2.Laplacian(grayscale, cv2.CV_64F).var()) / 500),
        "colorfulness": colorfulness_score(frame),
        "saturation": float(np.mean(hsv[:, :, 1]) / 255),
        "edge_density": float(np.mean(cv2.Canny(grayscale, 80, 160) > 0)),
    }


def extract_frames(video_id: str, source: Path, segments: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python is required for frame extraction.") from exc

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not read the uploaded video.")

    output_dir = FRAME_DIR / video_id
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = sorted(
        (timestamp, int(segment["index"]), sample_index)
        for segment in segments
        for sample_index, timestamp in enumerate(sample_timestamps(segment["start"], segment["end"]))
    )
    captured: dict[int, list[dict[str, Any]]] = {int(segment["index"]): [] for segment in segments}
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_interval = 1.0 / fps if fps > 0 else 1.0 / 30.0
    target_index = 0
    frame_index = 0
    scene_detectors: list[Any] = []
    scene_cut_frames: set[int] = set()
    try:
        from scenedetect.detectors import AdaptiveDetector, ThresholdDetector

        scene_detectors = [
            AdaptiveDetector(
                adaptive_threshold=float_from_env("NEUROAD_SCENE_ADAPTIVE_THRESHOLD", 3.0),
                min_scene_len=max(3, int((fps or 30) * 0.3)),
                window_width=2,
            ),
            ThresholdDetector(
                threshold=float_from_env("NEUROAD_FADE_THRESHOLD", 12.0),
                min_scene_len=max(3, int((fps or 30) * 0.3)),
            ),
        ]
    except ImportError:
        scene_detectors = []

    # Decode once in timestamp order. Every downstream visual extractor reuses
    # these persisted samples instead of issuing independent random seeks.
    while target_index < len(requested):
        ok, frame = cap.read()
        if not ok:
            break
        timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        if timestamp <= 0 and fps > 0:
            timestamp = frame_index / fps
        if scene_detectors:
            scene_frame = frame
            if frame.shape[1] > 640:
                scene_frame = cv2.resize(frame, (640, max(1, int(frame.shape[0] * 640 / frame.shape[1]))))
            for detector in scene_detectors:
                try:
                    scene_cut_frames.update(int(value) for value in detector.process_frame(frame_index, scene_frame))
                except Exception:
                    continue
        frame_index += 1
        while target_index < len(requested) and requested[target_index][0] <= timestamp + frame_interval / 2:
            requested_timestamp, segment_index, sample_index = requested[target_index]
            captured[segment_index].append(
                {
                    "frame": frame.copy(),
                    "timestamp": max(0.0, requested_timestamp),
                    "sample_index": sample_index,
                }
            )
            target_index += 1
    cap.release()
    for detector in scene_detectors:
        try:
            scene_cut_frames.update(int(value) for value in detector.post_process(frame_index))
        except Exception:
            continue
    scene_cut_timestamps = sorted(frame_number / (fps or 30.0) for frame_number in scene_cut_frames)

    frame_data: dict[int, dict[str, Any]] = {}
    previous_gray_small: Any | None = None
    saved_detection_frames = 0

    previous_motion = 0.0
    for segment in segments:
        segment_index = int(segment["index"])
        samples = captured.get(segment_index, [])
        if not samples:
            continue

        snapshots: list[dict[str, float]] = []
        motion_values: list[float] = []
        representative_frame: Any | None = None
        representative_timestamp = (segment["start"] + segment["end"]) / 2
        representative_gray_small: Any | None = None
        candidates: list[tuple[float, float, Any]] = []

        acceleration_values: list[float] = []
        camera_motion_values: list[float] = []
        sample_artifacts: list[dict[str, Any]] = []
        previous_segment_gray: Any | None = None

        for sample in samples:
            frame = sample["frame"]
            sample_timestamp = float(sample["timestamp"])
            snapshot = frame_metric_snapshot(frame)
            grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_small = cv2.resize(grayscale, (160, 90))
            motion = 0.0
            if previous_gray_small is not None:
                motion = float(
                    np.mean(np.abs(gray_small.astype(np.float32) - previous_gray_small.astype(np.float32))) / 255
                )
                acceleration_values.append(abs(motion - previous_motion))
                previous_motion = motion
            if previous_segment_gray is not None:
                try:
                    shift, _ = cv2.phaseCorrelate(
                        previous_segment_gray.astype(np.float32), gray_small.astype(np.float32)
                    )
                    camera_motion_values.append(clamp(math.hypot(float(shift[0]), float(shift[1])) / 40.0))
                except Exception:
                    camera_motion_values.append(0.0)
            previous_gray_small = gray_small
            candidates.append((float(snapshot["sharpness"]), sample_timestamp, frame.copy()))
            previous_segment_gray = gray_small
            motion_values.append(motion)
            snapshots.append(snapshot)

            sample_path = output_dir / f"sample_{segment_index:03d}_{int(sample['sample_index']):03d}.jpg"
            cv2.imwrite(str(sample_path), frame)
            sample_artifacts.append(
                {
                    "path": sample_path,
                    "timestamp": float(sample["timestamp"]),
                    "sharpness": snapshot["sharpness"],
                    "motion": clamp(motion),
                }
            )

        midpoint = (float(segment["start"]) + float(segment["end"])) / 2
        representative_index = min(
            range(len(samples)), key=lambda index: abs(float(samples[index]["timestamp"]) - midpoint)
        )
        representative_frame = samples[representative_index]["frame"]
        representative_timestamp = float(samples[representative_index]["timestamp"])
        frame_path = output_dir / f"frame_{segment_index:03d}.jpg"
        cv2.imwrite(str(frame_path), representative_frame)
        # Save a small, sharp/diverse set for real multi-frame inference and OCR.
        selected_samples: list[dict[str, Any]] = [{"path": frame_path, "timestamp": representative_timestamp}]
        if saved_detection_frames < DETECTION_MAX_FRAMES:
            remaining = min(DETECTION_FRAMES_PER_SEGMENT, DETECTION_MAX_FRAMES - saved_detection_frames)
            chosen: list[tuple[float, float, Any]] = []
            for candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
                if all(abs(candidate[1] - existing[1]) >= 0.35 for existing in chosen):
                    chosen.append(candidate)
                if len(chosen) >= remaining:
                    break
            selected_samples = []
            for sample_index, (_, timestamp, image) in enumerate(chosen):
                sample_path = output_dir / f"frame_{segment['index']:03d}_{sample_index + 1}.jpg"
                cv2.imwrite(str(sample_path), image)
                selected_samples.append({"path": sample_path, "timestamp": timestamp})
            saved_detection_frames += len(selected_samples)
        grayscale = cv2.cvtColor(representative_frame, cv2.COLOR_BGR2GRAY)
        metric_names = ["brightness", "contrast", "sharpness", "colorfulness", "saturation", "edge_density"]
        averaged = {
            key: float(np.mean([snapshot[key] for snapshot in snapshots]))
            for key in metric_names
        }
        mean_motion = float(np.mean(motion_values)) if motion_values else 0.0
        segment_scene_cuts = [
            timestamp
            for timestamp in scene_cut_timestamps
            if float(segment["start"]) <= timestamp < float(segment["end"])
        ]
        frame_data[segment_index] = {
            "path": frame_path,
            "sample_frames": selected_samples or [{"path": frame_path, "timestamp": representative_timestamp}],
            "sample_artifacts": sample_artifacts,
            "timestamp": representative_timestamp,
            "mean": float(np.mean(grayscale)),
            "std": float(np.std(grayscale)),
            "shape": representative_frame.shape,
            "sampled_frames": len(snapshots),
            "brightness": averaged["brightness"],
            "contrast": clamp(averaged["contrast"]),
            "sharpness": averaged["sharpness"],
            "colorfulness": averaged["colorfulness"],
            "saturation": averaged["saturation"],
            "edge_density": averaged["edge_density"],
            "clutter": clamp(averaged["edge_density"] / 0.18),
            "motion": clamp(mean_motion),
            "motion_acceleration": clamp(float(np.mean(acceleration_values)) * 4 if acceleration_values else 0.0),
            "camera_movement": clamp(float(np.mean(camera_motion_values)) if camera_motion_values else 0.0),
            "pacing_variation": clamp(float(np.std(motion_values)) * 5 if len(motion_values) > 1 else 0.0),
            "scene_boundaries": segment_scene_cuts,
            "shot_change_count": len(segment_scene_cuts),
            "scene_detector": "pyscenedetect_adaptive_threshold" if scene_detectors else "unavailable",
            "visual_quality": clamp(
                averaged["sharpness"] * 0.6 + (1 - abs(averaged["brightness"] - 0.5) * 2) * 0.4
            ),
        }
    return frame_data


def get_paddle_ocr_models() -> list[tuple[str, Any]]:
    if not env_enabled("NEUROAD_ENABLE_OCR", True):
        return []
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return []
    languages = [
        value.strip()
        for value in os.getenv("NEUROAD_OCR_LANGUAGES", "en,devanagari").split(",")
        if value.strip()
    ]
    models: list[tuple[str, Any]] = []
    for language in languages:
        if language not in PADDLE_OCR_CACHE:
            try:
                PADDLE_OCR_CACHE[language] = PaddleOCR(
                    lang=language,
                    use_doc_orientation_classify=True,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                )
            except TypeError:
                try:
                    PADDLE_OCR_CACHE[language] = PaddleOCR(lang=language, use_angle_cls=True, show_log=False)
                except Exception:
                    continue
            except Exception:
                continue
        if PADDLE_OCR_CACHE.get(language) is not None:
            models.append((language, PADDLE_OCR_CACHE[language]))
    return models


def parse_paddle_ocr_result(result: Any, language: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        data = payload.get("res", payload)
        texts = data.get("rec_texts", [])
        scores = data.get("rec_scores", [])
        boxes = data.get("dt_polys", data.get("rec_polys", []))
        for index, text in enumerate(texts):
            parsed.append(
                {
                    "text": str(text),
                    "confidence": float(scores[index]) if index < len(scores) else 0.0,
                    "box": boxes[index].tolist() if index < len(boxes) and hasattr(boxes[index], "tolist") else boxes[index] if index < len(boxes) else None,
                    "language_model": language,
                }
            )
        return parsed

    def visit(value: Any) -> None:
        if not isinstance(value, (list, tuple)):
            return
        if (
            len(value) == 2
            and isinstance(value[1], (list, tuple))
            and len(value[1]) >= 2
            and isinstance(value[1][0], str)
        ):
            parsed.append(
                {
                    "text": value[1][0],
                    "confidence": float(value[1][1]),
                    "box": value[0],
                    "language_model": language,
                }
            )
            return
        for child in value:
            visit(child)

    visit(result)
    return parsed


def ocr_box_geometry(box: Any, width: int, height: int) -> tuple[float, float]:
    if not isinstance(box, (list, tuple)) or not box:
        return 0.0, 0.0
    points = [point for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return 0.0, 0.0
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    box_width = max(xs) - min(xs)
    box_height = max(ys) - min(ys)
    return clamp(box_width * box_height / max(1, width * height)), clamp(box_height / max(1, height))


def extract_ocr_signals(frames: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    models = get_paddle_ocr_models()
    if not models:
        return {segment_index: {"available": False, "extractor": "paddleocr_ppocrv5"} for segment_index in frames}
    try:
        import cv2
    except ImportError:
        return {segment_index: {"available": False, "extractor": "paddleocr_ppocrv5"} for segment_index in frames}
    output: dict[int, dict[str, Any]] = {}
    for segment_index, frame in frames.items():
        samples = list(frame.get("sample_frames") or [])
        if not samples:
            samples = [{"path": frame["path"], "timestamp": frame["timestamp"], "sharpness": frame.get("sharpness", 0)}]
        ordered = sorted(samples, key=lambda sample: float(sample.get("timestamp", 0.0) or 0.0))
        selected = [ordered[0], ordered[-1]] if len(ordered) > 1 else [ordered[0]]
        sharpest = max(ordered, key=lambda sample: float(sample.get("sharpness", 0.0) or 0.0))
        if sharpest not in selected:
            selected.append(sharpest)
        detections: list[dict[str, Any]] = []
        for sample in selected:
            image = cv2.imread(str(sample["path"]))
            if image is None:
                continue
            height, width = image.shape[:2]
            for language, model in models:
                try:
                    if hasattr(model, "predict"):
                        raw_results = model.predict(str(sample["path"]))
                    else:
                        raw_results = model.ocr(str(sample["path"]), cls=True)
                except Exception:
                    continue
                for raw_result in raw_results or []:
                    for item in parse_paddle_ocr_result(raw_result, language):
                        text = str(item.get("text", "")).strip()
                        confidence = float(item.get("confidence", 0.0) or 0.0)
                        if not text or confidence < float_from_env("NEUROAD_OCR_CONFIDENCE", 0.5):
                            continue
                        area_ratio, height_ratio = ocr_box_geometry(item.get("box"), width, height)
                        detections.append(
                            {
                                **item,
                                "timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                                "area_ratio": round(area_ratio, 4),
                                "height_ratio": round(height_ratio, 4),
                                "mobile_readable": bool(confidence >= 0.7 and height_ratio >= 0.028),
                            }
                        )
        unique: dict[tuple[str, float], dict[str, Any]] = {}
        for item in detections:
            key = (re.sub(r"\s+", " ", item["text"].lower()).strip(), round(float(item["timestamp"]), 2))
            if key not in unique or item["confidence"] > unique[key]["confidence"]:
                unique[key] = item
        values = list(unique.values())
        output[segment_index] = {
            "available": True,
            "extractor": "paddleocr_ppocrv5",
            "texts": values,
            "text_prominence": round(max((item["area_ratio"] for item in values), default=0.0), 4),
            "text_readability": round(average_values([item["confidence"] for item in values]), 4) if values else None,
            "mobile_readable": all(item["mobile_readable"] for item in values) if values else None,
            "confidence": round(average_values([item["confidence"] for item in values]), 4) if values else 0.0,
            "sampled_keyframes": len(selected),
        }
    return output


def extract_audio(video_id: str, source: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for audio extraction. Install it with `brew install ffmpeg`.")
    if not has_audio_stream(source):
        return None
    target = AUDIO_DIR / f"{video_id}.wav"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(target)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        target.unlink(missing_ok=True)
        return None
    return target


def prepare_audio_for_analysis(video_id: str, audio_path: Path) -> Path:
    cleaned = cleanup_audio_with_uvr(video_id, audio_path)
    return apply_vad_to_audio(video_id, cleaned)


def cleanup_audio_with_uvr(video_id: str, audio_path: Path) -> Path:
    if not env_enabled("NEUROAD_ENABLE_AUDIO_CLEANUP", False):
        return audio_path
    engine = os.getenv("NEUROAD_AUDIO_CLEANUP_ENGINE", "uvr").lower()
    if engine != "uvr":
        return audio_path

    command = os.getenv("NEUROAD_UVR_COMMAND", "audio-separator")
    executable = shutil.which(command)
    if not executable:
        return audio_path

    output_dir = AUDIO_DIR / f"{video_id}_uvr"
    output_dir.mkdir(parents=True, exist_ok=True)
    before = set(output_dir.glob("*.wav"))
    args = [
        executable,
        str(audio_path),
        "--output_dir",
        str(output_dir),
        "--output_format",
        "WAV",
    ]
    model_name = os.getenv("NEUROAD_UVR_MODEL")
    if model_name:
        args.extend(["--model_filename", model_name])

    try:
        subprocess.run(args, capture_output=True, text=True, check=True, timeout=int_from_env("NEUROAD_UVR_TIMEOUT_SECONDS", 180))
    except Exception:
        return audio_path

    candidate = select_uvr_vocal_output(output_dir, before)
    if not candidate:
        return audio_path
    normalized = AUDIO_DIR / f"{video_id}_uvr.wav"
    return normalize_audio_to_wav(candidate, normalized) or audio_path


def select_uvr_vocal_output(output_dir: Path, before: set[Path]) -> Path | None:
    outputs = [path for path in output_dir.glob("*.wav") if path not in before and path.exists()]
    if not outputs:
        return None
    vocal_outputs = [path for path in outputs if "vocal" in path.name.lower() or "instrumental" not in path.name.lower()]
    candidates = vocal_outputs or outputs
    return max(candidates, key=lambda path: path.stat().st_size)


def normalize_audio_to_wav(source: Path, target: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(target)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        target.unlink(missing_ok=True)
        return None
    return target if target.exists() else None


def apply_vad_to_audio(video_id: str, audio_path: Path) -> Path:
    if not env_enabled("NEUROAD_ENABLE_VAD", False):
        return audio_path
    try:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except wave.Error:
        return audio_path
    if channels != 1 or sample_width != 2 or rate <= 0:
        return audio_path

    samples = np.frombuffer(frames, dtype=np.int16).copy()
    if samples.size == 0:
        return audio_path
    frame_ms = max(10, int_from_env("NEUROAD_VAD_FRAME_MS", 30))
    chunk_size = max(1, int(rate * frame_ms / 1000))
    rms_values = []
    for start in range(0, samples.size, chunk_size):
        chunk = samples[start : start + chunk_size].astype(np.float32) / 32768
        rms_values.append(float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0)
    if not rms_values:
        return audio_path

    base_threshold = float_from_env("NEUROAD_VAD_RMS_THRESHOLD", 0.012)
    dynamic_threshold = float(np.percentile(rms_values, 35)) * 2.5
    threshold = max(base_threshold, dynamic_threshold)
    speech_chunks = np.array(rms_values) >= threshold
    if not bool(np.any(speech_chunks)):
        return audio_path

    padding_chunks = max(0, int_from_env("NEUROAD_VAD_PADDING_CHUNKS", 2))
    expanded = speech_chunks.copy()
    for index, is_speech in enumerate(speech_chunks):
        if is_speech:
            left = max(0, index - padding_chunks)
            right = min(len(expanded), index + padding_chunks + 1)
            expanded[left:right] = True

    masked = np.zeros_like(samples)
    for index, keep in enumerate(expanded):
        if keep:
            start = index * chunk_size
            end = min(samples.size, start + chunk_size)
            masked[start:end] = samples[start:end]

    target = AUDIO_DIR / f"{video_id}_vad.wav"
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(masked.astype(np.int16).tobytes())
    return target


def compute_audio_metrics(audio_path: Path, segments: list[dict[str, Any]]) -> dict[int, float]:
    metrics, _ = compute_audio_analysis(audio_path, segments)
    return metrics


def silero_speech_ranges(samples: np.ndarray[Any, Any], rate: int) -> tuple[list[tuple[float, float]], str]:
    global SILERO_VAD_MODEL_CACHE
    if not env_enabled("NEUROAD_ENABLE_SILERO_VAD", True):
        return [], "energy_fallback"
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad
    except ImportError:
        return [], "energy_fallback"
    try:
        if SILERO_VAD_MODEL_CACHE is None:
            SILERO_VAD_MODEL_CACHE = load_silero_vad(onnx=True)
        waveform = torch.from_numpy((samples / 32768.0).astype(np.float32))
        timestamps = get_speech_timestamps(
            waveform,
            SILERO_VAD_MODEL_CACHE,
            sampling_rate=rate,
            threshold=float_from_env("NEUROAD_SILERO_THRESHOLD", 0.5),
            min_silence_duration_ms=int_from_env("NEUROAD_SILERO_MIN_SILENCE_MS", 300),
            return_seconds=True,
        )
        return [
            (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0))
            for item in timestamps
        ], "silero_vad_onnx"
    except Exception:
        return [], "energy_fallback"


def librosa_audio_features(samples: np.ndarray[Any, Any], rate: int) -> dict[str, Any]:
    if not env_enabled("NEUROAD_ENABLE_LIBROSA", True) or samples.size < rate // 2:
        return {"available": False}
    try:
        import librosa
    except ImportError:
        return {"available": False}
    try:
        onset_envelope = librosa.onset.onset_strength(y=samples, sr=rate, hop_length=320)
        tempo_values = librosa.feature.tempo(onset_envelope=onset_envelope, sr=rate, hop_length=320)
        f0, _, voiced_probabilities = librosa.pyin(
            samples,
            fmin=65,
            fmax=500,
            sr=rate,
            frame_length=1024,
            hop_length=320,
        )
        voiced_f0 = f0[np.isfinite(f0)] if f0 is not None else np.array([])
        voiced_probabilities = voiced_probabilities[np.isfinite(voiced_probabilities)] if voiced_probabilities is not None else np.array([])
        return {
            "available": True,
            "tempo_bpm": round(float(np.mean(tempo_values)), 2) if tempo_values.size else None,
            "pitch_variation": round(float(np.std(voiced_f0) / max(1.0, np.mean(voiced_f0))), 4) if voiced_f0.size > 1 else None,
            "voiced_probability": round(float(np.mean(voiced_probabilities)), 4) if voiced_probabilities.size else None,
            "extractor": "librosa_0_11",
        }
    except Exception:
        return {"available": False}


def compute_audio_analysis(
    audio_path: Path, segments: list[dict[str, Any]]
) -> tuple[dict[int, float], dict[int, dict[str, Any]]]:
    with wave.open(str(audio_path), "rb") as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32)
    metrics: dict[int, float] = {}
    evidence: dict[int, dict[str, Any]] = {}
    previous_energy: float | None = None
    previous_tail: np.ndarray[Any, Any] | None = None
    silence_threshold = float_from_env("NEUROAD_SILENCE_RMS_THRESHOLD", 0.008)
    speech_ranges, vad_engine = silero_speech_ranges(samples, rate)
    for segment in segments:
        start = int(segment["start"] * rate)
        end = int(segment["end"] * rate)
        chunk = samples[start:end]
        if chunk.size == 0:
            metrics[segment["index"]] = 0.0
            evidence[segment["index"]] = {
                "available": False,
                "audio_energy": None,
                "silence_duration": None,
            }
            continue
        normalized = chunk / 32768.0
        rms = float(np.sqrt(np.mean(np.square(normalized))))
        energy = clamp(rms * 4)
        metrics[segment["index"]] = energy
        hop = max(1, int(rate * 0.02))
        window_rms = np.asarray(
            [
                float(np.sqrt(np.mean(np.square(normalized[index : index + hop]))))
                for index in range(0, normalized.size, hop)
                if normalized[index : index + hop].size
            ],
            dtype=np.float32,
        )
        silent_windows = int(np.sum(window_rms < silence_threshold)) if window_rms.size else 0
        segment_duration = float(segment["end"] - segment["start"])
        energy_silence_duration = min(segment_duration, silent_windows * hop / rate)
        speech_duration = sum(
            max(0.0, min(float(segment["end"]), speech_end) - max(float(segment["start"]), speech_start))
            for speech_start, speech_end in speech_ranges
        )
        silence_duration = max(0.0, segment_duration - speech_duration) if vad_engine == "silero_vad_onnx" else energy_silence_duration
        spectrum = np.abs(np.fft.rfft(normalized * np.hanning(normalized.size))) if normalized.size > 8 else np.array([])
        frequencies = np.fft.rfftfreq(normalized.size, 1 / rate) if spectrum.size else np.array([])
        total_spectral_energy = float(np.sum(spectrum)) if spectrum.size else 0.0
        voice_band_energy = (
            float(np.sum(spectrum[(frequencies >= 300) & (frequencies <= 3400)])) if spectrum.size else 0.0
        )
        spectral_centroid = (
            float(np.sum(frequencies * spectrum) / total_spectral_energy) if total_spectral_energy > 0 else None
        )
        zero_crossing_rate = float(np.mean(np.abs(np.diff(np.signbit(normalized))))) if normalized.size > 1 else 0.0
        onset_strength = np.maximum(0.0, np.diff(window_rms)) if window_rms.size > 1 else np.array([])
        onset_threshold = float(np.mean(onset_strength) + np.std(onset_strength)) if onset_strength.size else 1.0
        onset_count = int(np.sum(onset_strength > onset_threshold)) if onset_strength.size else 0
        waveform_bucket_count = min(80, int(window_rms.size))
        waveform_energy = []
        if waveform_bucket_count:
            bucket_edges = np.linspace(0, window_rms.size, waveform_bucket_count + 1, dtype=int)
            waveform_energy = [
                round(clamp(float(np.mean(window_rms[bucket_edges[index] : bucket_edges[index + 1]])) * 4), 4)
                for index in range(waveform_bucket_count)
                if bucket_edges[index + 1] > bucket_edges[index]
            ]
        discontinuity = None
        if previous_tail is not None and previous_tail.size and normalized.size:
            discontinuity = clamp(abs(float(np.mean(np.abs(normalized[:hop]))) - float(np.mean(np.abs(previous_tail)))) * 8)
        librosa_features = librosa_audio_features(normalized.astype(np.float32), rate)
        evidence[segment["index"]] = {
            "available": True,
            "audio_energy": round(energy, 4),
            "rms_db": round(20 * math.log10(max(rms, 1e-8)), 2),
            "peak_db": round(20 * math.log10(max(float(np.max(np.abs(normalized))), 1e-8)), 2),
            "sudden_volume_change": round(abs(energy - previous_energy), 4) if previous_energy is not None else None,
            "silence_duration": round(silence_duration, 3),
            "silence_ratio": round(silence_duration / max(0.1, float(segment["end"] - segment["start"])), 4),
            "speech_duration": round(speech_duration, 3) if vad_engine == "silero_vad_onnx" else None,
            "vad_engine": vad_engine,
            "voice_band_ratio": round(voice_band_energy / total_spectral_energy, 4) if total_spectral_energy > 0 else None,
            "voice_clarity": round(clamp((voice_band_energy / total_spectral_energy) * 1.8), 4)
            if total_spectral_energy > 0
            else None,
            "spectral_centroid_hz": round(spectral_centroid, 2) if spectral_centroid is not None else None,
            "zero_crossing_rate": round(zero_crossing_rate, 4),
            "beat_onset_density": round(onset_count / max(0.1, float(segment["end"] - segment["start"])), 3),
            "waveform_energy": waveform_energy,
            "sudden_audio_discontinuity": round(discontinuity, 4) if discontinuity is not None else None,
            **librosa_features,
            "extractor": "numpy_waveform_v1",
            "feature_extractors": [
                "numpy_waveform_v1",
                *(["silero_vad_onnx"] if vad_engine == "silero_vad_onnx" else ["energy_vad"]),
                *(["librosa_0_11"] if librosa_features.get("available") else []),
            ],
            "confidence": 0.9 if vad_engine == "silero_vad_onnx" else 0.72,
        }
        previous_energy = energy
        previous_tail = normalized[-hop:]
    return metrics, evidence


def transcribe_audio(audio_path: Path) -> list[dict[str, Any]]:
    if os.getenv("NEUROAD_ENABLE_TRANSCRIPTION", "1").lower() in {"0", "false", "no", "off"}:
        return []
    engine = os.getenv("NEUROAD_TRANSCRIPTION_ENGINE", "faster_whisper").lower()
    if engine in {"faster_whisper", "faster-whisper"}:
        try:
            return transcribe_audio_faster_whisper(audio_path)
        except ImportError as exc:
            if os.getenv("NEUROAD_REQUIRE_TRANSCRIPTION", "0").lower() in {"1", "true", "yes", "on"}:
                raise RuntimeError("faster-whisper is required for transcription.") from exc
            return transcribe_audio_vosk(audio_path)
    if engine == "vosk":
        return transcribe_audio_vosk(audio_path)
    if engine != "whisper":
        return []
    try:
        import whisper
    except ImportError as exc:
        if os.getenv("NEUROAD_REQUIRE_TRANSCRIPTION", "0").lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("openai-whisper is required for transcription.") from exc
        return []
    model_name = os.getenv("WHISPER_MODEL", "tiny")
    model = whisper.load_model(model_name)
    result = model.transcribe(str(audio_path), fp16=False)
    return result.get("segments", [])


def get_faster_whisper_model() -> Any:
    global FASTER_WHISPER_MODEL_CACHE, FASTER_WHISPER_MODEL_SIGNATURE
    model_name = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    signature = (model_name, device, compute_type)
    if FASTER_WHISPER_MODEL_CACHE is not None and FASTER_WHISPER_MODEL_SIGNATURE == signature:
        return FASTER_WHISPER_MODEL_CACHE
    from faster_whisper import WhisperModel

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    FASTER_WHISPER_MODEL_CACHE = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=str(MODEL_DIR),
        cpu_threads=max(1, int_from_env("WHISPER_CPU_THREADS", 4)),
        num_workers=1,
    )
    FASTER_WHISPER_MODEL_SIGNATURE = signature
    return FASTER_WHISPER_MODEL_CACHE


def transcribe_audio_faster_whisper(audio_path: Path) -> list[dict[str, Any]]:
    model = get_faster_whisper_model()
    vad_filter = env_enabled("WHISPER_VAD_FILTER", True)
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=max(1, int_from_env("WHISPER_BEAM_SIZE", 5)),
        word_timestamps=env_enabled("WHISPER_WORD_TIMESTAMPS", True),
        vad_filter=vad_filter,
        vad_parameters={"min_silence_duration_ms": int_from_env("WHISPER_VAD_MIN_SILENCE_MS", 500)},
        condition_on_previous_text=env_enabled("WHISPER_CONDITION_ON_PREVIOUS_TEXT", False),
    )
    output: list[dict[str, Any]] = []
    language = getattr(info, "language", None)
    language_probability = float(getattr(info, "language_probability", 0.0) or 0.0)
    for index, segment in enumerate(segments):
        text = str(getattr(segment, "text", "")).strip()
        if not text:
            continue
        words = [
            {
                "word": str(getattr(word, "word", "")).strip(),
                "start": float(getattr(word, "start", 0.0) or 0.0),
                "end": float(getattr(word, "end", 0.0) or 0.0),
                "probability": float(getattr(word, "probability", 0.0) or 0.0),
            }
            for word in (getattr(segment, "words", None) or [])
            if str(getattr(word, "word", "")).strip()
        ]
        output.append(
            {
                "index": index,
                "start": float(getattr(segment, "start", 0.0) or 0.0),
                "end": float(getattr(segment, "end", 0.0) or 0.0),
                "text": text,
                "words": words,
                "source": "faster_whisper",
                "language": language,
                "language_probability": language_probability,
                "avg_logprob": float(getattr(segment, "avg_logprob", 0.0) or 0.0),
                "no_speech_prob": float(getattr(segment, "no_speech_prob", 0.0) or 0.0),
                "compression_ratio": float(getattr(segment, "compression_ratio", 0.0) or 0.0),
            }
        )
    return output


def get_vosk_model() -> Any | None:
    global VOSK_MODEL_CACHE
    if VOSK_MODEL_CACHE is not None:
        return VOSK_MODEL_CACHE
    if not VOSK_MODEL_DIR.exists():
        if os.getenv("NEUROAD_REQUIRE_TRANSCRIPTION", "0").lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError(f"Vosk model directory is missing: {VOSK_MODEL_DIR}")
        return None
    try:
        from vosk import Model
    except ImportError as exc:
        if os.getenv("NEUROAD_REQUIRE_TRANSCRIPTION", "0").lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("vosk is required for Vosk transcription.") from exc
        return None
    VOSK_MODEL_CACHE = Model(str(VOSK_MODEL_DIR))
    return VOSK_MODEL_CACHE


def transcribe_audio_vosk(audio_path: Path) -> list[dict[str, Any]]:
    model = get_vosk_model()
    if model is None:
        return []
    from vosk import KaldiRecognizer

    transcript_segments: list[dict[str, Any]] = []
    with wave.open(str(audio_path), "rb") as wav:
        recognizer = KaldiRecognizer(model, wav.getframerate())
        recognizer.SetWords(True)
        while True:
            data = wav.readframes(4000)
            if not data:
                break
            chunk_end = wav.tell() / float(wav.getframerate())
            if recognizer.AcceptWaveform(data):
                payload = json.loads(recognizer.Result())
                transcript_segments.extend(vosk_payload_to_segments(payload, len(transcript_segments), chunk_end))
        payload = json.loads(recognizer.FinalResult())
        transcript_segments.extend(vosk_payload_to_segments(payload, len(transcript_segments), None))
    return transcript_segments


def vosk_payload_to_segments(payload: dict[str, Any], start_index: int, fallback_end: float | None) -> list[dict[str, Any]]:
    words = payload.get("result") or []
    if words:
        segments: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for word in words:
            if current and (
                float(word.get("start", 0)) - float(current[-1].get("end", 0)) > 0.8
                or float(word.get("end", 0)) - float(current[0].get("start", 0)) > 8
            ):
                segments.append(vosk_words_to_segment(current, start_index + len(segments)))
                current = []
            current.append(word)
        if current:
            segments.append(vosk_words_to_segment(current, start_index + len(segments)))
        return segments

    text = str(payload.get("text", "")).strip()
    if not text:
        return []
    end = float(fallback_end or 0)
    return [{"index": start_index, "start": max(0.0, end - 5.0), "end": end, "text": text}]


def vosk_words_to_segment(words: list[dict[str, Any]], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "start": float(words[0].get("start", 0)),
        "end": float(words[-1].get("end", words[0].get("start", 0))),
        "text": " ".join(str(word.get("word", "")).strip() for word in words if word.get("word")),
    }


def extract_semantic_evidence(segments: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    global SENTENCE_MODEL_CACHE, GLINER_MODEL_CACHE
    output = {
        index: {
            "available": False,
            "semantic_novelty": None,
            "semantic_repetition": None,
            "named_entities": [],
            "extractors": [],
        }
        for index in range(len(segments))
    }
    text_indexes = [index for index, segment in enumerate(segments) if str(segment.get("transcript", "")).strip()]
    if not text_indexes or not env_enabled("NEUROAD_ENABLE_SEMANTIC_MODELS", True):
        return output
    texts = [str(segments[index].get("transcript", "")) for index in text_indexes]
    try:
        from sentence_transformers import SentenceTransformer

        if SENTENCE_MODEL_CACHE is None:
            SENTENCE_MODEL_CACHE = SentenceTransformer(
                os.getenv("NEUROAD_SENTENCE_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"),
                cache_folder=str(MODEL_DIR),
            )
        embeddings = np.asarray(
            SENTENCE_MODEL_CACHE.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
        )
        for position, segment_index in enumerate(text_indexes):
            previous_similarities = [float(np.dot(embeddings[position], embeddings[prior])) for prior in range(position)]
            previous_similarity = previous_similarities[-1] if previous_similarities else None
            output[segment_index].update(
                {
                    "available": True,
                    "semantic_novelty": round(clamp(1 - previous_similarity), 4) if previous_similarity is not None else 1.0,
                    "semantic_repetition": round(clamp(max(previous_similarities)), 4) if previous_similarities else 0.0,
                    "topic_transition_strength": round(clamp(1 - previous_similarity), 4) if previous_similarity is not None else 0.0,
                }
            )
            output[segment_index]["extractors"].append("paraphrase_multilingual_mpnet")
    except (ImportError, OSError, RuntimeError):
        pass

    try:
        from gliner import GLiNER

        if GLINER_MODEL_CACHE is None:
            GLINER_MODEL_CACHE = GLiNER.from_pretrained(
                os.getenv("NEUROAD_GLINER_MODEL", "urchade/gliner_multi-v2.1"), cache_dir=str(MODEL_DIR)
            )
        labels = ["person", "organization", "brand", "product", "location", "call to action"]
        predictions = GLINER_MODEL_CACHE.batch_predict_entities(
            texts,
            labels,
            threshold=float_from_env("NEUROAD_GLINER_THRESHOLD", 0.45),
        )
        for segment_index, entities in zip(text_indexes, predictions):
            output[segment_index]["named_entities"] = [
                {
                    "text": str(entity.get("text", "")),
                    "label": str(entity.get("label", "entity")),
                    "confidence": round(float(entity.get("score", 0.0) or 0.0), 4),
                }
                for entity in entities[:12]
            ]
            output[segment_index]["available"] = True
            output[segment_index]["extractors"].append("gliner_multilingual")
    except (ImportError, OSError, RuntimeError, TypeError):
        pass
    return output


def detect_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    enabled = env_enabled("NEUROAD_ENABLE_OBJECT_DETECTION", True)
    engine = os.getenv("NEUROAD_OBJECT_DETECTION_ENGINE", "mobilenet_ssd").lower()
    OBJECT_DETECTION_RUNTIME.update(
        {
            "requested_engine": engine,
            "active_detector": "unavailable",
            "model": str(YOLOE_MODEL_PATH) if engine == "yoloe" else str(YOLO_MODEL_PATH) if engine == "yolo" else None,
            "fallback_reason": None,
            "degraded": True,
        }
    )
    if not enabled:
        return finalize_object_detections(
            detect_lightweight_visual_context(frames),
            detector="heuristic_disabled",
            fallback_reason="Object detection is disabled by configuration.",
        )
    if (
        engine in {"yolo", "yoloe"}
        and os.getenv("NEUROAD_ENVIRONMENT", "development").lower() == "production"
        and not env_enabled("NEUROAD_ULTRALYTICS_LICENSE_ACCEPTED", False)
    ):
        raise RuntimeError(
            "Ultralytics production use is blocked until AGPL or enterprise-license compliance is acknowledged."
        )

    try:
        if engine == "yoloe":
            detections = detect_yoloe_objects(frames)
            return finalize_object_detections(detections, detector="yoloe_gpu")
        if engine == "yolo":
            detections = detect_yolo_objects(frames)
            return finalize_object_detections(detections, detector=local_yolo_detector_name())
        if engine == "mobilenet_ssd":
            if not MOBILENET_SSD_GRAPH.is_file() or not MOBILENET_SSD_CONFIG.is_file():
                raise RuntimeError("MobileNet-SSD model files are missing.")
            detections = detect_mobilenet_ssd_objects(frames)
            return finalize_object_detections(detections, detector="mobilenet_fallback")
        if engine in {"heuristic", "lightweight"}:
            return finalize_object_detections(detect_lightweight_visual_context(frames), detector="heuristic")
        raise RuntimeError(f"Unsupported object-detection engine: {engine}")
    except Exception as primary_error:
        if object_detection_required():
            raise
        fallback_reason = f"{type(primary_error).__name__}: {primary_error}"
        try:
            if engine == "yoloe" and YOLO_MODEL_PATH.is_file():
                return finalize_object_detections(
                    detect_yolo_objects(frames),
                    detector=local_yolo_detector_name(),
                    fallback_reason=fallback_reason,
                )
            if engine != "mobilenet_ssd" and MOBILENET_SSD_GRAPH.is_file() and MOBILENET_SSD_CONFIG.is_file():
                return finalize_object_detections(
                    detect_mobilenet_ssd_objects(frames),
                    detector="mobilenet_fallback",
                    fallback_reason=fallback_reason,
                )
        except Exception as fallback_error:
            fallback_reason = f"{fallback_reason}; MobileNet fallback failed: {fallback_error}"
        return finalize_object_detections(
            detect_lightweight_visual_context(frames),
            detector="heuristic_fallback",
            fallback_reason=fallback_reason,
        )


def object_detection_required() -> bool:
    return os.getenv("NEUROAD_REQUIRE_OBJECT_DETECTION", "0").lower() in {"1", "true", "yes", "on"}


def local_yolo_detector_name() -> str:
    return "yolo26_cpu" if "yolo26" in YOLO_MODEL_PATH.name.lower() else "yolo_local"


def normalize_object_detections(detections: dict[int, list[dict[str, Any]]]) -> dict[int, list[dict[str, Any]]]:
    if not detections:
        return detections
    normalized: dict[int, list[dict[str, Any]]] = {}
    for segment_index, objects in detections.items():
        unique: list[dict[str, Any]] = []
        for item in sorted(objects, key=lambda value: float(value.get("confidence", 0.0) or 0.0), reverse=True):
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            duplicate = any(
                str(existing.get("label", "")).lower() == label.lower()
                and (
                    (
                        not isinstance(existing.get("bbox"), (list, tuple))
                        and not isinstance(item.get("bbox"), (list, tuple))
                    )
                    or (
                        abs(float(existing.get("frame_timestamp", -1000) or -1000) - float(item.get("frame_timestamp", -2000) or -2000)) < 0.01
                        and bbox_iou(existing.get("bbox"), item.get("bbox")) >= 0.97
                    )
                )
                for existing in unique
            )
            if not duplicate:
                unique.append(item)
            if len(unique) >= MAX_OBJECTS_PER_SEGMENT:
                break
        normalized[segment_index] = unique
    return normalized


def bbox_iou(first: Any, second: Any) -> float:
    if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)) or len(first) != 4 or len(second) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(value) for value in first]
    bx1, by1, bx2, by2 = [float(value) for value in second]
    intersection_width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    first_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    second_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def finalize_object_detections(
    detections: dict[int, list[dict[str, Any]]], detector: str, fallback_reason: str | None = None
) -> dict[int, list[dict[str, Any]]]:
    normalized = normalize_object_detections(detections)
    ordered_objects: list[tuple[int, dict[str, Any]]] = []
    instance_counts: Counter[tuple[int, float, str]] = Counter()
    for segment_index, objects in normalized.items():
        for item in objects:
            item["detector"] = item.get("detector") or detector
            item["evidence_kind"] = item.get("evidence_kind") or "object"
            timestamp = round(float(item.get("frame_timestamp", 0.0) or 0.0), 3)
            key = (segment_index, timestamp, str(item.get("label", "")).lower())
            item["instance_index"] = instance_counts[key]
            instance_counts[key] += 1
            ordered_objects.append((segment_index, item))
    assign_object_track_ids(ordered_objects)
    OBJECT_DETECTION_RUNTIME.update(
        {
            "active_detector": detector,
            "model": (
                str(YOLOE_MODEL_PATH)
                if detector == "yoloe_gpu"
                else str(YOLO_MODEL_PATH)
                if detector in {"yolo_local", "yolo26_cpu"}
                else None
            ),
            "fallback_reason": fallback_reason,
            "degraded": detector not in {"yolo_local", "yoloe_gpu", "yolo26_cpu"},
        }
    )
    return normalized


def assign_object_track_ids(objects: list[tuple[int, dict[str, Any]]]) -> None:
    active_tracks: dict[str, list[dict[str, Any]]] = {}
    track_counts: Counter[str] = Counter()
    ordered = sorted(objects, key=lambda item: float(item[1].get("frame_timestamp", 0.0) or 0.0))
    timestamp_usage: dict[tuple[float, str], set[str]] = {}
    for _, item in ordered:
        bbox = item.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        label = str(item.get("label", "object")).strip().lower() or "object"
        timestamp = float(item.get("frame_timestamp", 0.0) or 0.0)
        used = timestamp_usage.setdefault((round(timestamp, 3), label), set())
        candidates = [
            track
            for track in active_tracks.get(label, [])
            if timestamp >= track["timestamp"]
            and timestamp - track["timestamp"] <= 2.5
            and track["track_id"] not in used
        ]
        best = max(candidates, key=lambda track: bbox_iou(track["bbox"], bbox), default=None)
        if best is None or bbox_iou(best["bbox"], bbox) < 0.2:
            track_counts[label] += 1
            safe_label = re.sub(r"[^a-z0-9]+", "_", label).strip("_") or "object"
            best = {
                "track_id": f"{safe_label}_{track_counts[label]:03d}",
                "bbox": bbox,
                "timestamp": timestamp,
            }
            active_tracks.setdefault(label, []).append(best)
        else:
            best["bbox"] = bbox
            best["timestamp"] = timestamp
        item["track_id"] = best["track_id"]
        used.add(best["track_id"])


def detection_frame_samples(frames: dict[int, dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    samples: list[tuple[int, dict[str, Any]]] = []
    for segment_index, frame in frames.items():
        frame_samples = frame.get("sample_frames") or [{"path": frame["path"], "timestamp": frame["timestamp"]}]
        samples.extend((segment_index, sample) for sample in frame_samples)
    return sorted(samples, key=lambda item: float(item[1].get("timestamp", 0.0) or 0.0))


def yoloe_text_prompts() -> list[str]:
    configured = [
        value.strip()
        for value in os.getenv(
            "NEUROAD_YOLOE_PROMPTS",
            "person,product packaging,bottle,box,packet,sachet,tube,jar,can,cosmetics,clothing,electronics,food product,brand logo",
        ).split(",")
        if value.strip()
    ]
    return list(dict.fromkeys(configured))


def get_yoloe_model() -> Any:
    global YOLOE_MODEL_CACHE, YOLOE_MODEL_SIGNATURE
    prompts = tuple(yoloe_text_prompts())
    signature = (str(YOLOE_MODEL_PATH), prompts)
    if not YOLOE_MODEL_PATH.is_file() or YOLOE_MODEL_PATH.stat().st_size <= 0:
        raise RuntimeError(f"Configured YOLOE model is missing: {YOLOE_MODEL_PATH}")
    if YOLOE_MODEL_CACHE is not None and YOLOE_MODEL_SIGNATURE == signature:
        return YOLOE_MODEL_CACHE
    try:
        from ultralytics import YOLOE
    except ImportError as exc:
        raise RuntimeError("A YOLOE-capable ultralytics build is required for open-vocabulary detection.") from exc
    model = YOLOE(str(YOLOE_MODEL_PATH))
    model.set_classes(list(prompts))
    YOLOE_MODEL_CACHE = model
    YOLOE_MODEL_SIGNATURE = signature
    return YOLOE_MODEL_CACHE


def detect_yoloe_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    model = get_yoloe_model()
    samples = detection_frame_samples(frames)
    output: dict[int, list[dict[str, Any]]] = {segment_index: [] for segment_index in frames}
    device = os.getenv("NEUROAD_YOLOE_DEVICE", "0")
    for batch_start in range(0, len(samples), YOLO_BATCH_SIZE):
        batch = samples[batch_start : batch_start + YOLO_BATCH_SIZE]
        results = model.predict(
            source=[str(sample["path"]) for _, sample in batch],
            verbose=False,
            conf=YOLO_CONFIDENCE,
            imgsz=YOLO_IMAGE_SIZE,
            device=device,
        )
        for (segment_index, sample), result in zip(batch, results):
            names = result.names
            masks = list(result.masks.xy) if getattr(result, "masks", None) is not None else []
            frame_objects: list[dict[str, Any]] = []
            for box_index, box in enumerate(result.boxes):
                cls_id = int(box.cls[0])
                label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else names[cls_id]
                mask = masks[box_index].tolist() if box_index < len(masks) and hasattr(masks[box_index], "tolist") else None
                frame_objects.append(
                    {
                        "label": str(label),
                        "confidence": float(box.conf[0]),
                        "bbox": [float(value) for value in box.xyxy[0].tolist()],
                        "mask": mask,
                        "frame_timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                        "detector": "yoloe_gpu",
                        "evidence_kind": "object",
                    }
                )
            output[segment_index].extend(
                sorted(frame_objects, key=lambda item: item["confidence"], reverse=True)[:MAX_OBJECTS_PER_FRAME]
            )
    return output


def get_yolo_model() -> Any:
    global YOLO_MODEL_CACHE, YOLO_MODEL_SIGNATURE
    model_path = str(YOLO_MODEL_PATH)
    if not YOLO_MODEL_PATH.is_file() or YOLO_MODEL_PATH.stat().st_size <= 0:
        raise RuntimeError(f"Configured YOLO model is missing: {YOLO_MODEL_PATH}")
    if YOLO_MODEL_CACHE is not None and YOLO_MODEL_SIGNATURE == model_path:
        return YOLO_MODEL_CACHE
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("ultralytics is required for YOLO object detection.") from exc
    YOLO_MODEL_CACHE = YOLO(model_path)
    YOLO_MODEL_SIGNATURE = model_path
    return YOLO_MODEL_CACHE


def detect_yolo_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    model = get_yolo_model()
    samples = detection_frame_samples(frames)
    output: dict[int, list[dict[str, Any]]] = {segment_index: [] for segment_index in frames}
    device = os.getenv("NEUROAD_YOLO_DEVICE") or None
    for batch_start in range(0, len(samples), YOLO_BATCH_SIZE):
        batch = samples[batch_start : batch_start + YOLO_BATCH_SIZE]
        paths = [str(sample["path"]) for _, sample in batch]
        predict_kwargs: dict[str, Any] = {
            "source": paths,
            "verbose": False,
            "conf": YOLO_CONFIDENCE,
            "imgsz": YOLO_IMAGE_SIZE,
        }
        if device:
            predict_kwargs["device"] = device
        results = model.predict(**predict_kwargs)
        for (segment_index, sample), result in zip(batch, results):
            names = result.names
            frame_objects: list[dict[str, Any]] = []
            for box in result.boxes:
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                xyxy = [float(value) for value in box.xyxy[0].tolist()]
                label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else names[cls_id]
                frame_objects.append(
                    {
                        "label": str(label),
                        "confidence": confidence,
                        "bbox": xyxy,
                        "frame_timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                        "detector": local_yolo_detector_name(),
                        "evidence_kind": "object",
                    }
                )
            output[segment_index].extend(
                sorted(frame_objects, key=lambda item: item["confidence"], reverse=True)[:MAX_OBJECTS_PER_FRAME]
            )
    return output


def get_mobilenet_ssd_net() -> Any | None:
    global MOBILENET_SSD_NET_CACHE
    if MOBILENET_SSD_NET_CACHE is not None:
        return MOBILENET_SSD_NET_CACHE
    if not MOBILENET_SSD_GRAPH.exists() or not MOBILENET_SSD_CONFIG.exists():
        if object_detection_required():
            raise RuntimeError("MobileNet-SSD model files are missing.")
        return None
    try:
        import cv2
    except ImportError as exc:
        if object_detection_required():
            raise RuntimeError("opencv-python is required for MobileNet-SSD object detection.") from exc
        return None
    try:
        MOBILENET_SSD_NET_CACHE = cv2.dnn.readNetFromTensorflow(str(MOBILENET_SSD_GRAPH), str(MOBILENET_SSD_CONFIG))
    except Exception:
        if object_detection_required():
            raise
        return None
    return MOBILENET_SSD_NET_CACHE


def detect_mobilenet_ssd_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    try:
        import cv2
    except ImportError:
        return detect_lightweight_visual_context(frames)
    net = get_mobilenet_ssd_net()
    if net is None:
        return detect_lightweight_visual_context(frames)

    output: dict[int, list[dict[str, Any]]] = {segment_index: [] for segment_index in frames}
    for segment_index, sample in detection_frame_samples(frames):
        image = cv2.imread(str(sample["path"]))
        if image is None:
            continue
        height, width = image.shape[:2]
        blob = cv2.dnn.blobFromImage(image, size=(300, 300), swapRB=True, crop=False)
        net.setInput(blob)
        detections = net.forward()
        objects: list[dict[str, Any]] = []
        for detection in detections[0, 0, :, :]:
            confidence = float(detection[2])
            if confidence < 0.35:
                continue
            class_id = int(detection[1])
            label = COCO_LABELS[class_id] if 0 <= class_id < len(COCO_LABELS) else str(class_id)
            x1 = clamp(float(detection[3])) * width
            y1 = clamp(float(detection[4])) * height
            x2 = clamp(float(detection[5])) * width
            y2 = clamp(float(detection[6])) * height
            objects.append(
                {
                    "label": label,
                    "confidence": confidence,
                    "bbox": [x1, y1, x2, y2],
                    "frame_timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                    "detector": "mobilenet_fallback",
                    "evidence_kind": "object",
                }
            )
        output[segment_index].extend(
            sorted(objects, key=lambda item: item["confidence"], reverse=True)[:MAX_OBJECTS_PER_FRAME]
        )
    return output


def detect_lightweight_visual_context(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    try:
        import cv2
    except ImportError:
        return {segment_index: [] for segment_index in frames}

    face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    output: dict[int, list[dict[str, Any]]] = {segment_index: [] for segment_index in frames}
    for segment_index, sample in detection_frame_samples(frames):
        image = cv2.imread(str(sample["path"]))
        if image is None:
            continue

        height, width = image.shape[:2]
        grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        detections: list[dict[str, Any]] = []

        if not face_detector.empty():
            faces = face_detector.detectMultiScale(grayscale, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
            for x, y, w, h in faces[:3]:
                detections.append(
                    {
                        "label": "person",
                        "confidence": 0.58,
                        "bbox": [float(x), float(y), float(x + w), float(y + h)],
                        "frame_timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                        "detector": "heuristic_fallback",
                        "evidence_kind": "face_proxy",
                    }
                )

        mean_brightness = float(np.mean(grayscale))
        contrast = float(np.std(grayscale))
        edge_density = float(np.mean(cv2.Canny(grayscale, 80, 160) > 0))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = float(np.mean(hsv[:, :, 1]))

        scene_tags: list[tuple[str, float]] = []
        if edge_density > 0.09 and contrast > 42:
            scene_tags.append(("detailed scene", 0.46))
        if saturation > 80:
            scene_tags.append(("colorful scene", 0.44))
        if mean_brightness > 165:
            scene_tags.append(("bright scene", 0.42))
        elif mean_brightness < 75:
            scene_tags.append(("low light scene", 0.42))

        for label, confidence in scene_tags[: max(0, 3 - len(detections))]:
            detections.append(
                {
                    "label": label,
                    "confidence": confidence,
                    "bbox": [0.0, 0.0, float(width), float(height)],
                    "frame_timestamp": float(sample.get("timestamp", 0.0) or 0.0),
                    "detector": "heuristic_fallback",
                    "evidence_kind": "scene_tag",
                }
            )
        output[segment_index].extend(detections[:MAX_OBJECTS_PER_FRAME])
    return output


def extract_face_behavior_signals(
    frames: dict[int, dict[str, Any]], detections: dict[int, list[dict[str, Any]]]
) -> dict[int, dict[str, Any]]:
    active_segments = {
        segment_index
        for segment_index, objects in detections.items()
        if any(str(item.get("label", "")).lower() == "person" for item in objects)
    }
    if not active_segments:
        return {}
    unavailable = {
        segment_index: {
            "available": False,
            "extractor": "mediapipe_face_landmarker",
            "confidence": 0.0,
        }
        for segment_index in active_segments
    }
    if not MEDIAPIPE_FACE_MODEL.is_file():
        return unavailable
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mediapipe_python
        from mediapipe.tasks.python import vision
    except ImportError:
        return unavailable

    observations: dict[int, list[dict[str, Any]]] = {segment_index: [] for segment_index in active_segments}
    try:
        options = vision.FaceLandmarkerOptions(
            base_options=mediapipe_python.BaseOptions(model_asset_path=str(MEDIAPIPE_FACE_MODEL)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=max(1, int_from_env("NEUROAD_MAX_FACES", 4)),
            min_face_detection_confidence=float_from_env("NEUROAD_FACE_DETECTION_CONFIDENCE", 0.5),
            min_face_presence_confidence=float_from_env("NEUROAD_FACE_PRESENCE_CONFIDENCE", 0.5),
            min_tracking_confidence=float_from_env("NEUROAD_FACE_TRACKING_CONFIDENCE", 0.5),
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True,
        )
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            last_timestamp_ms = -1
            for segment_index, sample in detection_frame_samples(frames):
                if segment_index not in active_segments:
                    continue
                image = cv2.imread(str(sample["path"]))
                if image is None:
                    continue
                timestamp_ms = max(last_timestamp_ms + 1, int(float(sample.get("timestamp", 0.0) or 0.0) * 1000))
                last_timestamp_ms = timestamp_ms
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms
                )
                faces = []
                for landmarks in result.face_landmarks:
                    if len(landmarks) < 387:
                        continue
                    xs = [float(point.x) for point in landmarks]
                    ys = [float(point.y) for point in landmarks]
                    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
                    face_width = max(0.001, x2 - x1)
                    face_height = max(0.001, y2 - y1)
                    nose = landmarks[1]
                    left_eye = landmarks[33]
                    right_eye = landmarks[263]
                    eye_midpoint_x = (float(left_eye.x) + float(right_eye.x)) / 2
                    mouth_aperture = abs(float(landmarks[13].y) - float(landmarks[14].y)) / face_height
                    eye_aperture = average_values(
                        [
                            abs(float(landmarks[159].y) - float(landmarks[145].y)) / face_height,
                            abs(float(landmarks[386].y) - float(landmarks[374].y)) / face_height,
                        ]
                    )
                    faces.append(
                        {
                            "bbox_normalized": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                            "prominence": clamp(face_width * face_height),
                            "direct_to_camera": abs(float(nose.x) - eye_midpoint_x) / face_width < 0.12,
                            "nose": [float(nose.x), float(nose.y)],
                            "mouth_aperture": mouth_aperture,
                            "eye_aperture": eye_aperture,
                        }
                    )
                observations[segment_index].append(
                    {
                        "timestamp": timestamp_ms / 1000,
                        "faces": faces,
                    }
                )
    except Exception as exc:
        for item in unavailable.values():
            item["error"] = f"{type(exc).__name__}: {exc}"
        return unavailable

    output: dict[int, dict[str, Any]] = {}
    for segment_index, samples in observations.items():
        samples_with_faces = [sample for sample in samples if sample["faces"]]
        primary_faces = [max(sample["faces"], key=lambda item: item["prominence"]) for sample in samples_with_faces]
        head_movements = [
            math.hypot(
                primary_faces[index]["nose"][0] - primary_faces[index - 1]["nose"][0],
                primary_faces[index]["nose"][1] - primary_faces[index - 1]["nose"][1],
            )
            for index in range(1, len(primary_faces))
        ]
        mouth_values = [face["mouth_aperture"] for face in primary_faces]
        eye_values = [face["eye_aperture"] for face in primary_faces]
        output[segment_index] = {
            "available": bool(primary_faces),
            "extractor": "mediapipe_face_landmarker",
            "face_prominence": round(max((face["prominence"] for face in primary_faces), default=0.0), 4),
            "face_persistence": round(len(samples_with_faces) / max(1, len(samples)), 4),
            "direct_to_camera_presence": round(
                average_values([1.0 if face["direct_to_camera"] else 0.0 for face in primary_faces]), 4
            )
            if primary_faces
            else None,
            "head_movement": round(average_values(head_movements), 4) if head_movements else 0.0,
            "mouth_activity": round(float(np.std(mouth_values)), 4) if len(mouth_values) > 1 else 0.0,
            "eye_region_movement": round(float(np.std(eye_values)), 4) if len(eye_values) > 1 else 0.0,
            "facial_behaviour_change_rate": round(
                average_values(
                    [
                        average_values(head_movements),
                        float(np.std(mouth_values)) if len(mouth_values) > 1 else 0.0,
                        float(np.std(eye_values)) if len(eye_values) > 1 else 0.0,
                    ]
                ),
                4,
            ),
            "people_on_screen": max((len(sample["faces"]) for sample in samples), default=0),
            "face_boxes": [
                {"timestamp": sample["timestamp"], "boxes": [face["bbox_normalized"] for face in sample["faces"]]}
                for sample in samples_with_faces
            ],
            "confidence": round(clamp(len(samples_with_faces) / max(2, len(samples)) * 0.85), 3),
            "identity_or_emotion_inference": False,
        }
    return output


def detect_ocr_text(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Extract high-confidence visible text from one best frame per segment."""
    if not env_enabled("NEUROAD_ENABLE_OCR", True):
        return {}
    try:
        import cv2
        import pytesseract
    except ImportError:
        return {}
    if not shutil.which("tesseract"):
        return {}
    output: dict[int, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    processed = 0
    for segment_index, frame in frames.items():
        if processed >= OCR_MAX_FRAMES:
            break
        samples = frame.get("sample_frames", [{"path": frame["path"], "timestamp": frame["timestamp"]}])[:1]
        records: list[dict[str, Any]] = []
        for sample in samples:
            processed += 1
            image = cv2.imread(str(sample["path"]))
            if image is None:
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            prepared = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            data = pytesseract.image_to_data(prepared, output_type=pytesseract.Output.DICT, config="--psm 6")
            for index, value in enumerate(data.get("text", [])):
                text = redact_insight_text(value).strip()
                try:
                    confidence = float(data.get("conf", [0])[index])
                except (ValueError, TypeError, IndexError):
                    confidence = 0.0
                normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
                if confidence < OCR_CONFIDENCE or len(normalized) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                x, y, width, height = (float(data[key][index]) for key in ("left", "top", "width", "height"))
                records.append({"text": text, "confidence": confidence / 100, "bbox": [x, y, x + width, y + height], "frame_timestamp": sample["timestamp"]})
        output[segment_index] = records[:12]
    return output
def average_values(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def assemble_segments(
    segments: list[dict[str, Any]],
    frames: dict[int, dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    detections: dict[int, list[dict[str, Any]]],
    detected_text_by_segment: dict[int, list[dict[str, Any]]],
    audio_metrics: dict[int, float],
    video: sqlite3.Row,
    audio_evidence: dict[int, dict[str, Any]] | None = None,
    social_evidence: dict[int, dict[str, Any]] | None = None,
    ocr_evidence: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    previous_frame: dict[str, Any] | None = None
    previous_transcript = ""
    enriched = []
    metadata_text = " ".join([video["title"] or "", video["description"] or ""])
    audio_evidence = audio_evidence or {}
    social_evidence = social_evidence or {}
    ocr_evidence = ocr_evidence or {}

    for segment in segments:
        idx = segment["index"]
        transcript = transcript_for_segment(segment["start"], segment["end"], transcript_segments)
        transcript_evidence = transcript_evidence_for_segment(segment["start"], segment["end"], transcript_segments)
        objects = detections.get(idx, [])
        detected_text = detected_text_by_segment.get(idx, [])
        ocr_text = " ".join(str(item.get("text", "")) for item in detected_text)
        topics = classify_topics(" ".join([transcript, ocr_text, metadata_text, " ".join(obj["label"] for obj in objects)]))
        object_instances = representative_object_instances(objects)
        topics = classify_topics(" ".join([transcript, metadata_text, " ".join(obj["label"] for obj in object_instances)]))
        frame = frames.get(idx)
        visual_novelty = compute_visual_novelty(frame, previous_frame)
        motion = float(frame.get("motion", 0.0)) if frame else 0.0
        visual_quality = float(frame.get("visual_quality", 0.45)) if frame else 0.35
        scene_change = clamp(visual_novelty * 0.7 + motion * 0.3)
        if frame:
            previous_frame = frame
        object_clarity = compute_object_clarity(objects, frame)
        audio_energy = audio_metrics.get(idx, 0.0)
        segment_duration = segment["end"] - segment["start"]
        speech_density = compute_speech_density(transcript, segment["end"] - segment["start"])
        topic_clarity = max([topic["confidence"] for topic in topics], default=0.2)
        hook_cta_signal = compute_hook_cta_signal(transcript, segment["start"])
        transcript_insights = analyze_transcript_segment(
            transcript,
            segment_duration,
            segment["start"],
            speech_density,
            transcript_evidence,
        )
        apply_transcript_sequence_quality(transcript_insights, transcript, previous_transcript)
        if transcript.strip():
            previous_transcript = transcript.strip().lower()
        brand_safety_score = compute_brand_safety_score(transcript_insights)
        visual_evidence = build_visual_evidence(frame, objects, visual_novelty, motion, visual_quality)
        attention = score_attention(
            visual_novelty,
            object_clarity,
            audio_energy,
            speech_density,
            scene_change,
            topic_clarity,
            hook_cta_signal,
            motion=motion,
            visual_quality=visual_quality,
            silence_penalty=transcript_insights["silence_penalty"],
            repetition_penalty=transcript_insights["repetition_penalty"],
            blur_penalty=visual_evidence["blur_penalty"],
        )
        drop_risk = score_drop_risk(attention, transcript_insights, visual_evidence)
        score_reasons = build_score_reasons(
            visual_novelty,
            motion,
            object_clarity,
            audio_energy,
            speech_density,
            topic_clarity,
            hook_cta_signal,
            visual_quality,
            drop_risk,
        )
        ad_matches = score_ad_matches(objects, topics, metadata_text, attention, f"{transcript} {ocr_text}", brand_safety_score, drop_risk)
        ad_fit = max([match["ad_fit_score"] for match in ad_matches], default=0)
        label = attention_label(attention)
        recommendation_context = evaluate_recommendation(
            attention,
            ad_fit,
            drop_risk,
            brand_safety_score,
            transcript_insights,
            visual_evidence,
            objects,
            ad_matches,
        )
        ad_slot_score, ad_slot_reasons = score_ad_slot(
            attention,
            ad_fit,
            drop_risk,
            brand_safety_score,
            recommendation_context["confidence"],
            transcript_insights,
            visual_evidence,
        )
        enriched.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "attention_score": attention,
                "ad_fit_score": ad_fit,
                "drop_risk_score": drop_risk,
                "brand_safety_score": brand_safety_score,
                "label": label,
                "summary": build_segment_summary(attention, objects, topics, audio_energy),
                "transcript": transcript,
                "transcript_insights": transcript_insights,
                "visual_evidence": visual_evidence,
                "audio_evidence": audio_evidence.get(idx, {"available": False}),
                "social_evidence": social_evidence.get(idx, {"available": False}),
                "ocr_evidence": ocr_evidence.get(idx, {"available": False}),
                "detector_provenance": {
                    **OBJECT_DETECTION_RUNTIME,
                    "observations": len(objects),
                    "tracked_instances": len(object_instances),
                },
                "score_reasons": score_reasons,
                "recommendation": build_recommendation(
                    segment["start"],
                    attention,
                    ad_fit,
                    objects,
                    topics,
                    drop_risk,
                    transcript_insights,
                    recommendation_context,
                ),
                "recommendation_tier": recommendation_context["tier"],
                "recommendation_confidence": recommendation_context["confidence"],
                "evidence_mode": recommendation_context["evidence_mode"],
                "strong_signals": recommendation_context["strong_signals"],
                "failed_or_weak_signals": recommendation_context["failed_or_weak_signals"],
                "ad_slot_score": ad_slot_score,
                "ad_slot_reasons": ad_slot_reasons,
                "is_best_ad_slot": False,
                "thumbnail_url": media_url(frame["path"]) if frame else None,
                "objects": objects,
                "detected_text": detected_text,
                "topics": topics,
                "ad_matches": ad_matches,
            }
        )
    candidates = [segment for segment in enriched if segment["ad_fit_score"] > 0]
    if candidates:
        max(candidates, key=lambda item: item["ad_slot_score"])["is_best_ad_slot"] = True
    return enriched


def normalize_transcript_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", "", value.lower())).strip()


def transcript_text_is_near_duplicate(current: str, previous: str) -> bool:
    current_normalized = normalize_transcript_text(current)
    previous_normalized = normalize_transcript_text(previous)
    if not current_normalized or not previous_normalized:
        return False
    if current_normalized == previous_normalized:
        return True
    current_words = current_normalized.split()
    previous_words = previous_normalized.split()
    if len(current_words) < 4 or len(previous_words) < 4:
        return False
    current_set = set(current_words)
    previous_set = set(previous_words)
    overlap = len(current_set.intersection(previous_set)) / max(1, min(len(current_set), len(previous_set)))
    return overlap >= 0.82 and (current_normalized in previous_normalized or previous_normalized in current_normalized)


def transcript_time(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transcript_for_segment(start: float, end: float, transcript_segments: list[dict[str, Any]]) -> str:
    word_chunks = transcript_words_for_segment(start, end, transcript_segments)
    if word_chunks:
        return word_chunks

    chunks: list[str] = []
    seen: set[str] = set()
    for item in transcript_segments:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        item_start = transcript_time(item.get("start"), start)
        item_end = transcript_time(item.get("end"), item_start)
        if item_end < item_start:
            item_start, item_end = item_end, item_start
        overlap = max(0.0, min(end, item_end) - max(start, item_start))
        if overlap <= 0:
            continue
        item_duration = max(0.1, item_end - item_start)
        midpoint = item_start + item_duration / 2
        substantial_overlap = overlap / item_duration >= 0.55
        midpoint_inside = start <= midpoint < end
        if not midpoint_inside and not substantial_overlap:
            continue
        normalized = normalize_transcript_text(text)
        if not normalized or normalized in seen:
            continue
        if any(transcript_text_is_near_duplicate(text, existing) for existing in chunks):
            continue
        seen.add(normalized)
        chunks.append(text)
    return " ".join(chunks)


def transcript_words_for_segment(start: float, end: float, transcript_segments: list[dict[str, Any]]) -> str:
    words: list[dict[str, Any]] = []
    for item in transcript_segments:
        item_words = item.get("words") or []
        if not isinstance(item_words, list):
            continue
        for word in item_words:
            if not isinstance(word, dict):
                continue
            text = str(word.get("word", "")).strip()
            if not text:
                continue
            word_start = transcript_time(word.get("start"), start)
            word_end = transcript_time(word.get("end"), word_start)
            if word_end < word_start:
                word_start, word_end = word_end, word_start
            word_midpoint = word_start + max(0.0, word_end - word_start) / 2
            overlap = max(0.0, min(end, word_end) - max(start, word_start))
            if overlap <= 0 and not (start <= word_midpoint < end):
                continue
            words.append({"word": text, "start": word_start, "end": word_end})

    if not words:
        return ""

    words.sort(key=lambda item: (item["start"], item["end"]))
    output: list[str] = []
    previous = ""
    for item in words:
        text = str(item["word"]).strip()
        normalized = normalize_transcript_text(text)
        if normalized and normalized != previous:
            output.append(text)
            previous = normalized
    return " ".join(output)


def transcript_evidence_for_segment(start: float, end: float, transcript_segments: list[dict[str, Any]]) -> dict[str, Any]:
    overlaps: list[tuple[dict[str, Any], float]] = []
    for item in transcript_segments:
        item_start = transcript_time(item.get("start"), start)
        item_end = transcript_time(item.get("end"), item_start)
        overlap = max(0.0, min(end, item_end) - max(start, item_start))
        if overlap > 0:
            overlaps.append((item, overlap))
    if not overlaps:
        return {"source": "none", "language": None, "language_probability": 0.0, "word_confidence": 0.0}

    weight = sum(item_overlap for _, item_overlap in overlaps)
    def weighted_average(key: str, default: float = 0.0) -> float:
        return sum(float(item.get(key, default) or default) * item_overlap for item, item_overlap in overlaps) / max(weight, 0.001)

    words = []
    for item, _ in overlaps:
        for word in item.get("words") or []:
            if not isinstance(word, dict):
                continue
            word_start = transcript_time(word.get("start"), start)
            word_end = transcript_time(word.get("end"), word_start)
            midpoint = word_start + max(0.0, word_end - word_start) / 2
            if not (start <= midpoint < end):
                continue
            words.append(
                {
                    "word": str(word.get("word", "")).strip(),
                    "start": round(word_start, 3),
                    "end": round(word_end, 3),
                    "confidence": round(float(word.get("probability", 0.0) or 0.0), 4),
                }
            )
    word_confidence = float(np.mean([float(word.get("confidence", 0.0) or 0.0) for word in words])) if words else 0.0
    source = next((str(item.get("source")) for item, _ in overlaps if item.get("source")), "legacy")
    language = next((item.get("language") for item, _ in overlaps if item.get("language")), None)
    segment_text = " ".join(str(item.get("text", "")) for item, _ in overlaps)
    devanagari_characters = len(re.findall(r"[\u0900-\u097f]", segment_text))
    latin_characters = len(re.findall(r"[A-Za-z]", segment_text))
    language_label = language
    language_method = "asr"
    if devanagari_characters and latin_characters:
        language_label = "hi-en"
        language_method = "script_and_asr"
    elif devanagari_characters:
        language_label = "hi"
        language_method = "script"
    elif language == "hi" and latin_characters:
        language_label = "likely Hindi/Hinglish"
        language_method = "asr_with_latin_script"
    return {
        "source": source,
        "language": language_label,
        "language_method": language_method,
        "language_probability": round(weighted_average("language_probability"), 3),
        "word_confidence": round(word_confidence, 3),
        "words": words,
        "avg_logprob": round(weighted_average("avg_logprob"), 3),
        "no_speech_prob": round(weighted_average("no_speech_prob"), 3),
        "compression_ratio": round(weighted_average("compression_ratio"), 3),
        "timestamp_coverage": round(
            min(
                1.0,
                len(words)
                / max(1, len(re.findall(r"\w+", " ".join(str(item.get("text", "")) for item, _ in overlaps)))),
            ),
            3,
        ),
    }


def classify_topics(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    scores = []
    for label, keywords in TOPIC_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if hits:
            scores.append({"label": label, "confidence": min(0.95, 0.45 + hits * 0.15)})
    if not scores:
        scores.append({"label": "entertainment", "confidence": 0.38})
    return sorted(scores, key=lambda item: item["confidence"], reverse=True)[:3]


def compute_visual_novelty(frame: dict[str, Any] | None, previous_frame: dict[str, Any] | None) -> float:
    if not frame:
        return 0.2
    if not previous_frame:
        return 0.55
    brightness_delta = abs(float(frame.get("brightness", 0.5)) - float(previous_frame.get("brightness", 0.5)))
    contrast_delta = abs(float(frame.get("contrast", 0.0)) - float(previous_frame.get("contrast", 0.0)))
    color_delta = abs(float(frame.get("colorfulness", 0.0)) - float(previous_frame.get("colorfulness", 0.0)))
    mean_delta = abs(float(frame.get("mean", 0.0)) - float(previous_frame.get("mean", 0.0))) / 70
    return clamp(mean_delta * 0.35 + brightness_delta * 0.20 + contrast_delta * 0.20 + color_delta * 0.25)


def compute_object_clarity(objects: list[dict[str, Any]], frame: dict[str, Any] | None) -> float:
    if not objects:
        return 0.15
    instances = representative_object_instances(objects)
    confidence = float(np.mean([obj["confidence"] for obj in instances]))
    size_bonus = 0.0
    if frame:
        height, width = frame["shape"][:2]
        frame_area = width * height
        ratios = []
        for obj in instances:
            bbox = obj.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            ratios.append(max(0.0, ((x2 - x1) * (y2 - y1)) / frame_area))
        size_bonus = min(0.25, float(np.mean(ratios)) * 2) if ratios else 0.0
    return clamp(confidence * 0.75 + size_bonus)


def representative_object_instances(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    instances: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(objects):
        track_id = str(item.get("track_id") or "")
        key = track_id or f"{item.get('label', 'object')}:{item.get('instance_index', index)}"
        if key not in instances or float(item.get("confidence", 0.0) or 0.0) > float(
            instances[key].get("confidence", 0.0) or 0.0
        ):
            instances[key] = item
    return list(instances.values())


def compute_speech_density(transcript: str, duration: float) -> float:
    words = len(re.findall(r"\w+", transcript))
    if duration <= 0:
        return 0.0
    wps = words / duration
    if 1.8 <= wps <= 3.0:
        return 1.0
    if wps > 3.5:
        return 0.62
    if wps < 1.0:
        return 0.28
    return 0.75


def compute_hook_cta_signal(transcript: str, start: float) -> float:
    terms = sorted(set(HOOK_TERMS + CTA_TERMS))
    hits = sum(1 for term in terms if term in transcript.lower())
    intro_bonus = 0.25 if start < 10 else 0
    return clamp(intro_bonus + hits * 0.18)


def analyze_transcript_segment(
    transcript: str,
    duration: float,
    start: float,
    speech_density: float,
    asr_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lowered = transcript.lower()
    words = [
        token
        for raw_token in re.findall(r"\S+", lowered, flags=re.UNICODE)
        if (token := raw_token.strip(".,!?;:\"'()[]{}<>…।॥-–—")) and any(character.isalpha() for character in token)
    ]
    filler_terms = ["um", "uh", "like", "basically", "actually", "literally", "मतलब", "यानी", "matlab"]
    filler_count = sum(1 for word in words if word in filler_terms)
    keyword_counts = Counter(word for word in words if len(word) > 3)
    repetition_ratio = max(keyword_counts.values(), default=0) / max(1, len(words))
    hook_terms = [term for term in HOOK_TERMS if term in lowered]
    cta_terms = [term for term in CTA_TERMS if term in lowered]
    claim_terms = [term for term in CLAIM_TERMS if term in lowered]
    risk_flags = {
        label: [term for term in terms if term in lowered]
        for label, terms in RISK_TERMS.items()
        if any(term in lowered for term in terms)
    }
    silence_penalty = 1.0 if not words else 0.0
    if transcript.strip() and duration > 0 and len(words) / duration < 0.8:
        silence_penalty = 0.45
    words_per_second = len(words) / duration if duration > 0 else 0
    quality_flags: list[str] = []
    if not words:
        quality_flags.append("no_speech_detected")
    if words_per_second > 6:
        quality_flags.append("unrealistic_speech_rate")
    elif words_per_second > 4:
        quality_flags.append("fast_speech_rate")
    if repetition_ratio > 0.34 and len(words) >= 6:
        quality_flags.append("repetitive_transcript")
    specificity = clamp(len({word for word in words if len(word) > 4}) / max(1, len(words)))
    clarity_score = int(
        round(
            100
            * clamp(
                speech_density * 0.38
                + specificity * 0.24
                + min(1.0, len(hook_terms) / 2) * 0.14
                + min(1.0, len(cta_terms) / 2) * 0.10
                + (1 - min(1.0, filler_count / max(1, len(words)))) * 0.14
            )
        )
    )
    transcript_confidence = clarity_score
    asr_evidence = asr_evidence or {}
    if asr_evidence.get("source") == "faster_whisper":
        logprob_quality = clamp((float(asr_evidence.get("avg_logprob", -1.2)) + 1.2) / 1.2)
        no_speech_quality = 1 - clamp(float(asr_evidence.get("no_speech_prob", 1.0)))
        compression_ratio = float(asr_evidence.get("compression_ratio", 0.0))
        compression_quality = 1.0 if compression_ratio <= 2.4 else clamp(1 - (compression_ratio - 2.4) / 1.6)
        word_quality = clamp(float(asr_evidence.get("word_confidence", 0.0)))
        transcript_confidence = int(round(
            clamp(
                (transcript_confidence / 100) * 0.45
                + logprob_quality * 0.20
                + no_speech_quality * 0.15
                + compression_quality * 0.10
                + word_quality * 0.10
            ) * 100
        ))
    if not words:
        transcript_confidence = 0
    if "unrealistic_speech_rate" in quality_flags:
        transcript_confidence = min(transcript_confidence, 35)
    elif "fast_speech_rate" in quality_flags:
        transcript_confidence = min(transcript_confidence, 55)
    if "repetitive_transcript" in quality_flags:
        transcript_confidence = min(transcript_confidence, 50)
    return {
        "word_count": len(words),
        "words_per_second": round(words_per_second, 2),
        "clarity_score": clarity_score,
        "transcript_confidence": int(round(transcript_confidence)),
        "transcript_quality_flags": quality_flags,
        "hook_terms": hook_terms[:5],
        "cta_terms": cta_terms[:5],
        "claim_terms": claim_terms[:5],
        "risk_flags": risk_flags,
        "filler_count": filler_count,
        "repetition_penalty": clamp((repetition_ratio - 0.16) / 0.24),
        "silence_penalty": silence_penalty,
        "early_hook": bool(start < 10 and hook_terms),
        "source": asr_evidence.get("source", "legacy"),
        "language": asr_evidence.get("language"),
        "language_method": asr_evidence.get("language_method"),
        "language_probability": asr_evidence.get("language_probability", 0),
        "word_confidence": asr_evidence.get("word_confidence", 0),
        "words": asr_evidence.get("words", []),
        "avg_logprob": asr_evidence.get("avg_logprob"),
        "no_speech_probability": asr_evidence.get("no_speech_prob"),
        "timestamp_coverage": asr_evidence.get("timestamp_coverage", 0),
    }


def apply_transcript_sequence_quality(insights: dict[str, Any], transcript: str, previous_transcript: str) -> None:
    normalized = " ".join(transcript.lower().split())
    if not normalized or not previous_transcript:
        return
    if normalized == previous_transcript and insights.get("word_count", 0) >= 3:
        flags = list(insights.get("transcript_quality_flags", []))
        if "duplicate_nearby_transcript" not in flags:
            flags.append("duplicate_nearby_transcript")
        insights["transcript_quality_flags"] = flags
        insights["transcript_confidence"] = min(int(insights.get("transcript_confidence", 0)), 40)
        insights["repetition_penalty"] = max(float(insights.get("repetition_penalty", 0.0)), 0.75)


def compute_brand_safety_score(transcript_insights: dict[str, Any]) -> int:
    risk_flags = transcript_insights.get("risk_flags", {})
    penalties = {
        "profanity": 18,
        "hate_or_abuse": 30,
        "sexual_content": 25,
        "violence": 22,
        "drug_alcohol": 20,
        "political_sensitive": 15,
    }
    score = 100
    for label in risk_flags:
        score -= penalties.get(label, 12)
    if transcript_insights.get("claim_terms"):
        score -= 12
    return int(round(clamp(score / 100) * 100))


def build_visual_evidence(
    frame: dict[str, Any] | None,
    objects: list[dict[str, Any]],
    visual_novelty: float,
    motion: float,
    visual_quality: float,
) -> dict[str, Any]:
    instances = representative_object_instances(objects)
    object_labels = list(dict.fromkeys(str(obj["label"]) for obj in instances))[:5]
    return {
        "sampled_frames": int(frame.get("sampled_frames", 0)) if frame else 0,
        "frame_width": int(frame["shape"][1]) if frame and frame.get("shape") else None,
        "frame_height": int(frame["shape"][0]) if frame and frame.get("shape") else None,
        "visual_novelty": round(visual_novelty, 3),
        "motion": round(motion, 3),
        "visual_quality": round(visual_quality, 3),
        "brightness": round(float(frame.get("brightness", 0.0)), 3) if frame else 0.0,
        "contrast": round(float(frame.get("contrast", 0.0)), 3) if frame else 0.0,
        "sharpness": round(float(frame.get("sharpness", 0.0)), 3) if frame else 0.0,
        "object_count": len(instances),
        "object_observation_count": len(objects),
        "top_objects": object_labels,
        "detector": OBJECT_DETECTION_RUNTIME.get("active_detector", "unavailable"),
        "detector_degraded": bool(OBJECT_DETECTION_RUNTIME.get("degraded", True)),
        "fallback_reason": OBJECT_DETECTION_RUNTIME.get("fallback_reason"),
        "motion_acceleration": round(float(frame.get("motion_acceleration", 0.0)), 3) if frame else 0.0,
        "camera_movement": round(float(frame.get("camera_movement", 0.0)), 3) if frame else 0.0,
        "pacing_variation": round(float(frame.get("pacing_variation", 0.0)), 3) if frame else 0.0,
        "scene_boundaries": list(frame.get("scene_boundaries", [])) if frame else [],
        "shot_change_count": int(frame.get("shot_change_count", 0)) if frame else 0,
        "scene_detector": frame.get("scene_detector", "unavailable") if frame else "unavailable",
        "saturation": round(float(frame.get("saturation", 0.0)), 3) if frame else 0.0,
        "visual_clutter": round(float(frame.get("clutter", 0.0)), 3) if frame else 0.0,
        "blur_penalty": clamp(1 - visual_quality),
    }


def score_drop_risk(attention: int, transcript_insights: dict[str, Any], visual_evidence: dict[str, Any]) -> int:
    risk = 100 - attention
    risk += 18 * float(transcript_insights.get("silence_penalty", 0.0))
    risk += 14 * float(transcript_insights.get("repetition_penalty", 0.0))
    risk += 12 * float(visual_evidence.get("blur_penalty", 0.0))
    if visual_evidence.get("object_count", 0) == 0:
        risk += 6
    return int(round(clamp(risk / 100) * 100))


def score_ad_slot(
    attention: int,
    ad_fit: int,
    drop_risk: int,
    brand_safety: int,
    recommendation_confidence: int,
    transcript_insights: dict[str, Any],
    visual_evidence: dict[str, Any],
) -> tuple[int, list[str]]:
    natural_boundary = 0.55
    if transcript_insights.get("word_count", 0) == 0:
        natural_boundary = 0.7 if visual_evidence.get("motion", 0) < 0.45 else 0.45
    elif transcript_insights.get("silence_penalty", 0) > 0:
        natural_boundary = 0.8
    elif transcript_insights.get("words_per_second", 0) <= 2.2:
        natural_boundary = 0.7
    context_score = clamp(ad_fit / 100)
    score = (
        clamp(attention / 100) * 0.25
        + context_score * 0.25
        + clamp(1 - drop_risk / 100) * 0.15
        + clamp(brand_safety / 100) * 0.15
        + natural_boundary * 0.10
        + clamp(recommendation_confidence / 100) * 0.10
    )
    reasons = [
        f"attention quality: {attention}",
        f"contextual ad fit: {ad_fit}",
        f"low drop risk: {100 - drop_risk}",
        f"brand safety: {brand_safety}",
        f"natural boundary: {round(natural_boundary * 100)}",
        f"evidence confidence: {recommendation_confidence}",
    ]
    return int(round(clamp(score) * 100)), reasons


def build_score_reasons(
    visual_novelty: float,
    motion: float,
    object_clarity: float,
    audio_energy: float,
    speech_density: float,
    topic_clarity: float,
    hook_cta_signal: float,
    visual_quality: float,
    drop_risk: int,
) -> list[str]:
    signals = [
        ("visual novelty", visual_novelty),
        ("motion change", motion),
        ("object clarity", object_clarity),
        ("audio energy", audio_energy),
        ("speech pacing", speech_density),
        ("topic clarity", topic_clarity),
        ("hook/CTA signal", hook_cta_signal),
        ("visual quality", visual_quality),
    ]
    reasons = [f"{label}: {round(value * 100)}" for label, value in sorted(signals, key=lambda item: item[1], reverse=True)[:4]]
    reasons.append(f"drop risk: {drop_risk}")
    return reasons


def evaluate_recommendation(
    attention: int,
    ad_fit: int,
    drop_risk: int,
    brand_safety: int,
    transcript_insights: dict[str, Any],
    visual_evidence: dict[str, Any],
    objects: list[dict[str, Any]],
    ad_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    transcript_confidence = int(transcript_insights.get("transcript_confidence", transcript_insights.get("clarity_score", 0)) or 0)
    visual_quality = int(round(float(visual_evidence.get("visual_quality", 0.0)) * 100))
    motion = int(round(float(visual_evidence.get("motion", 0.0)) * 100))
    object_count = int(visual_evidence.get("object_count", 0) or 0)
    object_labels = {obj["label"].lower() for obj in objects}
    has_person = "person" in object_labels
    product_objects = sorted(object_labels.intersection(PRODUCT_CONTEXT_OBJECTS))
    top_match_confidence = max([int(match.get("confidence", 0) or 0) for match in ad_matches], default=0)
    transcript_missing = int(transcript_insights.get("word_count", 0) or 0) == 0

    strong_signals: list[str] = []
    weak_signals: list[str] = []
    if attention >= 70:
        strong_signals.append(f"strong attention {attention}")
    elif attention < 40:
        weak_signals.append(f"low attention {attention}")
    if ad_fit >= 60 and top_match_confidence >= 65:
        strong_signals.append(f"category evidence {ad_fit}")
    elif ad_fit < 35:
        weak_signals.append("weak category match")
    if brand_safety >= 85:
        strong_signals.append(f"brand safe {brand_safety}")
    elif brand_safety < 70:
        weak_signals.append(f"brand-safety review {brand_safety}")
    if drop_risk <= 35:
        strong_signals.append(f"low drop risk {drop_risk}")
    elif drop_risk >= 65:
        weak_signals.append(f"high drop risk {drop_risk}")
    if transcript_confidence >= 70:
        strong_signals.append(f"clear transcript {transcript_confidence}")
    elif transcript_missing:
        weak_signals.append("transcript unavailable")
    elif transcript_confidence < 50:
        weak_signals.append(f"low transcript confidence {transcript_confidence}")
    if product_objects:
        strong_signals.append(f"product/context objects: {', '.join(product_objects[:3])}")
    elif has_person:
        strong_signals.append("person/context detected")
        weak_signals.append("person is generic product evidence")
    if visual_quality >= 65:
        strong_signals.append(f"visual quality {visual_quality}")
    elif visual_quality < 35:
        weak_signals.append(f"weak visual quality {visual_quality}")
    if motion >= 25:
        strong_signals.append(f"motion/context change {motion}")
    if object_count == 0:
        weak_signals.append("no strong object detections")

    visual_context = clamp((visual_quality / 100) * 0.42 + (motion / 100) * 0.18 + min(1.0, object_count / 3) * 0.24 + (0.16 if has_person else 0.0))
    transcript_weight = 0.12 if transcript_missing else 0.27
    visual_weight = 0.25 if transcript_missing else 0.17
    object_weight = 0.17 if transcript_missing else 0.12
    confidence = int(
        round(
            clamp(
                attention / 100 * 0.18
                + ad_fit / 100 * 0.20
                + (1 - drop_risk / 100) * 0.14
                + brand_safety / 100 * 0.14
                + transcript_confidence / 100 * transcript_weight
                + visual_context * visual_weight
                + min(1.0, object_count / 3) * object_weight
            )
            * 100
        )
    )

    has_context_source = bool(product_objects or transcript_confidence >= 55 or visual_context >= 0.58 or (has_person and visual_context >= 0.46))
    has_category_evidence = bool(ad_fit >= 60 and top_match_confidence >= 65 and (product_objects or transcript_confidence >= 55))
    if brand_safety < 50 or drop_risk >= 82 or attention < 20:
        tier = "Avoid"
    elif confidence >= 72 and attention >= 55 and drop_risk <= 50 and brand_safety >= 80 and has_category_evidence and has_context_source:
        tier = "Strong ad slot"
    elif confidence >= 54 and attention >= 38 and drop_risk <= 72 and brand_safety >= 68 and has_context_source:
        tier = "Conditional ad slot"
    elif confidence >= 38 or attention >= 35 or visual_context >= 0.42:
        tier = "Edit before monetization"
    else:
        tier = "Avoid"

    if transcript_missing and object_count > 0:
        evidence_mode = "visual_only"
    elif transcript_missing:
        evidence_mode = "weak_evidence"
    elif visual_evidence.get("sampled_frames", 0) and transcript_confidence > 0:
        evidence_mode = "transcript_visual"
    else:
        evidence_mode = "audio_visual"

    return {
        "tier": tier,
        "confidence": confidence,
        "evidence_mode": evidence_mode,
        "strong_signals": strong_signals[:8],
        "failed_or_weak_signals": weak_signals[:8],
    }


def active_scoring_settings() -> dict[str, Any]:
    """Read the immutable configuration currently marked active by release governance.

    The fallback preserves the existing production formula during local imports,
    tests, and before the control-plane migrations have run.
    """
    try:
        row = query_one("select config_json from ml_scoring_config_versions where status = 'active' order by version desc limit 1")
        if row and row["config_json"]:
            payload = json.loads(row["config_json"])
            if isinstance(payload, dict):
                return payload
    except (sqlite3.OperationalError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def score_attention(
    visual_novelty: float,
    object_clarity: float,
    audio_energy: float,
    speech_density: float,
    scene_change: float,
    topic_clarity: float,
    hook_cta_signal: float,
    motion: float = 0.0,
    visual_quality: float = 0.5,
    silence_penalty: float = 0.0,
    repetition_penalty: float = 0.0,
    blur_penalty: float = 0.0,
) -> int:
    settings = active_scoring_settings()
    weights = settings.get("weights", {})
    penalties = settings.get("penalties", {})
    value = (
        visual_novelty * float(weights.get("visual_novelty", 0.16))
        + motion * float(weights.get("motion", 0.12))
        + object_clarity * float(weights.get("object_clarity", 0.12))
        + visual_quality * float(weights.get("visual_quality", 0.10))
        + scene_change * float(weights.get("scene_change", 0.10))
        + speech_density * float(weights.get("speech_density", 0.12))
        + hook_cta_signal * float(weights.get("hook_cta_signal", 0.10))
        + audio_energy * float(weights.get("audio_energy", 0.08))
        + topic_clarity * float(weights.get("topic_clarity", 0.10))
    )
    penalty = (
        silence_penalty * float(penalties.get("silence", 0.12))
        + repetition_penalty * float(penalties.get("repetition", 0.08))
        + blur_penalty * float(penalties.get("blur", 0.08))
    )
    return int(round(clamp(value - penalty) * 100))


def score_ad_matches(
    objects: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    metadata_text: str,
    attention_score: int,
    transcript: str = "",
    brand_safety_score: int = 100,
    drop_risk_score: int = 0,
) -> list[dict[str, Any]]:
    object_labels = {obj["label"].lower() for obj in objects}
    product_object_labels = object_labels.difference(GENERIC_CONTEXT_OBJECTS)
    topic_labels = {topic["label"].lower() for topic in topics}
    context_text = " ".join([metadata_text, transcript, " ".join(topic_labels)]).lower()
    matches = []
    for item in AD_CATALOG:
        catalog_objects = {label.lower() for label in item["objects"]}
        object_hits = sorted(object_labels.intersection(catalog_objects))
        product_object_hits = sorted(product_object_labels.intersection(catalog_objects))
        generic_object_hits = sorted(set(object_hits).difference(product_object_hits))
        object_match = (len(product_object_hits) + len(generic_object_hits) * 0.35) / max(1, min(3, len(catalog_objects)))
        keyword_hits = [keyword for keyword in item["keywords"] if keyword in context_text]
        transcript_match = min(1.0, len(keyword_hits) / max(1, min(4, len(item["keywords"]))))
        audience_terms = AD_AUDIENCE_TERMS.get(item["category"], item.get("audience", []))
        audience_hits = [term for term in audience_terms if term in context_text]
        audience_match = min(1.0, len(audience_hits) / max(1, min(3, len(audience_terms))))
        topic_match = min(1.0, len(topic_labels.intersection(set(item["keywords"]))) / max(1, min(3, len(item["keywords"]))))
        evidence_units = (
            len(product_object_hits) * 1.0
            + len(generic_object_hits) * 0.25
            + len(keyword_hits) * 0.6
            + len(audience_hits) * 0.4
            + topic_match
        )
        attention_quality = clamp(attention_score / 100)
        slot_quality = clamp(1 - drop_risk_score / 100)
        safety_gate = clamp(brand_safety_score / 100)
        score = (
            transcript_match * 0.25
            + object_match * 0.20
            + topic_match * 0.15
            + audience_match * 0.10
            + attention_quality * 0.12
            + slot_quality * 0.10
            + safety_gate * 0.08
        ) * safety_gate
        if evidence_units <= 0:
            continue
        if len(keyword_hits) == 1 and not product_object_hits and not audience_hits and topic_match == 0:
            score *= 0.45
        if not product_object_hits and generic_object_hits == ["person"] and len(keyword_hits) < 2:
            score *= 0.55
        if score > 0.22 and evidence_units >= 0.75:
            reason_bits = []
            if product_object_hits:
                reason_bits.append(f"product/visual evidence: {', '.join(product_object_hits[:3])}")
            elif generic_object_hits:
                reason_bits.append(f"context evidence: {', '.join(generic_object_hits[:3])}")
            if keyword_hits:
                reason_bits.append(f"transcript/context: {', '.join(keyword_hits[:3])}")
            if audience_hits:
                reason_bits.append(f"audience cue: {', '.join(audience_hits[:2])}")
            if attention_score >= 70:
                reason_bits.append(f"strong attention {attention_score}")
            if brand_safety_score < 70:
                reason_bits.append(f"brand-safety review needed {brand_safety_score}")
            matches.append(
                {
                    "category": item["category"],
                    "ad_fit_score": int(round(clamp(score) * 100)),
                    "reason": "; ".join(reason_bits),
                    "confidence": int(round(min(0.95, 0.38 + score * 0.48 + min(evidence_units, 3) * 0.06) * 100)),
                }
            )
    return sorted(matches, key=lambda match: match["ad_fit_score"], reverse=True)[:3]


def attention_label(score: int) -> str:
    thresholds = active_scoring_settings().get("thresholds", {})
    if score >= int(thresholds.get("high_attention", 80)):
        return "High attention"
    if score >= int(thresholds.get("good_attention", 60)):
        return "Good attention"
    if score >= int(thresholds.get("neutral", 40)):
        return "Neutral"
    if score >= int(thresholds.get("drop_risk", 20)):
        return "Drop risk"
    return "Weak moment"


def build_segment_summary(
    attention: int, objects: list[dict[str, Any]], topics: list[dict[str, Any]], audio_energy: float
) -> str:
    object_text = ", ".join(obj["label"] for obj in objects[:2]) or "few clear objects"
    topic_text = ", ".join(topic["label"] for topic in topics[:2]) or "general context"
    audio_text = "active audio" if audio_energy > 0.55 else "lower audio energy"
    return f"{attention_label(attention)} with {object_text}, {topic_text}, and {audio_text}."


def build_recommendation(
    start: float,
    attention: int,
    ad_fit: int,
    objects: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    drop_risk: int = 0,
    transcript_insights: dict[str, Any] | None = None,
    recommendation_context: dict[str, Any] | None = None,
) -> str:
    timestamp = format_time(start)
    transcript_insights = transcript_insights or {}
    recommendation_context = recommendation_context or {}
    tier = recommendation_context.get("tier")
    confidence = recommendation_context.get("confidence", 0)
    weak_signals = recommendation_context.get("failed_or_weak_signals", [])
    if tier == "Strong ad slot":
        category_hint = topics[0]["label"] if topics else "context"
        return f"{timestamp} is a strong ad slot for {category_hint}; confidence {confidence} with aligned attention, safety, and context evidence."
    if tier == "Conditional ad slot":
        if transcript_insights.get("word_count", 0) == 0:
            return f"{timestamp} is a conditional slot; transcript unavailable, so the recommendation is based on visual, object, person, audio, and safety signals."
        caveat = f" Caveat: {weak_signals[0]}." if weak_signals else ""
        return f"{timestamp} is a conditional ad slot; review the evidence before monetization.{caveat}"
    if tier == "Edit before monetization":
        return f"{timestamp} is the best available content-context window, but editing is recommended before monetization."
    if tier == "Avoid":
        return f"{timestamp} should be avoided for ad placement because the available evidence is weak or risky."
    if transcript_insights.get("risk_flags") or transcript_insights.get("claim_terms"):
        return f"{timestamp} needs brand-safety review before sponsorship; transcript flags include claims or sensitive wording."
    if ad_fit >= 75:
        category_hint = topics[0]["label"] if topics else "context"
        return f"{timestamp} is a strong contextual ad moment because the scene and {category_hint} topic align."
    if attention < 40 or drop_risk >= 65:
        return f"{timestamp} may be a cut or rewrite zone; add clearer visual change, a stronger spoken promise, or a product cue."
    if transcript_insights.get("word_count", 0) == 0:
        return f"{timestamp} has little speech evidence; add a clear spoken cue or on-screen product context before placing a brand message."
    if objects:
        return f"{timestamp} is worth keeping; visible {objects[0]['label']} context helps viewers understand the moment."
    return f"{timestamp} is steady but could use a clearer object, example, or CTA to improve monetization fit."


def write_analysis(
    video_id: str, segments: list[dict[str, Any]], analysis_run_id: str | None = None
) -> None:
    signal_payload = build_signal_payload(segments)
    track_records: dict[str, dict[str, Any]] = {}
    with connect() as conn:
        for table in ("detected_objects", "detected_text", "topics", "ad_matches"):
            conn.execute(f"delete from {table} where segment_id in (select id from segments where video_id = ?)", (video_id,))
        previous_segment_ids = [
            row["id"] for row in conn.execute("select id from segments where video_id = ?", (video_id,)).fetchall()
        ]
        for previous_segment_id in previous_segment_ids:
            conn.execute("delete from detected_objects where segment_id = ?", (previous_segment_id,))
            conn.execute("delete from topics where segment_id = ?", (previous_segment_id,))
            conn.execute("delete from ad_matches where segment_id = ?", (previous_segment_id,))
        conn.execute("delete from segments where video_id = ?", (video_id,))
        for segment in segments:
            segment_id = new_id("seg")
            segment["id"] = segment_id
            conn.execute(
                """
                insert into segments
                (id, video_id, start_time, end_time, attention_score, ad_fit_score, drop_risk_score, brand_safety_score, label, summary, transcript, transcript_insights, visual_evidence, score_reasons, recommendation, recommendation_tier, recommendation_confidence, evidence_mode, strong_signals, failed_or_weak_signals, ad_slot_score, ad_slot_reasons, is_best_ad_slot, thumbnail_url, detector_provenance, audio_evidence, narrative_evidence, social_evidence, ocr_evidence, signal_summary, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    video_id,
                    segment["start"],
                    segment["end"],
                    segment["attention_score"],
                    segment["ad_fit_score"],
                    segment.get("drop_risk_score", max(0, 100 - int(segment["attention_score"]))),
                    segment.get("brand_safety_score", 100),
                    segment["label"],
                    segment["summary"],
                    segment["transcript"],
                    json.dumps(segment.get("transcript_insights", {})),
                    json.dumps(segment.get("visual_evidence", {})),
                    json.dumps(segment.get("score_reasons", [])),
                    segment["recommendation"],
                    segment.get("recommendation_tier", "Edit before monetization"),
                    segment.get("recommendation_confidence", 0),
                    segment.get("evidence_mode", "weak_evidence"),
                    json.dumps(segment.get("strong_signals", [])),
                    json.dumps(segment.get("failed_or_weak_signals", [])),
                    segment.get("ad_slot_score", 0),
                    json.dumps(segment.get("ad_slot_reasons", [])),
                    1 if segment.get("is_best_ad_slot") else 0,
                    segment["thumbnail_url"],
                    json.dumps(segment.get("detector_provenance", {})),
                    json.dumps(segment.get("audio_evidence", {})),
                    json.dumps(segment.get("narrative_evidence", {})),
                    json.dumps(segment.get("social_evidence", {})),
                    json.dumps(segment.get("ocr_evidence", {})),
                    json.dumps(segment.get("signal_summary", {})),
                    utc_now(),
                ),
            )
            for obj in segment["objects"]:
                conn.execute(
                    """
                    insert into detected_objects
                    (id, segment_id, label, confidence, bbox, frame_timestamp, track_id, detector, instance_index, mask, evidence_kind, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("obj"),
                        segment_id,
                        obj["label"],
                        obj["confidence"],
                        json.dumps(obj.get("bbox")),
                        obj.get("frame_timestamp"),
                        obj.get("track_id"),
                        obj.get("detector"),
                        obj.get("instance_index", 0),
                        json.dumps(obj.get("mask")) if obj.get("mask") is not None else None,
                        obj.get("evidence_kind", "object"),
                        utc_now(),
                    ),
                )
                track_id = str(obj.get("track_id") or "")
                if analysis_run_id and track_id:
                    timestamp = float(obj.get("frame_timestamp", segment["start"]) or segment["start"])
                    record = track_records.setdefault(
                        track_id,
                        {
                            "label": str(obj.get("label", "object")),
                            "confidence": [],
                            "first_seen": timestamp,
                            "last_seen": timestamp,
                            "detector": str(obj.get("detector") or "unavailable"),
                            "observations": [],
                        },
                    )
                    record["confidence"].append(float(obj.get("confidence", 0.0) or 0.0))
                    record["first_seen"] = min(float(record["first_seen"]), timestamp)
                    record["last_seen"] = max(float(record["last_seen"]), timestamp)
                    record["observations"].append(
                        {
                            "segment_id": segment_id,
                            "timestamp": timestamp,
                            "bbox": obj.get("bbox"),
                            "confidence": obj.get("confidence"),
                        }
                    )
            for text in segment.get("detected_text", []):
                conn.execute(
                    """insert into detected_text (id, segment_id, text, confidence, bbox, frame_timestamp, created_at)
                       values (?, ?, ?, ?, ?, ?, ?)""",
                    (new_id("ocr"), segment_id, text["text"], text["confidence"], json.dumps(text.get("bbox")), text.get("frame_timestamp"), utc_now()),
                )
            for topic in segment["topics"]:
                conn.execute(
                    "insert into topics (id, segment_id, label, confidence, created_at) values (?, ?, ?, ?, ?)",
                    (new_id("topic"), segment_id, topic["label"], topic["confidence"], utc_now()),
                )
            for match in segment["ad_matches"]:
                conn.execute(
                    """
                    insert into ad_matches
                    (id, segment_id, ad_category, ad_fit_score, reason, confidence, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("ad"),
                        segment_id,
                        match["category"],
                        match["ad_fit_score"],
                        match["reason"],
                        match["confidence"],
                        utc_now(),
                    ),
                )
            if analysis_run_id:
                for family in ("visual", "audio", "narrative", "social"):
                    family_summary = segment.get("signal_summary", {}).get(family, {})
                    conn.execute(
                        """
                        insert into segment_signals
                        (id, analysis_run_id, segment_id, family, summary, confidence, created_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("signal"),
                            analysis_run_id,
                            segment_id,
                            family,
                            json.dumps(family_summary),
                            float(family_summary.get("confidence", 0.0) or 0.0),
                            utc_now(),
                        ),
                    )
                    for signal_name, value in family_summary.items():
                        if signal_name == "confidence" or not isinstance(value, (int, float)) or isinstance(value, bool):
                            continue
                        conn.execute(
                            """
                            insert into signal_samples
                            (id, analysis_run_id, segment_id, family, signal_name, timestamp, value, confidence, metadata, created_at)
                            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_id("sample"),
                                analysis_run_id,
                                segment_id,
                                family,
                                signal_name,
                                segment["start"],
                                float(value),
                                float(family_summary.get("confidence", 0.0) or 0.0),
                                json.dumps({"end_time": segment["end"]}),
                                utc_now(),
                            ),
                        )
                evidence_payloads = [
                    ("frame", segment.get("thumbnail_url"), {"objects": segment.get("objects", [])}, None),
                    ("transcript", None, {"text": segment.get("transcript", ""), "insights": segment.get("transcript_insights", {})}, segment.get("transcript_insights", {}).get("transcript_confidence", 0) / 100),
                    ("audio", None, segment.get("audio_evidence", {}), segment.get("audio_evidence", {}).get("confidence")),
                    ("ocr", None, segment.get("ocr_evidence", {}), segment.get("ocr_evidence", {}).get("confidence")),
                    ("face_behavior", None, segment.get("social_evidence", {}), segment.get("social_evidence", {}).get("confidence")),
                    ("scene", None, {"boundaries": segment.get("visual_evidence", {}).get("scene_boundaries", [])}, None),
                ]
                for artifact_type, uri, artifact_payload, artifact_confidence in evidence_payloads:
                    conn.execute(
                        """
                        insert into evidence_artifacts
                        (id, analysis_run_id, segment_id, artifact_type, timestamp, uri, payload, confidence, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("evidence"), analysis_run_id, segment_id, artifact_type, segment["start"], uri,
                            json.dumps(artifact_payload), artifact_confidence, utc_now(),
                        ),
                    )
        if analysis_run_id:
            for track_id, record in track_records.items():
                conn.execute(
                    """
                    insert into object_tracks
                    (id, analysis_run_id, video_id, track_id, label, confidence, first_seen, last_seen, detector, observations, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("track"),
                        analysis_run_id,
                        video_id,
                        track_id,
                        record["label"],
                        float(np.mean(record["confidence"])) if record["confidence"] else 0.0,
                        record["first_seen"],
                        record["last_seen"],
                        record["detector"],
                        json.dumps(record["observations"]),
                        utc_now(),
                    ),
                )
            for metric in signal_payload.get("decision_metrics", []):
                timestamp = metric.get("timestamp", {})
                conn.execute(
                    """
                    insert into decision_metrics
                    (id, analysis_run_id, metric_key, label, internal_score, confidence, start_time, end_time, reasons, next_action, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("decision"),
                        analysis_run_id,
                        metric.get("key"),
                        metric.get("label"),
                        metric.get("score"),
                        metric.get("confidence_score", 0),
                        timestamp.get("start"),
                        timestamp.get("end"),
                        json.dumps(metric.get("reasons", [])),
                        metric.get("next_action"),
                        utc_now(),
                    ),
                )
            active_detector = str(OBJECT_DETECTION_RUNTIME.get("active_detector") or "unavailable")
            detector_model_path = (
                YOLOE_MODEL_PATH
                if active_detector == "yoloe_gpu"
                else YOLO_MODEL_PATH
                if active_detector in {"yolo_local", "yolo26_cpu"}
                else None
            )
            detector_checksum = (
                source_sha256(detector_model_path)
                if detector_model_path is not None and detector_model_path.is_file()
                else None
            )
            face_model_checksum = source_sha256(MEDIAPIPE_FACE_MODEL) if MEDIAPIPE_FACE_MODEL.is_file() else None
            manifests = [
                {
                    "extractor": "object_detection",
                    "library_version": installed_package_version("ultralytics"),
                    "model_version": str(detector_model_path.name) if detector_model_path is not None else active_detector,
                    "weight_checksum": detector_checksum,
                    "configuration": {
                        "detector": OBJECT_DETECTION_RUNTIME,
                        "confidence": YOLO_CONFIDENCE,
                        "image_size": YOLO_IMAGE_SIZE,
                    },
                },
                {
                    "extractor": "transcription",
                    "library_version": installed_package_version("faster-whisper"),
                    "model_version": os.getenv("WHISPER_MODEL", "small"),
                    "weight_checksum": None,
                    "configuration": {
                        "device": os.getenv("WHISPER_DEVICE", "cpu"),
                        "compute_type": os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
                    },
                },
                {
                    "extractor": "ocr",
                    "library_version": installed_package_version("paddleocr"),
                    "model_version": "PP-OCRv5 multilingual",
                    "weight_checksum": None,
                    "configuration": {
                        "languages": os.getenv("NEUROAD_OCR_LANGUAGES", "en,devanagari").split(","),
                        "confidence": float_from_env("NEUROAD_OCR_CONFIDENCE", 0.5),
                    },
                },
                {
                    "extractor": "face_behavior",
                    "library_version": installed_package_version("mediapipe"),
                    "model_version": MEDIAPIPE_FACE_MODEL.name,
                    "weight_checksum": face_model_checksum,
                    "configuration": {
                        "video_mode": True,
                        "identity_or_emotion_inference": False,
                    },
                },
                {
                    "extractor": "audio_features",
                    "library_version": installed_package_version("librosa"),
                    "model_version": "librosa-silero-v1",
                    "weight_checksum": None,
                    "configuration": {
                        "silero_vad": env_enabled("NEUROAD_ENABLE_SILERO_VAD", True),
                        "feature_hop_ms": 20,
                    },
                },
                {
                    "extractor": "semantic_embeddings",
                    "library_version": installed_package_version("sentence-transformers"),
                    "model_version": os.getenv(
                        "NEUROAD_SENTENCE_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
                    ),
                    "weight_checksum": None,
                    "configuration": {
                        "gliner_model": os.getenv("NEUROAD_GLINER_MODEL", "urchade/gliner_multi-v2.1"),
                        "gliner_version": installed_package_version("gliner"),
                    },
                },
                {
                    "extractor": "visual_signals",
                    "library_version": installed_package_version("opencv-python-headless"),
                    "model_version": "shared_decode_v1",
                    "weight_checksum": None,
                    "configuration": {
                        "sample_rate": FRAME_SAMPLE_RATE,
                        "hook_sample_rate": 8.0,
                        "scene_detector": "PySceneDetect AdaptiveDetector + ThresholdDetector",
                        "scenedetect_version": installed_package_version("scenedetect"),
                    },
                },
            ]
            for manifest in manifests:
                conn.execute(
                    """
                    insert into model_manifests
                    (id, analysis_run_id, extractor, library_version, model_version, weight_checksum, configuration, calibration_version, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("manifest"),
                        analysis_run_id,
                        manifest["extractor"],
                        manifest["library_version"],
                        manifest["model_version"],
                        manifest["weight_checksum"],
                        json.dumps(manifest["configuration"]),
                        ANALYSIS_SCHEMA_VERSION,
                        utc_now(),
                    ),
                )
        conn.commit()


def installed_package_version(name: str) -> str | None:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return None


def fit_text_hits(terms: list[str], text: str) -> list[str]:
    normalized = normalize_product_term(text)
    hits = []
    for term in terms:
        value = normalize_product_term(term)
        if len(value) < 3:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", normalized):
            hits.append(term)
    return hits


def prepare_product_segment_context(segment: dict[str, Any]) -> dict[str, Any]:
    transcript = str(segment.get("transcript", ""))
    ocr_text = " ".join(str(item.get("text", "")) for item in segment.get("detected_text", []))
    topics = [normalize_product_term(str(topic.get("label", ""))) for topic in segment.get("topics", [])]
    objects = [normalize_product_term(str(obj.get("label", ""))) for obj in segment.get("objects", [])]
    useful_objects = sorted({label for label in objects if label and label not in PRODUCT_GENERIC_TERMS})
    return {
        "transcript": normalize_product_term(f"{transcript} {ocr_text}"),
        "topic_text": " ".join(topics),
        "object_text": " ".join(useful_objects),
        "topics": [topic for topic in topics if topic],
        "objects": useful_objects,
        "context_text": normalize_product_term(" ".join([
            transcript, ocr_text, str(segment.get("summary", "")), str(segment.get("label", "")), " ".join(topics), " ".join(useful_objects)
        ])),
    }


def score_product_segment_fit(
    product: dict[str, Any], segment: dict[str, Any], prepared_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    terms = product_terms(product)
    context = prepared_context or prepare_product_segment_context(segment)
    context_text = context["context_text"]
    name_hits = fit_text_hits(terms["names"], context_text)
    category_hits = fit_text_hits(terms["categories"], context_text)
    feature_hits = fit_text_hits(terms["features"], context_text)
    use_case_hits = fit_text_hits(terms["use_cases"], context_text)
    audience_hits = fit_text_hits(terms["audience"], context_text)
    prohibited_hits = fit_text_hits(terms["prohibited"], context_text)
    relevant_terms = terms["names"] + terms["categories"] + terms["features"] + terms["use_cases"]
    product_tokens = {
        token for term in relevant_terms for token in normalize_product_term(term).split()
        if len(token) >= 3 and token not in PRODUCT_GENERIC_TERMS
    }
    visual_hits = sorted({label for label in context["objects"] if label in product_tokens})
    transcript_hits = {
        group: fit_text_hits(terms[group], context["transcript"])
        for group in ("names", "categories", "features", "use_cases", "audience")
    }
    topic_hits = sorted(set(
        fit_text_hits(terms["categories"] + terms["features"] + terms["use_cases"], context["topic_text"])
    ))
    transcript_confidence = int(segment.get("transcript_insights", {}).get("transcript_confidence", 0) or 0)
    visual_quality = float(segment.get("visual_evidence", {}).get("visual_quality", 0) or 0)
    brand_category = min(100, len(name_hits) * 70 + len(category_hits) * 45)
    feature_use_case = min(100, len(feature_hits) * 26 + len(use_case_hits) * 38)
    audience_alignment = min(100, len(audience_hits) * 50)
    visual_evidence = min(100, len(visual_hits) * 60)
    transcript_match_count = sum(len(values) for values in transcript_hits.values())
    transcript_evidence = min(100, transcript_match_count * 28)
    topic_evidence = min(100, len(topic_hits) * 45)
    score = (
        brand_category * 0.34
        + feature_use_case * 0.26
        + audience_alignment * 0.12
        + visual_evidence * 0.12
        + transcript_evidence * 0.10
        + topic_evidence * 0.06
    ) / 100
    if prohibited_hits:
        score *= 0.35
    modalities = sum(bool(value) for value in (transcript_match_count, topic_hits, visual_hits))
    high_specificity = bool(name_hits or category_hits or len(feature_hits) >= 2)
    if not high_specificity and modalities < 2:
        score = min(score, 0.44)
    fit_score = int(round(clamp(score) * 100))
    evidence_units = len(name_hits) + len(category_hits) + len(feature_hits) + len(use_case_hits) + len(audience_hits) + len(visual_hits)
    input_groups = sum(bool(terms[group]) for group in ("names", "categories", "features", "use_cases", "audience"))
    input_quality = input_groups / 5
    evidence_quality = clamp(transcript_confidence / 100 * 0.65 + visual_quality * 0.35)
    coverage = clamp((modalities / 3) * 0.55 + min(1, evidence_units / 4) * 0.45)
    confidence = int(round(clamp(input_quality * 0.25 + evidence_quality * 0.35 + coverage * 0.40) * 100))
    if evidence_units == 0 and not topic_hits:
        confidence = min(confidence, 30)
    reasons = []
    if name_hits:
        reasons.append(f"brand or product match: {', '.join(name_hits[:2])}")
    if category_hits:
        reasons.append(f"category alignment: {', '.join(category_hits[:2])}")
    if feature_hits or use_case_hits:
        reasons.append(f"feature or use-case alignment: {', '.join((feature_hits + use_case_hits)[:3])}")
    if audience_hits:
        reasons.append(f"audience cue: {', '.join(audience_hits[:2])}")
    if visual_hits:
        reasons.append(f"visual product cue: {', '.join(visual_hits[:3])}")
    if prohibited_hits:
        reasons.append(f"blocked context detected: {', '.join(prohibited_hits[:2])}")
    if not reasons:
        reasons.append("No direct product, category, audience, or visual cue was detected in this segment.")
    limitations = []
    if not transcript_match_count:
        limitations.append("No product-specific transcript evidence was found.")
    if not visual_hits:
        limitations.append("No product-specific visual object was detected.")
    if transcript_confidence < 45:
        limitations.append("Transcript confidence is low, so spoken-context matches may be incomplete.")
    if not terms["audience"]:
        limitations.append("No target audience was provided in the reviewed product profile.")
    conflicting = [f"Prohibited context: {value}" for value in prohibited_hits]
    if float(segment.get("drop_risk_score", 100) or 100) >= 75:
        conflicting.append(f"High viewer drop risk: {int(float(segment.get('drop_risk_score', 100) or 100))}")
    return {
        "fit_score": fit_score,
        "product_relevance_score": fit_score,
        "confidence": confidence,
        "reasons": reasons,
        "positive_evidence": reasons if not prohibited_hits else [reason for reason in reasons if not reason.startswith("blocked")],
        "conflicting_evidence": conflicting,
        "limitations": limitations,
        "blocked": bool(prohibited_hits),
        "evidence_units": evidence_units,
        "evidence_coverage": {
            "transcript_matches": transcript_match_count,
            "topic_matches": len(topic_hits),
            "visual_matches": len(visual_hits),
            "modalities": modalities,
        },
        "component_breakdown": {
            "brand_category_relevance": brand_category,
            "feature_use_case_alignment": feature_use_case,
            "audience_alignment": audience_alignment,
            "visual_evidence": visual_evidence,
            "transcript_evidence": transcript_evidence,
            "topic_evidence": topic_evidence,
            "brand_safety": int(float(segment.get("brand_safety_score", 100) or 100)),
        },
        "matched_terms": {
            "names": name_hits,
            "categories": category_hits,
            "features": feature_hits,
            "use_cases": use_case_hits,
            "audience": audience_hits,
            "prohibited": prohibited_hits,
        },
        "relevant_topics": topic_hits,
        "relevant_objects": visual_hits,
    }


def natural_boundary_score(segment: dict[str, Any]) -> float:
    natural_boundary = 0.55
    transcript = segment.get("transcript_insights", {})
    if transcript.get("word_count", 0) == 0 or transcript.get("silence_penalty", 0) > 0:
        natural_boundary = 0.8
    elif transcript.get("words_per_second", 0) <= 2.2:
        natural_boundary = 0.7
    return natural_boundary


def placement_readiness_breakdown(segment: dict[str, Any], fit: dict[str, Any]) -> dict[str, int]:
    boundary = natural_boundary_score(segment)
    transcript_confidence = int(segment.get("transcript_insights", {}).get("transcript_confidence", 0) or 0)
    return {
        "ad_slot_quality": int(float(segment.get("ad_slot_score", 0) or 0)),
        "attention": int(float(segment.get("attention_score", 0) or 0)),
        "low_drop_risk": 100 - int(float(segment.get("drop_risk_score", 100) or 100)),
        "brand_safety": int(float(segment.get("brand_safety_score", 0) or 0)),
        "natural_placement_boundary": int(round(boundary * 100)),
        "evidence_quality": int(round((fit["confidence"] + transcript_confidence) / 2)),
    }


def placement_recommendation(product: dict[str, Any], segment: dict[str, Any], fit: dict[str, Any]) -> tuple[int, str, str]:
    natural_boundary = natural_boundary_score(segment)
    placement_score = int(round(clamp(
        fit["fit_score"] / 100 * 0.38
        + float(segment.get("ad_slot_score", 0) or 0) / 100 * 0.24
        + float(segment.get("attention_score", 0) or 0) / 100 * 0.12
        + (1 - float(segment.get("drop_risk_score", 100) or 100) / 100) * 0.10
        + float(segment.get("brand_safety_score", 0) or 0) / 100 * 0.08
        + natural_boundary * 0.08
    ) * 100))
    if fit["blocked"]:
        placement_score = min(placement_score, 24)
    if fit["fit_score"] >= 65 and segment.get("transcript"):
        placement_type = "native spoken integration"
    elif fit["fit_score"] >= 45:
        placement_type = "contextual product overlay"
    else:
        placement_type = "brief visual placement"
    brand = product.get("brand_name") or product.get("name")
    timestamp = format_range(float(segment["start"]), float(segment["end"]))
    if fit["blocked"]:
        recommendation = f"Avoid {timestamp}: this moment conflicts with a prohibited context for {brand}."
    elif placement_score >= 70:
        recommendation = f"Use {timestamp} for a {placement_type} for {brand}; it combines product context with a stable ad window."
    elif placement_score >= 45:
        recommendation = f"Test {timestamp} for a short {placement_type} for {brand}; keep the execution light and validate performance."
    else:
        recommendation = f"Do not prioritize {timestamp} for {brand}; product-context evidence or viewer-window quality is limited."
    return placement_score, placement_type, recommendation


def video_analysis_fingerprint(video: sqlite3.Row, segments: list[dict[str, Any]]) -> str:
    stable = {
        "video_id": video["id"],
        "status": video["status"],
        "segments": [
            {
                "id": segment["id"], "start": segment["start"], "end": segment["end"],
                "attention": segment.get("attention_score"), "ad_fit": segment.get("ad_fit_score"),
                "drop": segment.get("drop_risk_score"), "safety": segment.get("brand_safety_score"),
                "transcript": segment.get("transcript"), "objects": segment.get("objects"), "topics": segment.get("topics"),
            }
            for segment in segments
        ],
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def product_fit_payload(fit_run: sqlite3.Row) -> dict[str, Any]:
    product = product_payload(get_product_or_404(fit_run["product_id"]))
    video = get_video_or_404(fit_run["video_id"])
    placements = []
    rows = query_all(
        """
        select product_placements.*, segments.start_time, segments.end_time, segments.summary, segments.thumbnail_url
        from product_placements join segments on segments.id = product_placements.segment_id
        where product_fit_run_id = ? order by placement_score desc, segments.start_time
        """,
        (fit_run["id"],),
    )
    for row in rows:
        placement = dict(row)
        placement["start"] = placement.pop("start_time")
        placement["end"] = placement.pop("end_time")
        for field, default in (
            ("reasons", []), ("component_breakdown", {}), ("positive_evidence", []),
            ("conflicting_evidence", []), ("limitations", []), ("evidence_coverage", {}),
            ("relevant_topics", []), ("relevant_objects", []),
        ):
            try:
                placement[field] = json.loads(placement.get(field) or json.dumps(default))
            except (TypeError, json.JSONDecodeError):
                placement[field] = default
        placement["is_best_placement"] = bool(placement["is_best_placement"])
        placements.append(placement)
    try:
        details = json.loads(fit_run["details_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        details = {}
    return {
        "fit_run_id": fit_run["id"],
        "video_id": video["id"],
        "video_title": video["title"],
        "product": product,
        "overall_fit_score": fit_run["overall_fit_score"],
        "fit_confidence": fit_run["fit_confidence"],
        "suitability_tier": fit_run["suitability_tier"],
        "summary": fit_run["summary"],
        "created_at": fit_run["created_at"],
        "placements": placements,
        "product_relevance_score": details.get("product_relevance_score", fit_run["overall_fit_score"]),
        "placement_readiness_score": details.get("placement_readiness_score", fit_run["overall_fit_score"]),
        "component_scores": details.get("component_scores", {}),
        "evidence_coverage": details.get("evidence_coverage", {}),
        "positive_evidence": details.get("positive_evidence", []),
        "conflicting_evidence": details.get("conflicting_evidence", []),
        "limitations": details.get("limitations", []),
        "missing_input_warnings": details.get("missing_input_warnings", []),
        "recommended_action": details.get("recommended_action", "Review the strongest timestamp before approving placement."),
        "cache_status": details.get("cache_status", "miss"),
        "scoring_version": fit_run["scoring_version"] or PRODUCT_FIT_SCORING_VERSION,
    }


def run_product_fit(product: sqlite3.Row, video: sqlite3.Row, comparison_id: str | None = None) -> dict[str, Any]:
    if video["status"] != "completed":
        raise HTTPException(status_code=400, detail="Complete the video analysis before running product fit.")
    analysis = build_analysis_payload(video)
    if not analysis["segments"]:
        raise HTTPException(status_code=400, detail="No analyzed segments are available for product fit.")
    profile = product_payload(product)
    product_fingerprint = profile.get("profile_fingerprint") or product_profile_fingerprint(profile)
    video_fingerprint = video_analysis_fingerprint(video, analysis["segments"])
    cached_run = query_one(
        """
        select * from product_fit_runs
        where product_id = ? and video_id = ? and product_fingerprint = ? and video_fingerprint = ? and scoring_version = ?
        order by created_at desc limit 1
        """,
        (product["id"], video["id"], product_fingerprint, video_fingerprint, PRODUCT_FIT_SCORING_VERSION),
    )
    if cached_run:
        cached_payload = product_fit_payload(cached_run)
        cached_payload["cache_status"] = "hit"
        return cached_payload

    placements = []
    prepared_segments = {segment["id"]: prepare_product_segment_context(segment) for segment in analysis["segments"]}
    for segment in analysis["segments"]:
        fit = score_product_segment_fit(profile, segment, prepared_segments[segment["id"]])
        score, placement_type, recommendation = placement_recommendation(profile, segment, fit)
        readiness_components = placement_readiness_breakdown(segment, fit)
        readiness_score = int(round(
            readiness_components["ad_slot_quality"] * 0.30
            + readiness_components["attention"] * 0.15
            + readiness_components["low_drop_risk"] * 0.15
            + readiness_components["brand_safety"] * 0.15
            + readiness_components["natural_placement_boundary"] * 0.15
            + readiness_components["evidence_quality"] * 0.10
        ))
        component_breakdown = {**fit["component_breakdown"], **readiness_components}
        placements.append({
            "segment_id": segment["id"],
            "start": segment["start"],
            "end": segment["end"],
            "placement_score": score,
            "placement_type": placement_type,
            "recommendation": recommendation,
            "reasons": fit["reasons"] + [f"product fit: {fit['fit_score']}", f"fit confidence: {fit['confidence']}"],
            "fit_score": fit["fit_score"],
            "product_relevance_score": fit["fit_score"],
            "placement_readiness_score": readiness_score,
            "fit_confidence": fit["confidence"],
            "blocked": fit["blocked"],
            "component_breakdown": component_breakdown,
            "positive_evidence": fit["positive_evidence"],
            "conflicting_evidence": fit["conflicting_evidence"],
            "limitations": fit["limitations"],
            "evidence_coverage": fit["evidence_coverage"],
            "transcript_excerpt": str(segment.get("transcript") or "").strip()[:320],
            "relevant_topics": fit["relevant_topics"],
            "relevant_objects": fit["relevant_objects"],
            "suggested_duration": f"{max(1, int(round(float(segment['end']) - float(segment['start']))))} seconds",
        })
    placements.sort(key=lambda item: (item["placement_score"], item["fit_score"]), reverse=True)
    leading = placements[:max(1, min(3, len(placements)))]
    overall_score = int(round(float(np.mean([item["placement_score"] for item in leading]))))
    product_relevance_score = int(round(float(np.mean([item["product_relevance_score"] for item in leading]))))
    placement_readiness_score = int(round(float(np.mean([item["placement_readiness_score"] for item in leading]))))
    confidence = int(round(float(np.mean([item["fit_confidence"] for item in leading]))))
    best = placements[0]
    if best["blocked"] or overall_score < 35:
        tier = "Not suitable"
    elif overall_score >= 70 and product_relevance_score >= 60 and confidence >= 65:
        tier = "Strong fit"
    elif overall_score >= 48:
        tier = "Conditional fit"
    else:
        tier = "Weak fit"
    product_name = profile.get("brand_name") or profile.get("name")
    if tier == "Strong fit":
        summary = f"{product_name} is a strong contextual fit. Prioritize {format_range(best['start'], best['end'])} with evidence confidence {confidence}."
    elif tier == "Conditional fit":
        summary = f"{product_name} can be tested in this video, but the strongest placement needs a lightweight execution and performance validation."
    else:
        summary = f"{product_name} has insufficient contextual evidence for a confident placement in this video."
    missing_input_warnings = list(profile.get("warnings") or [])
    if not profile.get("audience"):
        missing_input_warnings.append("Add a target audience to improve audience-alignment scoring.")
    if not profile.get("prohibited_contexts"):
        missing_input_warnings.append("Add prohibited contexts to make the safety gate product-specific.")
    if tier == "Strong fit":
        recommended_action = f"Use {format_range(best['start'], best['end'])} as the primary {best['placement_type']} candidate, then validate the final creative."
    elif tier == "Conditional fit":
        recommended_action = f"Test a lightweight integration at {format_range(best['start'], best['end'])} and review the weak evidence before launch."
    elif tier == "Weak fit":
        recommended_action = "Improve the product profile or video context before prioritizing an integration."
    else:
        recommended_action = "Do not place this product in the current edit unless the blocking context or missing evidence is resolved."

    component_keys = sorted({key for item in leading for key in item["component_breakdown"]})
    component_scores = {
        key: int(round(float(np.mean([item["component_breakdown"].get(key, 0) for item in leading]))))
        for key in component_keys
    }
    coverage_keys = ("transcript_matches", "topic_matches", "visual_matches")
    evidence_coverage = {
        key: sum(int(item["evidence_coverage"].get(key, 0)) for item in leading) for key in coverage_keys
    }
    evidence_coverage["modalities"] = max(int(item["evidence_coverage"].get("modalities", 0)) for item in leading)
    details = {
        "product_relevance_score": product_relevance_score,
        "placement_readiness_score": placement_readiness_score,
        "component_scores": component_scores,
        "evidence_coverage": evidence_coverage,
        "positive_evidence": best["positive_evidence"],
        "conflicting_evidence": best["conflicting_evidence"],
        "limitations": best["limitations"],
        "missing_input_warnings": list(dict.fromkeys(missing_input_warnings)),
        "recommended_action": recommended_action,
        "cache_status": "miss",
    }
    run_id = new_id("product_fit")
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            insert into product_fit_runs
            (id, product_id, video_id, comparison_id, overall_fit_score, fit_confidence, suitability_tier, summary,
             product_fingerprint, video_fingerprint, scoring_version, details_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, product["id"], video["id"], comparison_id, overall_score, confidence, tier, summary,
                product_fingerprint, video_fingerprint, PRODUCT_FIT_SCORING_VERSION, json.dumps(details), now,
            ),
        )
        for index, placement in enumerate(placements):
            conn.execute(
                """
                insert into product_placements
                (id, product_fit_run_id, segment_id, placement_score, placement_type, recommendation, reasons,
                 product_relevance_score, placement_readiness_score, component_breakdown, positive_evidence,
                 conflicting_evidence, limitations, evidence_coverage, transcript_excerpt, relevant_topics,
                 relevant_objects, suggested_duration, is_best_placement, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("product_placement"), run_id, placement["segment_id"], placement["placement_score"],
                    placement["placement_type"], placement["recommendation"], json.dumps(placement["reasons"]),
                    placement["product_relevance_score"], placement["placement_readiness_score"],
                    json.dumps(placement["component_breakdown"]), json.dumps(placement["positive_evidence"]),
                    json.dumps(placement["conflicting_evidence"]), json.dumps(placement["limitations"]),
                    json.dumps(placement["evidence_coverage"]), placement["transcript_excerpt"],
                    json.dumps(placement["relevant_topics"]), json.dumps(placement["relevant_objects"]),
                    placement["suggested_duration"], 1 if index == 0 else 0, now,
                ),
            )
        conn.commit()
    return product_fit_payload(query_one("select * from product_fit_runs where id = ?", (run_id,)))


def build_analysis_payload(video: sqlite3.Row) -> dict[str, Any]:
    segment_rows = query_all("select * from segments where video_id = ? order by start_time", (video["id"],))
    segments = []
    all_objects = []
    all_topics = []
    all_ad_matches = []
    for row in segment_rows:
        objects = [dict(item) for item in query_all("select * from detected_objects where segment_id = ?", (row["id"],))]
        detected_text = [dict(item) for item in query_all("select * from detected_text where segment_id = ? order by confidence desc", (row["id"],))]
        topics = [dict(item) for item in query_all("select * from topics where segment_id = ?", (row["id"],))]
        matches = [dict(item) for item in query_all("select * from ad_matches where segment_id = ? order by ad_fit_score desc", (row["id"],))]
        for obj in objects:
            obj["bbox"] = json.loads(obj["bbox"]) if obj.get("bbox") else None
        for item in detected_text:
            item["bbox"] = json.loads(item["bbox"]) if item.get("bbox") else None
            obj["mask"] = json.loads(obj["mask"]) if obj.get("mask") else None
        audio_evidence = json.loads(row["audio_evidence"]) if row["audio_evidence"] else {"available": False}
        if isinstance(audio_evidence, dict):
            audio_evidence.pop("waveform_energy", None)
        segments.append(
            {
                "id": row["id"],
                "start": row["start_time"],
                "end": row["end_time"],
                "attention_score": row["attention_score"],
                "ad_fit_score": row["ad_fit_score"],
                "drop_risk_score": row["drop_risk_score"] if row["drop_risk_score"] is not None else max(0, 100 - row["attention_score"]),
                "brand_safety_score": row["brand_safety_score"] if row["brand_safety_score"] is not None else 100,
                "label": row["label"],
                "summary": row["summary"],
                "transcript": row["transcript"],
                "transcript_insights": json.loads(row["transcript_insights"]) if row["transcript_insights"] else {},
                "visual_evidence": json.loads(row["visual_evidence"]) if row["visual_evidence"] else {},
                "detector_provenance": json.loads(row["detector_provenance"]) if row["detector_provenance"] else {},
                "audio_evidence": audio_evidence,
                "narrative_evidence": json.loads(row["narrative_evidence"]) if row["narrative_evidence"] else {},
                "social_evidence": json.loads(row["social_evidence"]) if row["social_evidence"] else {},
                "ocr_evidence": json.loads(row["ocr_evidence"]) if row["ocr_evidence"] else {"available": False},
                "signal_summary": json.loads(row["signal_summary"]) if row["signal_summary"] else {},
                "review_state": row["review_state"] or "unreviewed",
                "score_reasons": json.loads(row["score_reasons"]) if row["score_reasons"] else [],
                "recommendation": row["recommendation"],
                "recommendation_tier": row["recommendation_tier"] or "Edit before monetization",
                "recommendation_confidence": row["recommendation_confidence"] or 0,
                "evidence_mode": row["evidence_mode"] or "weak_evidence",
                "strong_signals": json.loads(row["strong_signals"]) if row["strong_signals"] else [],
                "failed_or_weak_signals": json.loads(row["failed_or_weak_signals"]) if row["failed_or_weak_signals"] else [],
                "ad_slot_score": row["ad_slot_score"] if row["ad_slot_score"] is not None else 0,
                "ad_slot_reasons": json.loads(row["ad_slot_reasons"]) if row["ad_slot_reasons"] else [],
                "is_best_ad_slot": bool(row["is_best_ad_slot"]),
                "thumbnail_url": row["thumbnail_url"],
                "objects": objects,
                "detected_text": detected_text,
                "topics": topics,
                "ad_matches": matches,
            }
        )
        all_objects.extend(objects)
        all_topics.extend(topics)
        all_ad_matches.extend(matches)

    summary = summarize(video, segments)
    exports = {
        "csv": f"/api/videos/{video['id']}/export?format=csv" if video["status"] == "completed" else None,
        "json": f"/api/videos/{video['id']}/export?format=json" if video["status"] == "completed" else None,
    }
    signal_payload = build_signal_payload(segments)
    latest_run = query_one(
        "select * from analysis_runs where video_id = ? order by started_at desc limit 1", (video["id"],)
    )
    if latest_run:
        run_payload = dict(latest_run)
        for field in ("model_manifest", "signal_availability", "timings"):
            run_payload[field] = json.loads(run_payload[field]) if run_payload.get(field) else {}
        signal_payload["analysis_run"] = run_payload
        review_rows = query_all(
            "select state, count(*) as count from evidence_review_tasks where analysis_run_id = ? group by state",
            (latest_run["id"],),
        )
        review_counts = {row["state"]: int(row["count"]) for row in review_rows}
        approved_segments = review_counts.get("approved", 0)
        signal_payload["review_summary"] = {
            "state": (
                "approved"
                if segments and approved_segments >= len(segments)
                else "in_review"
                if review_rows
                else "unreviewed"
            ),
            "reviewed_segments": approved_segments,
            "total_segments": len(segments),
            "counts": review_counts,
        }
    else:
        signal_payload["analysis_run"] = None
    return {
        "video": {
            "id": video["id"],
            "title": video["title"],
            "description": video["description"],
            "duration": video["duration_seconds"],
            "thumbnail": video["thumbnail_url"],
            "source_type": video["source_type"],
            "source_url": video["source_url"],
            "file_url": media_url_for_reference(video["file_path"]),
            "embed_url": video["embed_url"],
            "status": video["status"],
        },
        "summary": summary,
        "segments": segments,
        "objects": all_objects,
        "topics": all_topics,
        "ad_matches": all_ad_matches,
        "ad_categories": [item["category"] for item in AD_CATALOG],
        "recommendations": build_recommendations(summary, segments),
        "detailed_insight_report": detailed_insight_status("video", video["id"]),
        "exports": exports,
        **signal_payload,
    }


def infer_video_category(payload: dict[str, Any]) -> tuple[str, int]:
    topic_counts: Counter[str] = Counter()
    topic_confidences: dict[str, list[float]] = {}
    for topic in payload.get("topics", []):
        label = str(topic.get("label", "")).strip().lower()
        if not label:
            continue
        confidence = float(topic.get("confidence", 0.0) or 0.0)
        topic_counts[label] += 1
        topic_confidences.setdefault(label, []).append(confidence)
    if not topic_counts:
        return "general", 0
    category, count = topic_counts.most_common(1)[0]
    confidence = int(round(clamp(float(np.mean(topic_confidences[category])) * 0.7 + min(1.0, count / 3) * 0.3) * 100))
    return category, confidence


def extract_video_keywords(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stop_words = {
        "this", "that", "with", "from", "your", "about", "there", "their", "have", "will", "just", "they",
        "video", "watch", "today", "really", "being", "would", "could", "should", "because", "where",
    }
    terms: Counter[str] = Counter()
    evidence: dict[str, set[str]] = {}
    for topic in payload.get("topics", []):
        label = str(topic.get("label", "")).strip().lower()
        if label:
            terms[label] += 4
            evidence.setdefault(label, set()).add("topic")
    for segment in payload.get("segments", []):
        for match in segment.get("ad_matches", []):
            label = str(match.get("ad_category", "")).strip().lower()
            if label:
                terms[label] += 3
                evidence.setdefault(label, set()).add("ad context")
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", str(segment.get("transcript", "")).lower()):
            if word not in stop_words:
                terms[word] += 1
                evidence.setdefault(word, set()).add("transcript")
        for item in segment.get("detected_text", []):
            for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", str(item.get("text", "")).lower()):
                if word not in stop_words:
                    terms[word] += 2
                    evidence.setdefault(word, set()).add("on-screen text")
    keywords = []
    for keyword, count in terms.most_common(12):
        source = evidence.get(keyword, set())
        keyword_type = "advertising" if "ad context" in source else ("content" if "topic" in source else "audience")
        keywords.append(
            {
                "keyword": keyword,
                "type": keyword_type,
                "confidence": min(95, 45 + count * 8),
                "evidence": sorted(source),
            }
        )
    return keywords


def comparison_evidence_confidence(payload: dict[str, Any]) -> int:
    segments = payload.get("segments", [])
    if not segments:
        return 0
    transcript = float(np.mean([segment.get("transcript_insights", {}).get("transcript_confidence", 0) for segment in segments]))
    visual = float(np.mean([segment.get("visual_evidence", {}).get("visual_quality", 0) * 100 for segment in segments]))
    object_evidence = float(np.mean([min(100, segment.get("visual_evidence", {}).get("object_count", 0) * 35) for segment in segments]))
    temporal = float(np.mean([segment.get("transcript_insights", {}).get("timestamp_coverage", 0) * 100 for segment in segments]))
    return int(round(transcript * 0.40 + visual * 0.25 + object_evidence * 0.20 + temporal * 0.15))


def build_comparison_payload(comparison: sqlite3.Row) -> dict[str, Any]:
    members = query_all("select * from comparison_videos where comparison_id = ? order by display_order", (comparison["id"],))
    videos: list[dict[str, Any]] = []
    for member in members:
        video = get_video_or_404(member["video_id"])
        if member["processing_status"] != "completed" or video["status"] != "completed":
            videos.append(
                {
                    "video_id": video["id"],
                    "title": video["title"],
                    "status": member["processing_status"],
                    "error": member["error"],
                    "individual_report_url": f"/dashboard/{video['id']}" if video["status"] == "completed" else None,
                }
            )
            continue
        payload = build_analysis_payload(video)
        category, category_confidence = infer_video_category(payload)
        summary = payload["summary"]
        best_slot = max(payload["segments"], key=lambda item: item.get("ad_slot_score", 0), default=None)
        evidence_confidence = comparison_evidence_confidence(payload)
        decision_by_key = {metric.get("key"): metric for metric in payload.get("decision_metrics", [])}
        readable_values = [
            float(segment.get("signal_summary", {}).get("visual", {}).get("text_readability")) * 100
            for segment in payload["segments"]
            if segment.get("signal_summary", {}).get("visual", {}).get("text_readability") is not None
        ]
        audio_change_values = [
            average_values(
                [
                    float(segment.get("audio_evidence", {}).get("sudden_volume_change", 0) or 0),
                    float(segment.get("audio_evidence", {}).get("sudden_audio_discontinuity", 0) or 0),
                ]
            )
            for segment in payload["segments"]
            if segment.get("audio_evidence", {}).get("available")
        ]
        batch_signals = {
            "hook_strength": decision_by_key.get("hook_strength", {}).get("score"),
            "content_momentum": decision_by_key.get("content_momentum", {}).get("score"),
            "message_clarity": decision_by_key.get("message_clarity", {}).get("score"),
            "low_creative_friction": decision_by_key.get("creative_friction", {}).get("score"),
            "placement_readiness": decision_by_key.get("placement_readiness", {}).get("score"),
            "keyword_coverage": min(100, len(extract_video_keywords(payload)) * 10),
            "text_readability": int(round(float(np.mean(readable_values)))) if readable_values else None,
            "audio_stability": int(round((1 - clamp(float(np.mean(audio_change_values)))) * 100)) if audio_change_values else None,
            "evidence_reliability": decision_by_key.get("evidence_reliability", {}).get("score", evidence_confidence),
        }
        composite = int(round(
            summary.get("overall_attention_score", 0) * 0.30
            + summary.get("monetization_opportunity_score", 0) * 0.20
            + summary.get("creator_readiness_score", 0) * 0.20
            + summary.get("brand_safety_score", 0) * 0.10
            + (100 - summary.get("overall_drop_risk_score", 100)) * 0.10
            + evidence_confidence * 0.10
        ))
        videos.append(
            {
                "video_id": video["id"],
                "title": video["title"],
                "status": "completed",
                "duration": video["duration_seconds"],
                "thumbnail": video["thumbnail_url"],
                "individual_report_url": f"/dashboard/{video['id']}",
                "category": category,
                "category_confidence": category_confidence,
                "evidence_confidence": evidence_confidence,
                "score": composite,
                "metrics": {
                    "attention": summary.get("overall_attention_score", 0),
                    "monetization": summary.get("monetization_opportunity_score", 0),
                    "drop_risk": summary.get("overall_drop_risk_score", 0),
                    "brand_safety": summary.get("brand_safety_score", 0),
                    "visual_quality": summary.get("visual_quality_score", 0),
                    "transcript_clarity": summary.get("transcript_clarity_score", 0),
                    "creator_readiness": summary.get("creator_readiness_score", 0),
                    "ad_slot": best_slot.get("ad_slot_score", 0) if best_slot else 0,
                },
                "batch_signals": batch_signals,
                "decision_labels": {key: value.get("label") for key, value in decision_by_key.items()},
                "best_hook": summary.get("best_hook"),
                "strongest_ad_slot": {
                    "start": best_slot.get("start"),
                    "end": best_slot.get("end"),
                    "score": best_slot.get("ad_slot_score", 0),
                    "ad_fit_score": best_slot.get("ad_fit_score", 0),
                    "reasons": best_slot.get("ad_slot_reasons", []),
                } if best_slot else None,
                "keywords": extract_video_keywords(payload),
                "repeated_weaknesses": [
                    reason
                    for recommendation in payload.get("priority_recommendations", [])[1:5]
                    for reason in recommendation.get("why", [])
                ],
                "best_practices": (
                    payload.get("priority_recommendations", [{}])[0].get("why", [])
                    if payload.get("priority_recommendations")
                    else []
                ),
            }
        )

    completed = [video for video in videos if video["status"] == "completed"]
    categories = {video["category"] for video in completed}
    comparison_mode = "same_category" if len(categories) == 1 and completed else ("mixed" if completed else "pending")
    inferred_category = next(iter(categories)) if comparison_mode == "same_category" else "mixed"
    ranked = sorted(completed, key=lambda item: item["score"], reverse=True)
    for index, item in enumerate(ranked):
        item["rank"] = index + 1
        item["percentile"] = 50 if len(ranked) == 1 else int(round(100 * (len(ranked) - index - 1) / (len(ranked) - 1)))
        item["normalized_score"] = 50 if len(ranked) == 1 else int(round(100 * (item["score"] - ranked[-1]["score"]) / max(1, ranked[0]["score"] - ranked[-1]["score"])))
    for category in categories:
        category_items = sorted(
            [item for item in completed if item["category"] == category], key=lambda item: item["score"], reverse=True
        )
        for category_index, item in enumerate(category_items):
            item["category_benchmark_position"] = {
                "rank": category_index + 1,
                "total": len(category_items),
                "label": f"{category_index + 1} of {len(category_items)} in this uploaded batch",
            }

    shared_keywords: set[str] = set()
    if completed:
        keyword_sets = [{entry["keyword"] for entry in video["keywords"]} for video in completed]
        shared_keywords = set.intersection(*keyword_sets) if keyword_sets else set()
    metric_names = ["attention", "monetization", "drop_risk", "brand_safety", "visual_quality", "transcript_clarity", "creator_readiness", "ad_slot"]
    metric_comparison = [
        {
            "metric": metric,
            "values": [
                {"video_id": item["video_id"], "value": item["metrics"][metric], "rank": sorted(completed, key=lambda video: video["metrics"][metric], reverse=metric != "drop_risk").index(item) + 1}
                for item in completed
            ],
        }
        for metric in metric_names
    ]
    for metric in [
        "hook_strength", "content_momentum", "message_clarity", "low_creative_friction", "placement_readiness",
        "keyword_coverage", "text_readability", "audio_stability", "evidence_reliability",
    ]:
        available_items = [item for item in completed if item.get("batch_signals", {}).get(metric) is not None]
        if not available_items:
            continue
        ordered_items = sorted(available_items, key=lambda item: item["batch_signals"][metric], reverse=True)
        metric_comparison.append(
            {
                "metric": metric,
                "values": [
                    {
                        "video_id": item["video_id"],
                        "value": item["batch_signals"][metric],
                        "rank": ordered_items.index(item) + 1,
                    }
                    for item in available_items
                ],
            }
        )
    ab = None
    if len(completed) == 2:
        a, b = completed
        deltas = []
        for metric in metric_names:
            delta = b["metrics"][metric] - a["metrics"][metric]
            absolute_delta = abs(delta)
            winner = "tie" if absolute_delta < 5 else ("B" if (delta > 0) != (metric == "drop_risk") else "A")
            deltas.append({"metric": metric, "video_a": a["metrics"][metric], "video_b": b["metrics"][metric], "delta": delta, "winner": winner})
        overall_delta = b["score"] - a["score"]
        ab = {
            "video_a_id": a["video_id"],
            "video_b_id": b["video_id"],
            "winner": "tie" if abs(overall_delta) < 5 else ("B" if overall_delta > 0 else "A"),
            "confidence": int(round((a["evidence_confidence"] + b["evidence_confidence"]) / 2)),
            "deltas": deltas,
        }
    recommendations = []
    if ranked:
        winner = ranked[0]
        recommendations.append({"title": "Recommended video", "body": f"{winner['title']} ranks first in this comparison with a score of {winner['score']} and evidence confidence of {winner['evidence_confidence']}.", "video_id": winner["video_id"]})
        if winner["strongest_ad_slot"]:
            slot = winner["strongest_ad_slot"]
            recommendations.append({"title": "Strongest ad slot", "body": f"Use {format_range(slot['start'], slot['end'])} in {winner['title']} for the strongest evidence-backed contextual placement.", "video_id": winner["video_id"], "timestamp": format_range(slot["start"], slot["end"])})
    def best_batch_signal(signal_name: str) -> dict[str, Any] | None:
        candidates = [item for item in completed if item.get("batch_signals", {}).get(signal_name) is not None]
        if not candidates:
            return None
        best = max(candidates, key=lambda item: item["batch_signals"][signal_name])
        decision_key = {
            "low_creative_friction": "creative_friction",
            "evidence_reliability": "evidence_reliability",
        }.get(signal_name, signal_name)
        return {
            "video_id": best["video_id"],
            "title": best["title"],
            "score": best["batch_signals"][signal_name],
            "label": best.get("decision_labels", {}).get(decision_key),
        }

    weakness_counts = Counter(
        weakness for item in completed for weakness in item.get("repeated_weaknesses", [])
    )
    reusable_practices = list(
        dict.fromkeys(practice for item in ranked for practice in item.get("best_practices", []))
    )[:6]
    strongest_placement = best_batch_signal("placement_readiness")
    if strongest_placement:
        source_video = next(item for item in completed if item["video_id"] == strongest_placement["video_id"])
        strongest_placement["moment"] = source_video.get("strongest_ad_slot")
    batch_insights = {
        "best_hook": best_batch_signal("hook_strength"),
        "most_consistent_creative_momentum": best_batch_signal("content_momentum"),
        "clearest_message": best_batch_signal("message_clarity"),
        "lowest_creative_friction": best_batch_signal("low_creative_friction"),
        "strongest_placement_ready_moment": strongest_placement,
        "best_keyword_coverage": best_batch_signal("keyword_coverage"),
        "most_readable_on_screen_text": best_batch_signal("text_readability"),
        "most_stable_audio_quality": best_batch_signal("audio_stability"),
        "evidence_reliability": best_batch_signal("evidence_reliability"),
        "shared_themes": sorted(shared_keywords),
        "repeated_weaknesses": [
            {"finding": finding, "videos": count} for finding, count in weakness_counts.most_common(6)
        ],
        "best_practices_to_reuse": reusable_practices,
        "benchmark_scope": "Completed same-category videos in this uploaded batch only.",
    }
    return {
        "comparison": {
            "id": comparison["id"],
            "title": comparison["title"],
            "status": comparison["status"],
            "comparison_mode": comparison_mode,
            "inferred_category": inferred_category,
            "total_videos": comparison["total_videos"],
            "completed_videos": len(completed),
            "failed_videos": sum(1 for video in videos if video["status"] == "failed"),
        },
        "rankings": ranked,
        "videos": videos,
        "metric_comparison": metric_comparison,
        "shared_keywords": sorted(shared_keywords),
        "batch_insights": batch_insights,
        "ab": ab,
        "recommendations": recommendations,
        "detailed_insight_report": detailed_insight_status("comparison", comparison["id"]),
        "caveats": (["Cross-category comparison is directional; use category-specific benchmarks for decisions."] if comparison_mode == "mixed" else []) + (["At least two completed videos are required for a consolidated comparison."] if len(completed) < COMPARISON_MIN_VIDEOS else []),
    }


def persist_comparison_report(comparison_id: str) -> None:
    comparison = get_comparison_or_404(comparison_id)
    payload = build_comparison_payload(comparison)
    report_dir = REPORT_DIR / comparison_id
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "comparison.json"
    csv_path = report_dir / "comparison.csv"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "video_id", "title", "category", "score", "normalized_score", "percentile", "evidence_confidence", "attention", "ad_slot"])
        writer.writeheader()
        for item in payload["rankings"]:
            writer.writerow({
                "rank": item["rank"], "video_id": item["video_id"], "title": item["title"], "category": item["category"],
                "score": item["score"], "normalized_score": item["normalized_score"], "percentile": item["percentile"],
                "evidence_confidence": item["evidence_confidence"], "attention": item["metrics"]["attention"], "ad_slot": item["metrics"]["ad_slot"],
            })
    execute("delete from comparison_reports where comparison_id = ?", (comparison_id,))
    execute(
        "insert into comparison_reports (id, comparison_id, summary, csv_path, json_path, created_at) values (?, ?, ?, ?, ?, ?)",
        (new_id("comparison_report"), comparison_id, json.dumps(payload), str(csv_path), str(json_path), utc_now()),
    )
    execute(
        "update comparisons set comparison_mode = ?, inferred_category = ?, summary = ?, updated_at = ? where id = ?",
        (payload["comparison"]["comparison_mode"], payload["comparison"]["inferred_category"], json.dumps(payload["recommendations"]), utc_now(), comparison_id),
    )
    if OBJECT_STORAGE.ready:
        for path in [json_path, csv_path]:
            OBJECT_STORAGE.upload_file(path, object_key_for_local_path(path), content_type_for_suffix(path.suffix))


def summarize(video: sqlite3.Row, segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return {
            "overall_attention_score": 0,
            "monetization_opportunity_score": 0,
            "overall_drop_risk_score": 0,
            "brand_safety_score": 100,
            "transcript_clarity_score": 0,
            "visual_quality_score": 0,
            "creator_readiness_score": 0,
            "ad_catalog_size": len(AD_CATALOG),
            "best_hook": None,
            "best_ad_slot": None,
            "best_content_window": None,
            "best_recommendation_tier": "Avoid",
            "recommendation_status": "No analysis available",
            "recommendation_message": "No segment evidence is available yet.",
            "weakest_segment": None,
            "top_ad_category": None,
        }
    attention_scores = [float(segment["attention_score"]) for segment in segments]
    ad_scores = [float(segment["ad_fit_score"]) for segment in segments]
    drop_scores = [float(segment.get("drop_risk_score", 100 - segment["attention_score"])) for segment in segments]
    safety_scores = [float(segment.get("brand_safety_score", 100)) for segment in segments]
    clarity_scores = [float(segment.get("transcript_insights", {}).get("clarity_score", 0)) for segment in segments]
    visual_scores = [float(segment.get("visual_evidence", {}).get("visual_quality", 0)) * 100 for segment in segments]
    first_pool = [segment for segment in segments if segment["start"] < 10] or segments[:2]
    top_count = max(1, math.ceil(len(attention_scores) * 0.2))
    consistency = 100 - min(100, float(np.std(attention_scores)))
    overall = int(
        round(
            float(np.mean(attention_scores)) * 0.35
            + float(np.mean([segment["attention_score"] for segment in first_pool])) * 0.20
            + float(np.mean(sorted(attention_scores, reverse=True)[:top_count])) * 0.20
            + consistency * 0.15
            + float(np.mean(attention_scores[-min(2, len(attention_scores)) :])) * 0.10
        )
    )
    brand_safety = int(round(float(np.mean(safety_scores))))
    transcript_clarity = int(round(float(np.mean(clarity_scores)))) if any(clarity_scores) else 0
    visual_quality = int(round(float(np.mean(visual_scores)))) if any(visual_scores) else 0
    drop_risk = int(round(float(np.mean(drop_scores))))
    top_ad_mean = float(np.mean(sorted(ad_scores, reverse=True)[:top_count])) if ad_scores else 0
    monetization = int(round(top_ad_mean * 0.35 + brand_safety * 0.20 + overall * 0.20 + (100 - drop_risk) * 0.15 + visual_quality * 0.10))
    creator_readiness = int(round(overall * 0.28 + transcript_clarity * 0.20 + visual_quality * 0.18 + brand_safety * 0.18 + monetization * 0.16))
    hook_pool = [segment for segment in segments if segment["start"] < 15] or segments[:3]
    best_hook = max(hook_pool, key=lambda segment: segment["attention_score"])
    strong_candidates = [segment for segment in segments if segment.get("recommendation_tier") == "Strong ad slot" and segment["ad_fit_score"] > 0 and segment["ad_matches"]]
    best_ad = max(strong_candidates, key=lambda segment: segment.get("ad_slot_score", segment.get("recommendation_confidence", segment["ad_fit_score"]))) if strong_candidates else None
    best_content = max(segments, key=content_window_score)
    weakest = min(segments, key=lambda segment: segment["attention_score"])
    category_counts: dict[str, int] = {}
    for segment in segments:
        for match in segment["ad_matches"]:
            category_counts[match["ad_category"]] = category_counts.get(match["ad_category"], 0) + 1
    top_category = max(category_counts, key=category_counts.get) if category_counts and best_ad else "No confident ad category match"
    best_tier = best_ad.get("recommendation_tier") if best_ad else best_content.get("recommendation_tier", "Edit before monetization")
    if best_ad:
        recommendation_status = "Strong ad slot found"
        recommendation_message = f"Strong ad slot found at {format_range(best_ad['start'], best_ad['end'])} for {best_ad['ad_matches'][0]['ad_category']}."
    elif best_tier == "Conditional ad slot":
        recommendation_status = "Conditional slot only"
        recommendation_message = (
            f"No strong ad slot found. Best content-context window is {format_range(best_content['start'], best_content['end'])}; "
            "use it only after reviewing the weak signals."
        )
    elif best_tier == "Avoid":
        recommendation_status = "No reliable ad slot"
        recommendation_message = (
            f"No strong ad slot found. Best content-context window is {format_range(best_content['start'], best_content['end'])}, "
            "but editing is recommended before monetization."
        )
    else:
        recommendation_status = "Edit before monetization"
        recommendation_message = (
            f"No strong ad slot found. Best content-context window is {format_range(best_content['start'], best_content['end'])}, "
            "but editing is recommended before monetization."
        )
    return {
        "overall_attention_score": overall,
        "monetization_opportunity_score": monetization,
        "overall_drop_risk_score": drop_risk,
        "brand_safety_score": brand_safety,
        "transcript_clarity_score": transcript_clarity,
        "visual_quality_score": visual_quality,
        "creator_readiness_score": creator_readiness,
        "ad_catalog_size": len(AD_CATALOG),
        "best_hook": compact_segment(best_hook),
        "best_ad_slot": {**compact_segment(best_ad), "category": best_ad["ad_matches"][0]["ad_category"]} if best_ad else None,
        "best_content_window": compact_segment(best_content),
        "best_recommendation_tier": best_tier,
        "recommendation_status": recommendation_status,
        "recommendation_message": recommendation_message,
        "weakest_segment": compact_segment(weakest),
        "top_ad_category": top_category,
    }


def compact_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": segment["start"],
        "end": segment["end"],
        "score": segment["attention_score"],
        "ad_fit_score": segment["ad_fit_score"],
        "label": segment["label"],
        "recommendation_tier": segment.get("recommendation_tier", "Edit before monetization"),
        "recommendation_confidence": segment.get("recommendation_confidence", 0),
        "ad_slot_score": segment.get("ad_slot_score", 0),
        "ad_slot_reasons": segment.get("ad_slot_reasons", []),
    }


def content_window_score(segment: dict[str, Any]) -> float:
    visual_quality = float(segment.get("visual_evidence", {}).get("visual_quality", 0.0)) * 100
    return (
        float(segment.get("attention_score", 0)) * 0.32
        + float(segment.get("ad_fit_score", 0)) * 0.20
        + max(0, 100 - float(segment.get("drop_risk_score", 100))) * 0.22
        + float(segment.get("brand_safety_score", 100)) * 0.14
        + visual_quality * 0.12
    )


def build_recommendations(summary: dict[str, Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []
    best_ad = summary["best_ad_slot"]
    best_content = summary.get("best_content_window")
    weakest = summary["weakest_segment"]
    best_hook = summary["best_hook"]
    recommendations = [
        {
            "title": summary.get("recommendation_status", "Placement decision"),
            "timestamp": format_range(best_content["start"], best_content["end"]) if best_content else "Full video",
            "body": summary.get("recommendation_message", "Review the best content-context window before placing an ad."),
        },
        {
            "title": "Best hook moment",
            "timestamp": format_range(best_hook["start"], best_hook["end"]),
            "body": "Open with this pacing and clarity; it has the strongest early attention proxy signal.",
        },
        {
            "title": "Avoid-ad zone",
            "timestamp": format_range(weakest["start"], weakest["end"]),
            "body": "Avoid inserting ads here; the moment already has weaker attention and may increase drop risk.",
        },
    ]
    if best_ad:
        recommendations.insert(
            1,
            {
                "title": "Best ad placement",
                "timestamp": format_range(best_ad["start"], best_ad["end"]),
                "body": f"Test this slot for {best_ad['category']} because the detected evidence supports that brand category.",
            },
        )
    else:
        recommendations.insert(
            1,
            {
                "title": "Best available content window",
                "timestamp": format_range(best_content["start"], best_content["end"]) if best_content else "Full video",
                "body": "Use this as the review window, not an automatic ad placement. Improve weak evidence before monetization.",
            },
        )
    for segment in sorted(segments, key=lambda item: item["attention_score"])[:2]:
        recommendations.append(
            {
                "title": "Creator improvement",
                "timestamp": format_range(segment["start"], segment["end"]),
                "body": segment["recommendation"],
            }
        )
    return recommendations[:7]


def generate_exports(video_id: str) -> dict[str, Path]:
    video = get_video_or_404(video_id)
    payload = build_analysis_payload(video)
    json_path = REPORT_DIR / f"{video_id}.json"
    csv_path = REPORT_DIR / f"{video_id}.csv"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "segment_id",
                "start",
                "end",
                "attention_score",
                "attention_label",
                "ad_fit_score",
                "drop_risk_score",
                "brand_safety_score",
                "recommendation_tier",
                "recommendation_confidence",
                "evidence_mode",
                "strong_signals",
                "failed_or_weak_signals",
                "transcript_clarity_score",
                "transcript_confidence",
                "transcript_quality_flags",
                "visual_evidence",
                "score_reasons",
                "objects",
                "topics",
                "transcript",
                "recommendation",
            ],
        )
        writer.writeheader()
        for segment in payload["segments"]:
            writer.writerow(
                {
                    "segment_id": segment["id"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "attention_score": segment["attention_score"],
                    "attention_label": segment["label"],
                    "ad_fit_score": segment["ad_fit_score"],
                    "drop_risk_score": segment.get("drop_risk_score", ""),
                    "brand_safety_score": segment.get("brand_safety_score", ""),
                    "recommendation_tier": segment.get("recommendation_tier", ""),
                    "recommendation_confidence": segment.get("recommendation_confidence", ""),
                    "evidence_mode": segment.get("evidence_mode", ""),
                    "strong_signals": " | ".join(segment.get("strong_signals", [])),
                    "failed_or_weak_signals": " | ".join(segment.get("failed_or_weak_signals", [])),
                    "transcript_clarity_score": segment.get("transcript_insights", {}).get("clarity_score", ""),
                    "transcript_confidence": segment.get("transcript_insights", {}).get("transcript_confidence", ""),
                    "transcript_quality_flags": " | ".join(segment.get("transcript_insights", {}).get("transcript_quality_flags", [])),
                    "visual_evidence": json.dumps(segment.get("visual_evidence", {})),
                    "score_reasons": " | ".join(segment.get("score_reasons", [])),
                    "objects": ", ".join(obj["label"] for obj in segment["objects"]),
                    "topics": ", ".join(topic["label"] for topic in segment["topics"]),
                    "transcript": segment["transcript"],
                    "recommendation": segment["recommendation"],
                }
            )
    report_id = new_id("report")
    execute(
        "insert into reports (id, video_id, summary, csv_path, json_path, created_at) values (?, ?, ?, ?, ?, ?)",
        (report_id, video_id, json.dumps(payload["summary"]), str(csv_path), str(json_path), utc_now()),
    )
    return {"csv": csv_path, "json": json_path}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    if math.isnan(value):
        return lower
    return max(lower, min(upper, value))


def format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def format_range(start: float, end: float) -> str:
    return f"{format_time(start)}-{format_time(end)}"
ADMIN_SERVICES = AdminServices(
    execute=execute,
    query_one=query_one,
    query_all=query_all,
    new_id=new_id,
    utc_now=utc_now,
    runtime_dependencies=runtime_dependency_status,
    build_metadata=build_metadata,
)
app.include_router(create_admin_router(ADMIN_SERVICES))
