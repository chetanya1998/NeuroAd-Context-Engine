# NeuroAd Context Engine Deployment Guide

## Target Architecture

Use Netlify for the Next.js frontend and a separate container host for the FastAPI/video backend.

```text
Netlify
  apps/web Next.js app
  NEXT_PUBLIC_API_BASE=https://your-api-host
      |
      v
Render/Railway/Fly.io/VPS
  apps/api FastAPI service
  FFmpeg/FFprobe
  OpenCV, yt-dlp
  Optional Whisper and YOLO model dependencies
  persistent disk for SQLite, uploads, frames, audio, and reports
```

Do not put the Python analysis backend on Netlify Functions. This app needs system packages, large Python/model dependencies, local media writes, and long-running video jobs.

## Files Added For Deployment

- `netlify.toml`: Netlify build settings for the Next.js frontend.
- `.nvmrc`: Node 22 for local and hosted builds.
- `apps/api/Dockerfile`: containerized FastAPI backend with FFmpeg.
- `apps/api/.dockerignore`: keeps generated media/model files out of Docker builds.
- `render.yaml`: Render blueprint for the backend service and persistent disk.
- `apps/api/.env.example`: backend deployment variables.
- `apps/web/.env.example`: frontend deployment variables.

## Backend Deployment

The repo includes a Render blueprint because it is the fastest MVP path for a persistent Docker service.

### Render Blueprint

1. Push this repo to GitHub.
2. In Render, create a Blueprint from the repo.
3. Render will read `render.yaml`.
4. Set the prompted `CORS_ORIGINS` value after the Netlify site exists.

The blueprint creates:

- Docker web service named `neuroad-api`
- persistent disk mounted at `/data`
- health check path: `/health`
- storage path: `/data/neuroad/storage`
- SQLite path: `/data/neuroad/neuroad.db`

Default backend env:

```bash
NEUROAD_STORAGE_DIR=/data/neuroad/storage
NEUROAD_DB_PATH=/data/neuroad/neuroad.db
NEUROAD_WORKERS=1
NEUROAD_MAX_UPLOAD_MB=200
NEUROAD_MAX_SOURCE_SECONDS=600
NEUROAD_MAX_ANALYSIS_SECONDS=180
NEUROAD_MODEL_DIR=/opt/neuroad/models
NEUROAD_ENABLE_TRANSCRIPTION=1
NEUROAD_TRANSCRIPTION_ENGINE=vosk
NEUROAD_ENABLE_OBJECT_DETECTION=1
NEUROAD_OBJECT_DETECTION_ENGINE=mobilenet_ssd
VOSK_MODEL_DIR=/opt/neuroad/models/vosk-model-small-en-us-0.15
MOBILENET_SSD_GRAPH=/opt/neuroad/models/mobilenet-ssd/frozen_inference_graph.pb
MOBILENET_SSD_CONFIG=/opt/neuroad/models/mobilenet-ssd/ssd_mobilenet_v1_coco.pbtxt
WHISPER_MODEL=tiny
YOLO_MODEL=yolov8n.pt
```

Docker now installs the lightweight Vosk speech model and OpenCV MobileNet-SSD object model by default. This keeps Whisper and YOLO out of the base image, avoiding the large PyTorch install while preserving transcript and object-detection functionality. If a model is missing, the app falls back unless the matching `NEUROAD_REQUIRE_*` variable is set to `1`.

Set CORS after Netlify deploys:

```bash
CORS_ORIGINS=https://your-netlify-site.netlify.app,http://localhost:3000,http://127.0.0.1:3000
```

Optional YouTube settings:

```bash
YOUTUBE_API_KEY=...
YTDLP_COOKIES_FILE=/data/neuroad/cookies.txt
```

### Manual Docker Backend

If not using Render:

```bash
docker build -t neuroad-api ./apps/api
docker run --rm -p 8000:8000 \
  -e CORS_ORIGINS=http://localhost:3000 \
  -e NEUROAD_STORAGE_DIR=/data/neuroad/storage \
  -e NEUROAD_DB_PATH=/data/neuroad/neuroad.db \
  -v neuroad-data:/data \
  neuroad-api
```

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/system/dependencies
```

### Local Docker Compose

For local container testing, run the full API plus web stack:

```bash
npm run docker:up
```

This uses `docker-compose.yml`, exposes the web app on `http://localhost:3000`, exposes the API on `http://localhost:8000`, and stores API data in the `neuroad-api-data` named volume.

Vosk and MobileNet-SSD are enabled by default:

```bash
docker compose build api --no-cache
docker compose up
```

To opt back into Whisper transcription in Docker:

```bash
docker compose build api --build-arg INSTALL_WHISPER=1
NEUROAD_ENABLE_TRANSCRIPTION=1 docker compose up
```

To opt back into YOLO object detection in Docker:

```bash
docker compose build api --build-arg INSTALL_YOLO=1
NEUROAD_ENABLE_OBJECT_DETECTION=1 docker compose up
```

## Netlify Frontend Deployment

Netlify uses the root `netlify.toml`.

Build settings:

```text
Base directory: repository root
Build command: npm --workspace apps/web run build
Publish directory: apps/web/.next
```

Environment variables:

```bash
NEXT_PUBLIC_API_BASE=https://your-api-host
NETLIFY_NEXT_SKEW_PROTECTION=true
NODE_VERSION=22
```

After the API deploys, set `NEXT_PUBLIC_API_BASE` to the backend HTTPS URL, then trigger a Netlify redeploy.

## Deployment Order

1. Push the deployment files to GitHub.
2. Deploy the API with Render Blueprint or another Docker host.
3. Confirm `https://your-api-host/health` returns `ready: true`.
4. Create the Netlify site from the same repo.
5. Set `NEXT_PUBLIC_API_BASE` in Netlify.
6. Deploy the frontend.
7. Copy the Netlify URL into backend `CORS_ORIGINS`.
8. Restart/redeploy the backend.
9. Run the smoke test checklist.

## Smoke Test Checklist

- Netlify app opens.
- API health endpoint responds.
- `/api/system/dependencies` shows FFmpeg and FFprobe available.
- Upload a short MP4 under 200 MB.
- Processing page progresses through job steps.
- Dashboard renders the trend graph and segment data.
- CSV export downloads.
- JSON export downloads.
- Direct MP4 URL analysis works.
- YouTube ingestion either works or shows a clear permission/403 fallback.

## MVP Limits

- Upload limit defaults to 200 MB.
- Source duration limit defaults to 10 minutes in the Docker deployment.
- Analysis is capped to the first 3 minutes by default.
- Jobs run in-process with one worker.
- SQLite and local file storage are acceptable for a controlled demo, not multi-instance production.

## Production Upgrade Path

For a public product:

- Move SQLite to PostgreSQL.
- Move media and reports to Cloudflare R2, S3, or Supabase Storage.
- Add Redis and a separate Python worker process.
- Add retries, cleanup, and retention jobs.
- Add auth, workspaces, rate limiting, and upload scanning.
- Use GPU-backed workers for longer videos or faster turnaround.

Recommended production architecture:

```text
Netlify Web
  -> FastAPI API Service
  -> PostgreSQL
  -> Redis Queue
  -> Python Worker
  -> S3/R2 Storage
```
