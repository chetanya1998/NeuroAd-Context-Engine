from __future__ import annotations

import csv
from collections import Counter
import importlib.util
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


APP_DIR = Path(__file__).resolve().parent


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


STORAGE_DIR = path_from_env("NEUROAD_STORAGE_DIR", APP_DIR / "storage")
UPLOAD_DIR = STORAGE_DIR / "uploads"
FRAME_DIR = STORAGE_DIR / "frames"
AUDIO_DIR = STORAGE_DIR / "audio"
REPORT_DIR = STORAGE_DIR / "reports"
DB_PATH = path_from_env("NEUROAD_DB_PATH", STORAGE_DIR / "neuroad.db")
MODEL_DIR = path_from_env("NEUROAD_MODEL_DIR", STORAGE_DIR.parent / "models")
VOSK_MODEL_DIR = path_from_env("VOSK_MODEL_DIR", MODEL_DIR / "vosk-model-small-en-us-0.15")
MOBILENET_SSD_GRAPH = path_from_env("MOBILENET_SSD_GRAPH", MODEL_DIR / "mobilenet-ssd" / "frozen_inference_graph.pb")
MOBILENET_SSD_CONFIG = path_from_env(
    "MOBILENET_SSD_CONFIG",
    MODEL_DIR / "mobilenet-ssd" / "ssd_mobilenet_v1_coco.pbtxt",
)

MAX_UPLOAD_BYTES = int_from_env("NEUROAD_MAX_UPLOAD_MB", 200) * 1024 * 1024
MAX_SOURCE_SECONDS = int_from_env("NEUROAD_MAX_SOURCE_SECONDS", 0)
MAX_ANALYSIS_SECONDS = int_from_env("NEUROAD_MAX_ANALYSIS_SECONDS", 180)
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
FRAME_SAMPLE_RATE = float(os.getenv("NEUROAD_FRAME_SAMPLE_RATE", "1.0") or "1.0")
MAX_FRAMES_PER_SEGMENT = max(1, int_from_env("NEUROAD_MAX_FRAMES_PER_SEGMENT", 6))
VOSK_MODEL_CACHE: Any | None = None
MOBILENET_SSD_NET_CACHE: Any | None = None

PROCESSING_STEPS = [
    ("metadata", "Metadata fetched"),
    ("frames", "Frames extracted"),
    ("audio", "Audio prepared"),
    ("transcript", "Transcript processed"),
    ("objects", "YOLO/Object detection complete"),
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

HOOK_TERMS = ["how", "why", "what if", "today", "before", "after", "mistake", "secret", "show you", "watch"]
CTA_TERMS = ["subscribe", "try", "buy", "click", "comment", "save", "share", "check out", "download", "follow"]
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
    for directory in [UPLOAD_DIR, FRAME_DIR, AUDIO_DIR, REPORT_DIR, MODEL_DIR]:
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
    ultralytics_available = importlib.util.find_spec("ultralytics") is not None
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
        "mobilenet_ssd": {
            "available": MOBILENET_SSD_GRAPH.exists() and MOBILENET_SSD_CONFIG.exists(),
            "graph_path": str(MOBILENET_SSD_GRAPH),
            "config_path": str(MOBILENET_SSD_CONFIG),
        },
        "ultralytics": {"available": ultralytics_available, "path": None, "model": os.getenv("YOLO_MODEL", "yolov8n.pt")},
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


ensure_storage_dirs()
app = FastAPI(title="NeuroAd Context Engine API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_env(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=str(STORAGE_DIR)), name="media")


class YouTubeRequest(BaseModel):
    url: str


class YouTubeIngestRequest(BaseModel):
    url: str
    has_permission: bool = False


class VideoUrlRequest(BaseModel):
    url: str


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
    return f"/media/{rel.as_posix()}"


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
              created_at text not null
            );

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


@app.get("/health")
def health() -> dict[str, Any]:
    dependencies = runtime_dependency_status()
    storage_ready = STORAGE_DIR.exists() and os.access(STORAGE_DIR, os.W_OK)
    db_ready = DB_PATH.parent.exists() and os.access(DB_PATH.parent, os.W_OK)
    media_ready = bool(dependencies["ffmpeg"]["available"] and dependencies["ffprobe"]["available"])
    ready = bool(storage_ready and db_ready and media_ready)
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "storage_ready": storage_ready,
        "database_ready": db_ready,
        "storage_dir": str(STORAGE_DIR),
        "database_path": str(DB_PATH),
        "limits": {
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_source_seconds": MAX_SOURCE_SECONDS,
            "max_analysis_seconds": MAX_ANALYSIS_SECONDS,
            "workers": int_from_env("NEUROAD_WORKERS", 1),
        },
        "dependencies": dependencies,
    }


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
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
    return {"video_id": video_id, "status": "uploaded", "duration_seconds": duration}


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


@app.post("/api/videos/{video_id}/analyze")
def analyze_video(video_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    video = get_video_or_404(video_id)
    existing = query_one("select * from jobs where video_id = ? order by created_at desc limit 1", (video_id,))
    if existing and existing["status"] in {"queued", "processing"}:
        return {"job_id": existing["id"], "status": existing["status"]}

    job_id = new_id("job")
    execute(
        """
        insert into jobs (id, video_id, status, progress, current_step, error, created_at, updated_at)
        values (?, ?, 'queued', 0, 'metadata', null, ?, ?)
        """,
        (job_id, video_id, utc_now(), utc_now()),
    )

    if not video["file_path"] and video["source_type"] not in {"url", "youtube_ingest"}:
        update_job(
            job_id,
            "failed",
            100,
            "metadata",
            "No analyzable media file is attached. Upload a video or provide a direct MP4/MOV/WebM URL.",
        )
        execute("update videos set status = 'failed' where id = ?", (video_id,))
        return {"job_id": job_id, "status": "failed"}

    EXECUTOR.submit(process_upload_job, job_id, video_id)
    return {"job_id": job_id, "status": "queued"}


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


def process_upload_job(job_id: str, video_id: str) -> None:
    video = query_one("select * from videos where id = ?", (video_id,))
    if not video:
        update_job(job_id, "failed", 0, "metadata", "Video not found")
        return
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

        source = Path(video["file_path"])
        source = normalize_video_for_analysis(source, video_id)
        if str(source) != video["file_path"]:
            execute("update videos set file_path = ? where id = ?", (str(source), video_id))
            video = query_one("select * from videos where id = ?", (video_id,))
        duration = probe_duration_or_raise(source)
        enforce_source_duration(duration)
        update_job(job_id, "processing", 8, "metadata")

        segments = make_segments(duration)
        frames = extract_frames(video_id, source, segments)
        update_job(job_id, "processing", 20, "frames")

        audio_path = extract_audio(video_id, source)
        analysis_audio_path = prepare_audio_for_analysis(video_id, audio_path) if audio_path else None
        audio_metrics = compute_audio_metrics(analysis_audio_path, segments) if analysis_audio_path else {}
        update_job(job_id, "processing", 32, "audio")

        transcript_segments = transcribe_audio(analysis_audio_path) if analysis_audio_path else []
        update_job(job_id, "processing", 48, "transcript")

        detections = detect_objects(frames)
        update_job(job_id, "processing", 62, "objects")

        enriched_segments = assemble_segments(segments, frames, transcript_segments, detections, audio_metrics, video)
        update_job(job_id, "processing", 74, "topics")

        update_job(job_id, "processing", 82, "attention")
        write_analysis(video_id, enriched_segments)
        update_job(job_id, "processing", 90, "ad_scoring")

        generate_exports(video_id)
        execute(
            "update videos set status = 'completed', duration_seconds = ?, thumbnail_url = ? where id = ?",
            (int(duration), enriched_segments[0].get("thumbnail_url") if enriched_segments else None, video_id),
        )
        update_job(job_id, "completed", 100, "report")
    except Exception as exc:
        execute("update videos set status = 'failed' where id = ?", (video_id,))
        update_job(job_id, "failed", 100, "failed", public_job_error(exc))


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
    interval = 1.0 / max(0.1, FRAME_SAMPLE_RATE)
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
        return {"brightness": 0.5, "contrast": 0.0, "sharpness": 0.0, "colorfulness": 0.0}
    grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return {
        "brightness": float(np.mean(grayscale) / 255),
        "contrast": float(np.std(grayscale) / 90),
        "sharpness": clamp(float(cv2.Laplacian(grayscale, cv2.CV_64F).var()) / 500),
        "colorfulness": colorfulness_score(frame),
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
    frame_data: dict[int, dict[str, Any]] = {}
    previous_gray_small: Any | None = None

    for segment in segments:
        timestamps = sample_timestamps(segment["start"], segment["end"])
        snapshots: list[dict[str, float]] = []
        motion_values: list[float] = []
        representative_frame: Any | None = None
        representative_timestamp = (segment["start"] + segment["end"]) / 2
        representative_gray_small: Any | None = None

        for index, timestamp in enumerate(timestamps):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0, timestamp) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            if representative_frame is None or index == len(timestamps) // 2:
                representative_frame = frame
                representative_timestamp = timestamp

            grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_small = cv2.resize(grayscale, (160, 90))
            if representative_gray_small is None or index == len(timestamps) // 2:
                representative_gray_small = gray_small
            if previous_gray_small is not None:
                motion_values.append(float(np.mean(np.abs(gray_small.astype(np.float32) - previous_gray_small.astype(np.float32))) / 255))
            previous_gray_small = gray_small
            snapshots.append(frame_metric_snapshot(frame))

        if representative_frame is None or not snapshots:
            continue
        frame_path = output_dir / f"frame_{segment['index']:03d}.jpg"
        cv2.imwrite(str(frame_path), representative_frame)
        grayscale = cv2.cvtColor(representative_frame, cv2.COLOR_BGR2GRAY)
        averaged = {
            key: float(np.mean([snapshot[key] for snapshot in snapshots]))
            for key in ["brightness", "contrast", "sharpness", "colorfulness"]
        }
        frame_data[segment["index"]] = {
            "path": frame_path,
            "timestamp": representative_timestamp,
            "mean": float(np.mean(grayscale)),
            "std": float(np.std(grayscale)),
            "shape": representative_frame.shape,
            "sampled_frames": len(snapshots),
            "brightness": averaged["brightness"],
            "contrast": clamp(averaged["contrast"]),
            "sharpness": averaged["sharpness"],
            "colorfulness": averaged["colorfulness"],
            "motion": clamp(float(np.mean(motion_values)) if motion_values else 0.0),
            "visual_quality": clamp(averaged["sharpness"] * 0.6 + (1 - abs(averaged["brightness"] - 0.5) * 2) * 0.4),
        }
    cap.release()
    return frame_data


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
    with wave.open(str(audio_path), "rb") as wav:
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32)
    metrics: dict[int, float] = {}
    for segment in segments:
        start = int(segment["start"] * rate)
        end = int(segment["end"] * rate)
        chunk = samples[start:end]
        if chunk.size == 0:
            metrics[segment["index"]] = 0.0
            continue
        rms = float(np.sqrt(np.mean(np.square(chunk))) / 32768)
        metrics[segment["index"]] = clamp(rms * 4)
    return metrics


def transcribe_audio(audio_path: Path) -> list[dict[str, Any]]:
    if os.getenv("NEUROAD_ENABLE_TRANSCRIPTION", "1").lower() in {"0", "false", "no", "off"}:
        return []
    engine = os.getenv("NEUROAD_TRANSCRIPTION_ENGINE", "vosk").lower()
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


def detect_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    if os.getenv("NEUROAD_ENABLE_OBJECT_DETECTION", "1").lower() in {"0", "false", "no", "off"}:
        return detect_lightweight_visual_context(frames)
    engine = os.getenv("NEUROAD_OBJECT_DETECTION_ENGINE", "mobilenet_ssd").lower()
    try:
        if engine == "mobilenet_ssd":
            return normalize_object_detections(detect_mobilenet_ssd_objects(frames))
        if engine == "yolo":
            try:
                return normalize_object_detections(detect_yolo_objects(frames))
            except Exception:
                if object_detection_required():
                    raise
                return normalize_object_detections(detect_mobilenet_ssd_objects(frames))
        return detect_lightweight_visual_context(frames)
    except Exception:
        if object_detection_required():
            raise
        return detect_lightweight_visual_context(frames)


def object_detection_required() -> bool:
    return os.getenv("NEUROAD_REQUIRE_OBJECT_DETECTION", "0").lower() in {"1", "true", "yes", "on"}


def normalize_object_detections(detections: dict[int, list[dict[str, Any]]]) -> dict[int, list[dict[str, Any]]]:
    if not detections:
        return detections

    total_segments = len(detections)
    person_only_segments = 0
    for objects in detections.values():
        labels = {str(obj.get("label", "")).lower() for obj in objects}
        if labels and labels.issubset({"person"}):
            person_only_segments += 1

    person_only_ratio = person_only_segments / max(1, total_segments)
    if total_segments < 3 or person_only_ratio < 0.6:
        return detections

    normalized: dict[int, list[dict[str, Any]]] = {}
    for segment_index, objects in detections.items():
        non_person_objects = [obj for obj in objects if str(obj.get("label", "")).lower() != "person"]
        if non_person_objects:
            normalized[segment_index] = non_person_objects[:5]
        else:
            normalized[segment_index] = []
    return normalized


def detect_yolo_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("ultralytics is required for YOLO object detection.") from exc
    model_name = os.getenv("YOLO_MODEL", "yolov8n.pt")
    model = YOLO(model_name)
    output: dict[int, list[dict[str, Any]]] = {}
    for segment_index, frame in frames.items():
        results = model(str(frame["path"]), verbose=False)
        detections: list[dict[str, Any]] = []
        for result in results:
            names = result.names
            for box in result.boxes:
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                xyxy = [float(value) for value in box.xyxy[0].tolist()]
                detections.append(
                    {
                        "label": names.get(cls_id, str(cls_id)),
                        "confidence": confidence,
                        "bbox": xyxy,
                        "frame_timestamp": frame["timestamp"],
                    }
                )
        output[segment_index] = sorted(detections, key=lambda item: item["confidence"], reverse=True)[:5]
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

    output: dict[int, list[dict[str, Any]]] = {}
    for segment_index, frame in frames.items():
        image = cv2.imread(str(frame["path"]))
        if image is None:
            output[segment_index] = []
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
                    "frame_timestamp": frame["timestamp"],
                }
            )
        output[segment_index] = sorted(objects, key=lambda item: item["confidence"], reverse=True)[:5]
    return output


def detect_lightweight_visual_context(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    try:
        import cv2
    except ImportError:
        return {segment_index: [] for segment_index in frames}

    face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    output: dict[int, list[dict[str, Any]]] = {}
    for segment_index, frame in frames.items():
        image = cv2.imread(str(frame["path"]))
        if image is None:
            output[segment_index] = []
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
                        "frame_timestamp": frame["timestamp"],
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
                    "frame_timestamp": frame["timestamp"],
                }
            )

        output[segment_index] = detections[:5]
    return output


def assemble_segments(
    segments: list[dict[str, Any]],
    frames: dict[int, dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    detections: dict[int, list[dict[str, Any]]],
    audio_metrics: dict[int, float],
    video: sqlite3.Row,
) -> list[dict[str, Any]]:
    previous_frame: dict[str, Any] | None = None
    previous_transcript = ""
    enriched = []
    metadata_text = " ".join([video["title"] or "", video["description"] or ""])

    for segment in segments:
        idx = segment["index"]
        transcript = transcript_for_segment(segment["start"], segment["end"], transcript_segments)
        objects = detections.get(idx, [])
        topics = classify_topics(" ".join([transcript, metadata_text, " ".join(obj["label"] for obj in objects)]))
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
        transcript_insights = analyze_transcript_segment(transcript, segment_duration, segment["start"], speech_density)
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
        ad_matches = score_ad_matches(objects, topics, metadata_text, attention, transcript, brand_safety_score, drop_risk)
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
                "thumbnail_url": media_url(frame["path"]) if frame else None,
                "objects": objects,
                "topics": topics,
                "ad_matches": ad_matches,
            }
        )
    return enriched


def normalize_transcript_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", "", value.lower())).strip()


def transcript_time(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transcript_for_segment(start: float, end: float, transcript_segments: list[dict[str, Any]]) -> str:
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
        seen.add(normalized)
        chunks.append(text)
    return " ".join(chunks)


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
    confidence = float(np.mean([obj["confidence"] for obj in objects]))
    size_bonus = 0.0
    if frame:
        height, width = frame["shape"][:2]
        frame_area = width * height
        ratios = []
        for obj in objects:
            x1, y1, x2, y2 = obj["bbox"]
            ratios.append(max(0.0, ((x2 - x1) * (y2 - y1)) / frame_area))
        size_bonus = min(0.25, float(np.mean(ratios)) * 2)
    return clamp(confidence * 0.75 + size_bonus)


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


def analyze_transcript_segment(transcript: str, duration: float, start: float, speech_density: float) -> dict[str, Any]:
    lowered = transcript.lower()
    words = re.findall(r"\b[a-zA-Z][a-zA-Z']+\b", lowered)
    filler_terms = ["um", "uh", "like", "basically", "actually", "literally"]
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
    object_labels = [obj["label"] for obj in objects[:5]]
    return {
        "sampled_frames": int(frame.get("sampled_frames", 0)) if frame else 0,
        "visual_novelty": round(visual_novelty, 3),
        "motion": round(motion, 3),
        "visual_quality": round(visual_quality, 3),
        "brightness": round(float(frame.get("brightness", 0.0)), 3) if frame else 0.0,
        "contrast": round(float(frame.get("contrast", 0.0)), 3) if frame else 0.0,
        "sharpness": round(float(frame.get("sharpness", 0.0)), 3) if frame else 0.0,
        "object_count": len(objects),
        "top_objects": object_labels,
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
    value = (
        visual_novelty * 0.16
        + motion * 0.12
        + object_clarity * 0.12
        + visual_quality * 0.10
        + scene_change * 0.10
        + speech_density * 0.12
        + hook_cta_signal * 0.10
        + audio_energy * 0.08
        + topic_clarity * 0.10
    )
    penalty = silence_penalty * 0.12 + repetition_penalty * 0.08 + blur_penalty * 0.08
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
    if score >= 80:
        return "High attention"
    if score >= 60:
        return "Good attention"
    if score >= 40:
        return "Neutral"
    if score >= 20:
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


def write_analysis(video_id: str, segments: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("delete from segments where video_id = ?", (video_id,))
        for segment in segments:
            segment_id = new_id("seg")
            conn.execute(
                """
                insert into segments
                (id, video_id, start_time, end_time, attention_score, ad_fit_score, drop_risk_score, brand_safety_score, label, summary, transcript, transcript_insights, visual_evidence, score_reasons, recommendation, recommendation_tier, recommendation_confidence, evidence_mode, strong_signals, failed_or_weak_signals, thumbnail_url, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    segment["thumbnail_url"],
                    utc_now(),
                ),
            )
            for obj in segment["objects"]:
                conn.execute(
                    """
                    insert into detected_objects
                    (id, segment_id, label, confidence, bbox, frame_timestamp, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("obj"),
                        segment_id,
                        obj["label"],
                        obj["confidence"],
                        json.dumps(obj.get("bbox")),
                        obj.get("frame_timestamp"),
                        utc_now(),
                    ),
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
        conn.commit()


def build_analysis_payload(video: sqlite3.Row) -> dict[str, Any]:
    segment_rows = query_all("select * from segments where video_id = ? order by start_time", (video["id"],))
    segments = []
    all_objects = []
    all_topics = []
    all_ad_matches = []
    for row in segment_rows:
        objects = [dict(item) for item in query_all("select * from detected_objects where segment_id = ?", (row["id"],))]
        topics = [dict(item) for item in query_all("select * from topics where segment_id = ?", (row["id"],))]
        matches = [dict(item) for item in query_all("select * from ad_matches where segment_id = ? order by ad_fit_score desc", (row["id"],))]
        for obj in objects:
            obj["bbox"] = json.loads(obj["bbox"]) if obj.get("bbox") else None
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
                "score_reasons": json.loads(row["score_reasons"]) if row["score_reasons"] else [],
                "recommendation": row["recommendation"],
                "recommendation_tier": row["recommendation_tier"] or "Edit before monetization",
                "recommendation_confidence": row["recommendation_confidence"] or 0,
                "evidence_mode": row["evidence_mode"] or "weak_evidence",
                "strong_signals": json.loads(row["strong_signals"]) if row["strong_signals"] else [],
                "failed_or_weak_signals": json.loads(row["failed_or_weak_signals"]) if row["failed_or_weak_signals"] else [],
                "thumbnail_url": row["thumbnail_url"],
                "objects": objects,
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
    return {
        "video": {
            "id": video["id"],
            "title": video["title"],
            "description": video["description"],
            "duration": video["duration_seconds"],
            "thumbnail": video["thumbnail_url"],
            "source_type": video["source_type"],
            "source_url": video["source_url"],
            "file_url": media_url(Path(video["file_path"])) if video["file_path"] else None,
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
        "exports": exports,
    }


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
    best_ad = max(strong_candidates, key=lambda segment: segment.get("recommendation_confidence", segment["ad_fit_score"])) if strong_candidates else None
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
