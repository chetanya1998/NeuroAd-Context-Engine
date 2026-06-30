from __future__ import annotations

import csv
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
VOSK_MODEL_CACHE: Any | None = None
MOBILENET_SSD_NET_CACHE: Any | None = None

PROCESSING_STEPS = [
    ("metadata", "Metadata fetched"),
    ("frames", "Frames extracted"),
    ("audio", "Audio extracted"),
    ("transcript", "Transcript processed"),
    ("objects", "Object detection complete"),
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
    "luxury": ["luxury", "watch", "premium", "designer", "brand"],
    "automobiles": ["car", "vehicle", "drive", "engine", "auto"],
}

AD_CATALOG = [
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
    yt_dlp_available = importlib.util.find_spec("yt_dlp") is not None
    vosk_available = importlib.util.find_spec("vosk") is not None
    ultralytics_available = importlib.util.find_spec("ultralytics") is not None
    return {
        "ffmpeg": {"available": bool(ffmpeg_path), "path": ffmpeg_path},
        "ffprobe": {"available": bool(ffprobe_path), "path": ffprobe_path},
        "yt_dlp": {"available": yt_dlp_available, "path": None},
        "vosk": {"available": vosk_available, "model_path": str(VOSK_MODEL_DIR), "model_ready": VOSK_MODEL_DIR.exists()},
        "mobilenet_ssd": {
            "available": MOBILENET_SSD_GRAPH.exists() and MOBILENET_SSD_CONFIG.exists(),
            "graph_path": str(MOBILENET_SSD_GRAPH),
            "config_path": str(MOBILENET_SSD_CONFIG),
        },
        "ultralytics": {"available": ultralytics_available, "path": None},
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
              label text not null,
              summary text not null,
              transcript text,
              recommendation text,
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
        conn.commit()


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
    options = ytdlp_base_options(video_id)
    options["http_headers"]["Referer"] = "https://www.youtube.com/"
    
    # If using browser cookies, avoid iOS/Android clients because desktop cookies
    # combined with mobile clients immediately trigger a 403 bot detection ban.
    if "cookiefile" in options or "cookiesfrombrowser" in options:
        options["extractor_args"] = {"youtube": {"player_client": ["web_safari", "web", "web_creator"]}}
    else:
        options["extractor_args"] = {"youtube": {"player_client": ["ios", "android", "web_safari", "web"]}}

    before = set(UPLOAD_DIR.glob(f"{video_id}.*"))
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except Exception as exc:
        for path in UPLOAD_DIR.glob(f"{video_id}.*"):
            path.unlink(missing_ok=True)
        message = str(exc)
        if "403" in message or "Forbidden" in message or "Sign in to confirm" in message:
            detail = (
                "YouTube blocked the video stream with HTTP 403. Try a video you own that is public/unlisted, "
                "or export cookies from your browser using an extension like 'Get cookies.txt' and save them "
                "to 'cookies.txt' in the storage directory, or configure YTDLP_COOKIES_BROWSER=chrome. "
                "You can also upload the video file directly."
            )
        else:
            detail = f"Could not ingest this YouTube URL: {message}"
        raise HTTPException(status_code=400, detail=detail) from exc

    target = find_downloaded_media(video_id, before)

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
    return {
        "ready": bool(ffmpeg_available and ffprobe_available),
        "youtube_ingest_ready": bool(ffmpeg_available and ffprobe_available and yt_dlp_available),
        "youtube_cookies_configured": bool(os.getenv("YTDLP_COOKIES_FILE") or os.getenv("YTDLP_COOKIES_BROWSER")),
        "dependencies": dependencies,
    }


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
        audio_metrics = compute_audio_metrics(audio_path, segments)
        update_job(job_id, "processing", 32, "audio")

        transcript_segments = transcribe_audio(audio_path)
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
        update_job(job_id, "failed", 100, "failed", str(exc))


def is_youtube_media_blocked(exc: Exception) -> bool:
    message = str(exc).lower()
    blocked_markers = [
        "sign in to confirm",
        "not a bot",
        "captcha",
        "cookies",
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

    for segment in segments:
        timestamp = (segment["start"] + segment["end"]) / 2
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        frame_path = output_dir / f"frame_{segment['index']:03d}.jpg"
        cv2.imwrite(str(frame_path), frame)
        grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_data[segment["index"]] = {
            "path": frame_path,
            "timestamp": timestamp,
            "mean": float(np.mean(grayscale)),
            "std": float(np.std(grayscale)),
            "shape": frame.shape,
        }
    cap.release()
    return frame_data


def extract_audio(video_id: str, source: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for audio extraction. Install it with `brew install ffmpeg`.")
    target = AUDIO_DIR / f"{video_id}.wav"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(target)],
        capture_output=True,
        text=True,
        check=True,
    )
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
            return detect_mobilenet_ssd_objects(frames)
        if engine != "yolo":
            return detect_lightweight_visual_context(frames)
        return detect_yolo_objects(frames)
    except Exception:
        if object_detection_required():
            raise
        return detect_lightweight_visual_context(frames)


def object_detection_required() -> bool:
    return os.getenv("NEUROAD_REQUIRE_OBJECT_DETECTION", "0").lower() in {"1", "true", "yes", "on"}


def detect_yolo_objects(frames: dict[int, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        if object_detection_required():
            raise RuntimeError("ultralytics is required for YOLO object detection.") from exc
        return detect_lightweight_visual_context(frames)
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
    previous_mean: float | None = None
    enriched = []
    metadata_text = " ".join([video["title"] or "", video["description"] or ""])

    for segment in segments:
        idx = segment["index"]
        transcript = transcript_for_segment(segment["start"], segment["end"], transcript_segments)
        objects = detections.get(idx, [])
        topics = classify_topics(" ".join([transcript, metadata_text, " ".join(obj["label"] for obj in objects)]))
        frame = frames.get(idx)
        visual_novelty = 0.3
        scene_change = 0.3
        if frame and previous_mean is not None:
            visual_novelty = clamp(abs(frame["mean"] - previous_mean) / 70)
            scene_change = visual_novelty
        if frame:
            previous_mean = frame["mean"]
        object_clarity = compute_object_clarity(objects, frame)
        audio_energy = audio_metrics.get(idx, 0.0)
        speech_density = compute_speech_density(transcript, segment["end"] - segment["start"])
        topic_clarity = max([topic["confidence"] for topic in topics], default=0.2)
        hook_cta_signal = compute_hook_cta_signal(transcript, segment["start"])
        attention = score_attention(
            visual_novelty,
            object_clarity,
            audio_energy,
            speech_density,
            scene_change,
            topic_clarity,
            hook_cta_signal,
        )
        ad_matches = score_ad_matches(objects, topics, metadata_text, attention)
        ad_fit = max([match["ad_fit_score"] for match in ad_matches], default=0)
        label = attention_label(attention)
        enriched.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "attention_score": attention,
                "ad_fit_score": ad_fit,
                "label": label,
                "summary": build_segment_summary(attention, objects, topics, audio_energy),
                "transcript": transcript,
                "recommendation": build_recommendation(segment["start"], attention, ad_fit, objects, topics),
                "thumbnail_url": media_url(frame["path"]) if frame else None,
                "objects": objects,
                "topics": topics,
                "ad_matches": ad_matches,
            }
        )
    return enriched


def transcript_for_segment(start: float, end: float, transcript_segments: list[dict[str, Any]]) -> str:
    chunks = [
        item.get("text", "").strip()
        for item in transcript_segments
        if float(item.get("end", 0)) >= start and float(item.get("start", 0)) <= end
    ]
    return " ".join(chunk for chunk in chunks if chunk)


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
    terms = ["today", "show", "learn", "try", "click", "subscribe", "buy", "save", "before", "after"]
    hits = sum(1 for term in terms if term in transcript.lower())
    intro_bonus = 0.25 if start < 10 else 0
    return clamp(intro_bonus + hits * 0.18)


def score_attention(
    visual_novelty: float,
    object_clarity: float,
    audio_energy: float,
    speech_density: float,
    scene_change: float,
    topic_clarity: float,
    hook_cta_signal: float,
) -> int:
    value = (
        visual_novelty * 0.25
        + object_clarity * 0.20
        + audio_energy * 0.15
        + speech_density * 0.15
        + scene_change * 0.10
        + topic_clarity * 0.10
        + hook_cta_signal * 0.05
    )
    return int(round(clamp(value) * 100))


def score_ad_matches(
    objects: list[dict[str, Any]], topics: list[dict[str, Any]], metadata_text: str, attention_score: int
) -> list[dict[str, Any]]:
    object_labels = {obj["label"].lower() for obj in objects}
    topic_labels = {topic["label"].lower() for topic in topics}
    metadata = metadata_text.lower()
    matches = []
    for item in AD_CATALOG:
        object_match = len(object_labels.intersection(set(item["objects"]))) / max(1, len(item["objects"]))
        transcript_match = len(topic_labels.intersection(set(item["keywords"]))) / max(1, min(3, len(item["keywords"])))
        keyword_match = sum(1 for keyword in item["keywords"] if keyword in metadata) / max(1, len(item["keywords"]))
        brand_safety = 0.9
        score = (
            object_match * 0.35
            + transcript_match * 0.30
            + keyword_match * 0.15
            + (attention_score / 100) * 0.10
            + brand_safety * 0.10
        )
        if score > 0.16:
            reason_bits = []
            if object_match:
                reason_bits.append("visible objects match")
            if transcript_match or keyword_match:
                reason_bits.append("topic/context aligns")
            if attention_score >= 70:
                reason_bits.append("attention proxy is strong")
            matches.append(
                {
                    "category": item["category"],
                    "ad_fit_score": int(round(clamp(score) * 100)),
                    "reason": ", ".join(reason_bits) or "baseline contextual fit",
                    "confidence": int(round(min(0.95, 0.45 + score * 0.5) * 100)),
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
    start: float, attention: int, ad_fit: int, objects: list[dict[str, Any]], topics: list[dict[str, Any]]
) -> str:
    timestamp = format_time(start)
    if ad_fit >= 75:
        category_hint = topics[0]["label"] if topics else "context"
        return f"{timestamp} is a strong contextual ad moment because the scene and {category_hint} topic align."
    if attention < 40:
        return f"{timestamp} may be a cut or rewrite zone; add clearer visual change, a stronger spoken promise, or a product cue."
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
                (id, video_id, start_time, end_time, attention_score, ad_fit_score, label, summary, transcript, recommendation, thumbnail_url, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    video_id,
                    segment["start"],
                    segment["end"],
                    segment["attention_score"],
                    segment["ad_fit_score"],
                    segment["label"],
                    segment["summary"],
                    segment["transcript"],
                    segment["recommendation"],
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
                "label": row["label"],
                "summary": row["summary"],
                "transcript": row["transcript"],
                "recommendation": row["recommendation"],
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
        "recommendations": build_recommendations(summary, segments),
        "exports": exports,
    }


def summarize(video: sqlite3.Row, segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return {
            "overall_attention_score": 0,
            "monetization_opportunity_score": 0,
            "best_hook": None,
            "best_ad_slot": None,
            "weakest_segment": None,
            "top_ad_category": None,
        }
    overall = int(round(float(np.mean([segment["attention_score"] for segment in segments]))))
    monetization = int(round(float(np.mean([segment["ad_fit_score"] for segment in segments]))))
    hook_pool = [segment for segment in segments if segment["start"] < 15] or segments[:3]
    best_hook = max(hook_pool, key=lambda segment: segment["attention_score"])
    best_ad = max(segments, key=lambda segment: segment["ad_fit_score"])
    weakest = min(segments, key=lambda segment: segment["attention_score"])
    category_counts: dict[str, int] = {}
    for segment in segments:
        for match in segment["ad_matches"]:
            category_counts[match["ad_category"]] = category_counts.get(match["ad_category"], 0) + 1
    top_category = max(category_counts, key=category_counts.get) if category_counts else "No strong ad match"
    return {
        "overall_attention_score": overall,
        "monetization_opportunity_score": monetization,
        "best_hook": compact_segment(best_hook),
        "best_ad_slot": {**compact_segment(best_ad), "category": best_ad["ad_matches"][0]["ad_category"] if best_ad["ad_matches"] else "No strong ad match"},
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
    }


def build_recommendations(summary: dict[str, Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []
    best_ad = summary["best_ad_slot"]
    weakest = summary["weakest_segment"]
    best_hook = summary["best_hook"]
    recommendations = [
        {
            "title": "Best hook moment",
            "timestamp": format_range(best_hook["start"], best_hook["end"]),
            "body": "Open with this pacing and clarity; it has the strongest early attention proxy signal.",
        },
        {
            "title": "Best ad placement",
            "timestamp": format_range(best_ad["start"], best_ad["end"]),
            "body": f"Test this slot for {best_ad.get('category', 'a contextual ad')} because attention and ad-fit both rank highly.",
        },
        {
            "title": "Avoid-ad zone",
            "timestamp": format_range(weakest["start"], weakest["end"]),
            "body": "Avoid inserting ads here; the moment already has weaker attention and may increase drop risk.",
        },
    ]
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
