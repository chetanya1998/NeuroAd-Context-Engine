# NeuroAd Context Engine Deployment Strategy

## Recommended MVP Deployment

Use a split deployment:

- Frontend: Vercel
- Backend/API: Render, Railway, Fly.io, or a small VPS
- Storage: backend persistent disk for MVP
- Database: SQLite on persistent disk for MVP, PostgreSQL for public demos
- Video processing: backend worker process in the FastAPI service for MVP

This is the lowest-friction path because the current app is already structured as:

- `apps/web`: Next.js frontend
- `apps/api`: FastAPI backend
- `apps/api/storage`: local uploads, frames, audio, reports, and SQLite data

## Codex Sites Plugin Strategy

The Codex Sites plugin is not available in the current Codex session, and it was not listed as an installable plugin candidate.

Even if Codex Sites becomes available, use it only for a static preview or marketing/demo shell, not for the full NeuroAd AI MVP. This product needs a backend that can run FFmpeg, Whisper, YOLO, OpenCV, sentence-transformers, yt-dlp, local file writes, and long-running video jobs.

Recommended use of Codex Sites, if available later:

- Host a static public landing/demo page.
- Show screenshots, product positioning, and a link to the real app.
- Embed a precomputed sample report or exported JSON visualization.
- Link out to the deployed Next.js app.

Do not use Codex Sites for:

- Uploaded-video analysis
- YouTube ingestion
- FFmpeg processing
- Whisper transcription
- YOLO object detection
- SQLite/local file persistence
- Background jobs

Best strategy with Sites:

```text
Codex Sites:
  Static landing/demo page
  -> CTA links to hosted app

Vercel:
  Next.js dashboard app
  -> calls API

Render/Railway/Fly/VPS:
  FastAPI + AI processing
  -> persistent disk or object storage
```

## Why Not Vercel-Only

Vercel is good for the Next.js frontend, but not for the AI/video backend because this app needs:

- FFmpeg and FFprobe
- long-running video jobs
- local file writes
- Python model dependencies
- Whisper, YOLO, OpenCV, sentence-transformers
- yt-dlp for permitted YouTube ingestion

Those are better hosted in a persistent Python service or container.

## Phase 1: Demo Deployment

### 1. Deploy the FastAPI backend

Use Render/Railway/Fly.io with a Dockerized API service.

Backend requirements:

- Python 3.10 or 3.11
- FFmpeg/FFprobe installed at system level
- `apps/api/requirements.txt`
- persistent disk mounted to `apps/api/storage`
- public HTTPS URL, for example `https://neuroad-api.onrender.com`

Backend start command:

```bash
cd apps/api
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Important environment variables:

```bash
CORS_ORIGINS=https://your-vercel-domain.vercel.app
YTDLP_COOKIES_FILE=/path/to/cookies.txt
YTDLP_COOKIES_BROWSER=chrome
```

For production, prefer `YTDLP_COOKIES_FILE` if YouTube ingestion is required. Some YouTube streams may still block cloud datacenter IPs, so upload/direct MP4 should remain the reliable path.

### 2. Deploy the Next.js frontend

Deploy `apps/web` to Vercel.

Vercel settings:

```bash
Root Directory: apps/web
Build Command: npm run build
Output: .next
```

Environment variable:

```bash
NEXT_PUBLIC_API_BASE=https://your-api-domain.com
```

### 3. Update backend CORS

Make sure the backend allows the Vercel frontend origin.

Recommended CORS values:

```bash
https://your-vercel-domain.vercel.app
http://localhost:3000
```

## Phase 2: Stable Public Demo

Move beyond local MVP storage:

- Replace SQLite with PostgreSQL
- Replace local file storage with Cloudflare R2, AWS S3, or Supabase Storage
- Add Redis queue for processing jobs
- Run video processing in a separate worker
- Keep FastAPI only for API requests and job orchestration

Recommended architecture:

```text
Vercel Web
  -> FastAPI API Service
  -> PostgreSQL
  -> Redis Queue
  -> Python Worker
  -> S3/R2 Storage
```

This prevents one long Whisper/YOLO job from blocking the API service.

## Phase 3: Production-Grade AI Processing

For faster and more reliable analysis:

- Run workers on GPU-backed infrastructure
- Use Modal, RunPod, Replicate, Lambda Labs, or a GPU VPS
- Cache model weights during build or worker startup
- Store extracted frames/audio in object storage
- Add job retries and failure step visibility

Recommended model execution plan:

- CPU demo: short videos only, first 3 minutes capped
- GPU demo: 5-10 minute videos
- Production: queue-based GPU workers with concurrency limits

## Deployment Blockers To Fix Before Public Launch

### Must fix

- Move SQLite path into a configurable env var.
- Move storage directory into a configurable env var.
- Add upload cleanup/retention policy.
- Add max duration checks before full processing.
- Add request limits and basic abuse protection.
- Add CORS env configuration if not already configurable.

### Should fix

- Add Dockerfile for `apps/api`.
- Add health endpoint, for example `GET /health`.
- Add persistent report links.
- Add structured logging for job steps.
- Add PostgreSQL migration path.

### Nice to have

- Auth/workspaces
- Signed upload URLs
- Cloud storage
- Separate worker service
- GPU worker option

## Suggested First Deployment Target

For the fastest credible demo:

1. Deploy API on Render with Docker and persistent disk.
2. Deploy frontend on Vercel.
3. Use direct upload and direct MP4 URL as the reliable demo path.
4. Keep YouTube ingestion as beta because YouTube may return 403 from cloud IPs.
5. Add PostgreSQL/R2 only after the public demo works end-to-end.

## Demo Readiness Checklist

- Frontend opens from Vercel.
- API health endpoint responds.
- Upload a short MP4 under 200 MB.
- Processing page shows step progress.
- Dashboard renders trend graph and report sections.
- CSV export downloads.
- JSON export downloads.
- Direct MP4 URL analysis works.
- YouTube ingestion either works or shows a clear permission/403 fallback message.
