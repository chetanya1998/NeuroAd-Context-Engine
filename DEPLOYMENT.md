# NeuroAd Context Engine Deployment Guide

## Target Architecture

Use Netlify for the Next.js frontend and Railway for the FastAPI/video backend.

```text
Netlify
  apps/web Next.js app
  NEXT_PUBLIC_API_BASE=https://your-api-host
      |
      v
Railway
  apps/api FastAPI service
  FFmpeg/FFprobe
  Vosk, OpenCV MobileNet-SSD, yt-dlp
  volume mounted at /data for SQLite, uploads, frames, audio, and reports
```

Do not put the Python analysis backend on Netlify Functions. This app needs system packages, large Python/model dependencies, local media writes, and long-running video jobs.

## Files Added For Deployment

- `netlify.toml`: Netlify build settings for the Next.js frontend.
- `.nvmrc`: Node 22 for local and hosted builds.
- `apps/api/Dockerfile`: containerized FastAPI backend with FFmpeg.
- `apps/api/.dockerignore`: keeps generated media/model files out of Docker builds.
- `apps/api/railway.toml`: Railway backend deploy config.
- `RAILWAY_DEPLOYMENT.md`: step-by-step Railway + Netlify deployment guide.
- `apps/api/.env.example`: backend deployment variables.
- `apps/web/.env.example`: frontend deployment variables.

## Backend Deployment

Railway is the recommended backend host for the current MVP. Follow:

[RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md)

Key Railway settings:

```text
Git branch: V1.0
Service source/root directory: apps/api
Builder: Dockerfile
Dockerfile: apps/api/Dockerfile
Health check path: /health
Volume mount path: /data
```

The source/root directory matters because Railway looks for a `Dockerfile` at the root of the service source directory.

Recommended Railway resources for this MVP:

```text
Hobby plan
1 backend service
1 volume mounted at /data
Short videos only
```

### Railway Backend Variables

Set these on the Railway backend service:

```text
PORT=8000
NEUROAD_STORAGE_DIR=/data/neuroad/storage
NEUROAD_DB_PATH=/data/neuroad/neuroad.db
NEUROAD_WORKERS=1
NEUROAD_MAX_UPLOAD_MB=200
NEUROAD_MAX_SOURCE_SECONDS=600
NEUROAD_MAX_ANALYSIS_SECONDS=180
NEUROAD_MODEL_DIR=/opt/neuroad/models
NEUROAD_ENABLE_AUDIO_CLEANUP=0
NEUROAD_AUDIO_CLEANUP_ENGINE=uvr
NEUROAD_ENABLE_VAD=0
NEUROAD_ENABLE_TRANSCRIPTION=1
NEUROAD_TRANSCRIPTION_ENGINE=vosk
NEUROAD_ENABLE_OBJECT_DETECTION=1
NEUROAD_OBJECT_DETECTION_ENGINE=yolo
VOSK_MODEL_DIR=/opt/neuroad/models/vosk-model-small-en-us-0.15
MOBILENET_SSD_GRAPH=/opt/neuroad/models/mobilenet-ssd/frozen_inference_graph.pb
MOBILENET_SSD_CONFIG=/opt/neuroad/models/mobilenet-ssd/ssd_mobilenet_v1_coco.pbtxt
WHISPER_MODEL=tiny
YOLO_MODEL=yolov8n.pt
```

Docker now installs the lightweight Vosk speech model and OpenCV MobileNet-SSD object model by default. The object engine is configured to try YOLO Tiny first when `INSTALL_YOLO=1` is used, then fall back to MobileNet/OpenCV if Ultralytics is unavailable. Whisper, YOLO, and UVR are kept out of the base image by default to avoid large PyTorch/model installs. If a model is missing, the app falls back unless the matching `NEUROAD_REQUIRE_*` variable is set to `1`.

Set CORS after Netlify deploys:

```bash
CORS_ORIGINS=https://your-netlify-site.netlify.app,http://localhost:3000,http://127.0.0.1:3000
```

Optional YouTube settings:

```bash
YOUTUBE_API_KEY=...
YTDLP_COOKIES_FILE=/data/neuroad/cookies.txt
```

Verify:

```bash
curl https://your-railway-domain.up.railway.app/health
curl https://your-railway-domain.up.railway.app/api/system/dependencies
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

To enable UVR-style audio cleanup, build the optional UVR dependency layer and enable cleanup explicitly:

```bash
docker compose build api --build-arg INSTALL_UVR=1
NEUROAD_ENABLE_AUDIO_CLEANUP=1 NEUROAD_AUDIO_CLEANUP_ENGINE=uvr docker compose up
```

For a lighter ASR cleanup pass without UVR, enable the built-in energy VAD:

```bash
NEUROAD_ENABLE_VAD=1 docker compose up
```

## Netlify Frontend Deployment

Netlify uses the root `netlify.toml`.

Build settings:

```text
Git branch: V1.0
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
2. Create the Railway backend from `apps/api`.
3. Add a Railway volume mounted at `/data`.
4. Confirm `https://your-railway-domain.up.railway.app/health` returns `ready: true`.
5. Create the Netlify site from the same repo.
6. Set `NEXT_PUBLIC_API_BASE=https://your-railway-domain.up.railway.app` in Netlify.
7. Deploy the frontend.
8. Copy the Netlify URL into Railway `CORS_ORIGINS`.
9. Restart/redeploy the Railway backend.
10. Run the smoke test checklist.

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
