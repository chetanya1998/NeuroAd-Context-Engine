# NeuroAd Context Engine

NeuroAd Context Engine is a full-stack AI MVP for moment-level video intelligence. It lets a user upload a short video, paste a direct video file URL, or ingest a permitted YouTube URL, then generates a dashboard with attention proxy scoring, object/context moments, transcript topics, ad-fit recommendations, creator insights, and exportable CSV/JSON reports.

The product is intentionally positioned as an **Attention Proxy Score** system. It does not claim to read minds, predict guaranteed human attention, or perform actual TRIBE v2 brain-response inference. TRIBE-style brain-response research is represented only as a future research-mode placeholder.

## Product Summary

The app answers a practical creator/adtech question:

> Which exact moments inside a video are strongest, weakest, or best suited for contextual ad placement?

It analyzes video at the segment level using:

- Frame sampling
- Audio energy
- Speech-to-text
- Object detection
- Topic classification
- Attention proxy scoring
- Contextual ad matching
- Plain-English recommendations

## Current MVP Status

This repository contains a working local MVP:

- Next.js dashboard frontend
- FastAPI backend
- SQLite persistence
- Local file storage
- In-process background jobs
- Real uploaded-video analysis
- Real direct-video-URL analysis
- Permitted YouTube ingestion through `yt-dlp`
- CSV and JSON exports
- Dark pitch-black UI
- Dashboard trend graph with annotated high/low/ad-fit moments

Sample/mock analysis is disabled in the current build. Completed dashboards should come from real uploaded media, permitted YouTube ingestion, or direct video file URLs.

## Repository Structure

```text
.
├── apps
│   ├── api
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   ├── tests
│   │   │   └── test_scoring.py
│   │   └── storage
│   │       ├── audio
│   │       ├── frames
│   │       ├── reports
│   │       ├── samples
│   │       └── uploads
│   └── web
│       ├── src
│       │   ├── app
│       │   ├── components
│       │   └── lib
│       ├── package.json
│       └── tailwind.config.ts
├── DEPLOYMENT.md
├── package.json
├── package-lock.json
└── README.md
```

## Tech Stack

### Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- Recharts
- TanStack Query
- Zustand
- Lucide React icons

### Backend

- FastAPI
- SQLite
- Local file storage
- In-process background jobs with `ThreadPoolExecutor`
- Static media serving through FastAPI

### AI/Video Pipeline

- FFmpeg and FFprobe
- OpenCV
- OpenAI Whisper open-source package
- Ultralytics YOLO
- sentence-transformers
- NumPy
- pandas
- yt-dlp for permitted YouTube media ingestion

## Key Features

### Landing/Input Page

Route:

```text
/
```

The landing page includes:

- Product name: `NeuroAd Context Engine`
- Paste video URL input
- YouTube permission checkbox
- Upload video section
- Pitch-black dashboard aesthetic
- Live output preview visualization
- Concept explainer cards

Supported input types:

- Uploaded MP4/MOV/WebM/M4V
- Direct public video file URLs ending in `.mp4`, `.mov`, `.webm`, or `.m4v`
- YouTube URLs only when the user confirms they own or have permission to analyze the video

### Processing Page

Route:

```text
/analyze/[videoId]
```

The processing page starts the analysis job and polls job status.

Visible processing steps:

```text
metadata
frames
audio
transcript
objects
topics
attention
ad_scoring
report
```

When the job completes, the frontend automatically routes to:

```text
/dashboard/[videoId]
```

### Dashboard Page

Route:

```text
/dashboard/[videoId]
```

Dashboard sections:

- Header with export buttons
- Overall video trend graph
- Summary metric cards
- Attention timeline
- Segment drawer
- Segments tab
- Objects tab
- Transcript tab
- Ad Matches tab
- Recommendations tab

The top dashboard chart shows:

- Full Attention Proxy Score trend
- Dashed Ad Fit trend
- Annotated peak attention point
- Annotated lowest attention point
- Annotated best ad-fit point

### Report Page

Route:

```text
/reports/[reportId]
```

The current report page is a read-only report route scaffold that fetches analysis data using the report/video id.

### Exports

The completed dashboard supports:

- CSV export
- JSON export

Exports are generated from real segment data after processing is complete.

## Backend API

Base URL locally:

```text
http://localhost:8000
```

### Upload Video

```http
POST /api/videos/upload
```

Request:

```multipart
file: video.mp4
```

Response:

```json
{
  "video_id": "video_123",
  "status": "uploaded"
}
```

### Create Direct URL Video

```http
POST /api/videos/url
```

Request:

```json
{
  "url": "https://example.com/video.mp4"
}
```

This registers the URL quickly. The actual download happens inside the processing job so the user sees the progress screen.

### Fetch YouTube Metadata

```http
POST /api/videos/youtube
```

Request:

```json
{
  "url": "https://www.youtube.com/watch?v=..."
}
```

This endpoint creates a metadata-only YouTube record and embed preview.

### Ingest Permitted YouTube URL

```http
POST /api/videos/youtube/ingest
```

Request:

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "has_permission": true
}
```

This registers a YouTube ingestion job. The actual media download happens during analysis with `yt-dlp`.

Important: YouTube can return HTTP 403 from some cloud or local environments. If that happens, upload the video file directly or configure cookies.

### Start Analysis

```http
POST /api/videos/{video_id}/analyze
```

Response:

```json
{
  "job_id": "job_123",
  "status": "queued"
}
```

### Get Job Status

```http
GET /api/jobs/{job_id}
```

Response:

```json
{
  "id": "job_123",
  "video_id": "video_123",
  "status": "processing",
  "progress": 62,
  "current_step": "objects",
  "error": null
}
```

### Check Runtime Dependencies

```http
GET /api/system/dependencies
```

Response includes:

- FFmpeg availability
- FFprobe availability
- yt-dlp availability
- YouTube cookie configuration status

### Fetch Analysis

```http
GET /api/videos/{video_id}/analysis
```

Returns the full dashboard payload:

```json
{
  "video": {},
  "summary": {},
  "segments": [],
  "objects": [],
  "topics": [],
  "ad_matches": [],
  "recommendations": [],
  "exports": {}
}
```

### Export Analysis

```http
GET /api/videos/{video_id}/export?format=csv
GET /api/videos/{video_id}/export?format=json
```

Exports are only available after the video status is `completed`.

## Analysis Pipeline

The current backend pipeline lives in:

```text
apps/api/main.py
```

High-level flow:

```text
Input media
  -> validate source
  -> download/register source if needed
  -> probe duration with FFprobe
  -> segment video
  -> sample frames with OpenCV
  -> extract audio with FFmpeg
  -> transcribe audio with Whisper
  -> detect objects with YOLO
  -> classify topics
  -> compute Attention Proxy Score
  -> compute Ad Fit Score
  -> write SQLite rows
  -> generate CSV/JSON exports
  -> dashboard payload
```

### Segmentation Rules

- Videos under 60 seconds use 2-second segments.
- Longer videos use 5-second segments.
- MVP analysis is capped to the first 3 minutes.

### Object Detection

YOLO detections are sampled from extracted frames. The app keeps the highest-confidence objects per segment.

### Transcript

Whisper is used for timestamped speech-to-text. If Whisper or audio processing fails in a constrained environment, the job returns a clear failed step and error message.

### Topic Classification

The app currently uses keyword/category fallback logic around these categories:

- fitness
- finance
- beauty
- skincare
- gaming
- education
- productivity
- startup
- travel
- food
- fashion
- entertainment
- parenting
- technology
- health
- luxury
- automobiles

### Attention Proxy Score

The score is bounded from 0 to 100 and combines:

- visual novelty
- object clarity
- audio energy
- speech density
- scene change
- topic clarity
- hook/CTA signal

Labels:

```text
80-100: High attention
60-79: Good attention
40-59: Neutral
20-39: Drop risk
0-19: Weak moment
```

### Ad Fit Score

The current contextual ad matcher uses:

- object/category overlap
- transcript/topic overlap
- metadata matching
- attention score
- brand-safety baseline

Current ad catalog categories include:

- Productivity SaaS
- AI Note-taking App
- Coffee Brand
- Fitness Product
- Creator Gear
- Fashion / Apparel

## Local Development

### Prerequisites

Install:

- Node.js 18 or newer
- npm
- Python 3.10 or 3.11 recommended
- FFmpeg and FFprobe

On macOS:

```bash
brew install ffmpeg
```

Check FFmpeg:

```bash
ffmpeg -version
ffprobe -version
```

### Install Dependencies

From the repository root:

```bash
npm install
```

Create and activate the Python environment:

```bash
python3 -m venv apps/api/.venv
source apps/api/.venv/bin/activate
pip install -r apps/api/requirements.txt
```

### Run Backend

From the repository root:

```bash
npm run dev:api
```

This runs:

```bash
cd apps/api && uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Run Frontend

In a second terminal:

```bash
npm run dev:web
```

Open:

```text
http://localhost:3000
```

### Production-style Local Run

Build the web app:

```bash
npm --workspace apps/web run build
```

Start it:

```bash
npm --workspace apps/web exec next start -- --hostname 127.0.0.1 --port 3000
```

Start the API:

```bash
cd apps/api
uvicorn main:app --host 127.0.0.1 --port 8000
```

## Environment Variables

### Frontend

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

If omitted, the frontend defaults to:

```text
http://localhost:8000
```

### Backend

```bash
NEUROAD_WORKERS=1
YTDLP_COOKIES_FILE=/absolute/path/to/cookies.txt
YTDLP_COOKIES_BROWSER=chrome
```

Notes:

- `NEUROAD_WORKERS` controls in-process job concurrency.
- Keep it low on CPU-only machines.
- `YTDLP_COOKIES_FILE` is preferred over browser-cookie extraction in deployed environments.

## Storage

Local storage lives under:

```text
apps/api/storage
```

Subdirectories:

```text
uploads/   uploaded/downloaded video files
frames/    extracted frame thumbnails
audio/     extracted audio files
reports/   generated CSV/JSON exports
samples/   reserved for sample fixtures
```

SQLite database:

```text
apps/api/storage/neuroad.db
```

The repository intentionally ignores generated media, reports, the SQLite database, virtual environments, model weights, and build outputs.

## Git Ignore Policy

Ignored examples:

- `node_modules/`
- `.next/`
- `.venv/`
- `apps/api/.venv/`
- generated uploaded videos
- generated frames
- generated audio
- generated reports
- SQLite database
- `.pt` model weights
- `.onnx` model weights
- `.env`
- `.env.local`

Only `.gitkeep` files inside storage folders are committed.

## Testing

### Backend Tests

```bash
apps/api/.venv/bin/pytest apps/api/tests
```

or, after activating the virtual environment:

```bash
npm run test:api
```

Current tests cover scoring behavior.

### Frontend Lint

```bash
npm run lint:web
```

### Frontend Build

```bash
npm run build:web
```

## Deployment Strategy

See the detailed deployment guide:

[DEPLOYMENT.md](./DEPLOYMENT.md)

Recommended MVP deployment:

```text
Vercel:
  Next.js frontend

Render/Railway/Fly.io/VPS:
  FastAPI backend
  FFmpeg/FFprobe
  Python AI dependencies
  persistent disk

Later:
  PostgreSQL
  Cloudflare R2/S3/Supabase Storage
  Redis queue
  separate Python worker
  optional GPU worker
```

Do not deploy this as a Vercel-only app. The backend needs long-running Python work, local file writes, and system-level video tooling.

## YouTube Ingestion Notes

YouTube ingestion is supported only when the user confirms they own or have permission to analyze the video.

The app uses `yt-dlp` for permitted media ingestion.

If a YouTube stream fails with HTTP 403:

1. Try a video you own that is public or unlisted.
2. Upload the video file directly.
3. Provide a direct MP4/MOV/WebM/M4V URL.
4. Configure cookies:

```bash
YTDLP_COOKIES_FILE=/absolute/path/to/cookies.txt npm run dev:api
```

or:

```bash
YTDLP_COOKIES_BROWSER=chrome npm run dev:api
```

Cloud hosting providers may still receive 403 responses from YouTube because of datacenter IP restrictions.

## Security and Privacy Notes

This is an MVP, not a production security model.

Current protections:

- Upload format validation
- 200 MB upload limit
- Analysis duration capped to first 3 minutes
- Local storage ignored from Git
- YouTube permission checkbox
- No training on uploaded videos

Before public launch, add:

- Authentication
- Rate limiting
- Signed upload URLs
- Virus/malware scanning for uploads
- User-owned private storage
- Delete video/report endpoint
- Storage retention policy
- CORS configuration through environment variables
- Job retry policies
- Audit logging

## Known Limitations

- SQLite is local and not suitable for multi-instance production.
- File storage is local and should move to object storage for public demos.
- Video jobs run in-process; a separate worker queue is better for production.
- CPU-only Whisper/YOLO processing can be slow.
- YouTube ingestion can fail with HTTP 403.
- No authentication yet.
- No payment or workspace management.
- No production brand-safety classifier.
- TRIBE v2 inference is not implemented.

## Troubleshooting

### Frontend cannot reach backend

Check:

```bash
NEXT_PUBLIC_API_BASE
```

Default expected API:

```text
http://localhost:8000
```

Make sure FastAPI is running:

```bash
curl http://localhost:8000/api/system/dependencies
```

### FFmpeg missing

Install FFmpeg:

```bash
brew install ffmpeg
```

Verify:

```bash
ffmpeg -version
ffprobe -version
```

### OpenCV/Whisper/YOLO import errors

Activate the API virtual environment and reinstall dependencies:

```bash
source apps/api/.venv/bin/activate
pip install -r apps/api/requirements.txt
```

### YouTube returns 403

Use direct upload as the reliable path, or configure cookies:

```bash
YTDLP_COOKIES_FILE=/absolute/path/to/cookies.txt npm run dev:api
```

### Dashboard says analysis is not complete

Check the job:

```bash
curl http://localhost:8000/api/jobs/{job_id}
```

If the job failed, the `error` field will show the failed step and message.

### Large files are rejected

The MVP limit is:

```text
200 MB
```

Use a shorter clip or compress the file.

## Development Workflow

Typical local workflow:

```bash
npm install

python3 -m venv apps/api/.venv
source apps/api/.venv/bin/activate
pip install -r apps/api/requirements.txt

npm run dev:api
npm run dev:web
```

Quality checks:

```bash
apps/api/.venv/bin/pytest apps/api/tests
npm run lint:web
npm run build:web
```

## Roadmap

### V1.0

- Local MVP
- Upload/direct URL/YouTube ingestion
- Real video analysis
- Dashboard trend graph
- CSV/JSON export
- Deployment strategy

### V1.1

- Dockerfile for API
- Health endpoint
- Configurable storage and database paths
- Configurable CORS origins
- Better report route and share links

### V2

- PostgreSQL
- S3/R2/Supabase Storage
- Redis queue
- Separate worker service
- GPU-backed processing option
- Auth and workspaces
- Multi-video creative comparison

### V3

- Brand-safety classifier
- Product catalog upload
- Creator/brand matching
- Optional TRIBE v2 research-mode integration
- Production-grade report sharing

## License and Model Notes

This repository is an MVP implementation for product/demo exploration.

Third-party libraries and models have their own licenses. Review licenses for:

- Whisper
- Ultralytics YOLO
- sentence-transformers
- yt-dlp
- FFmpeg

TRIBE v2 is referenced only as product inspiration and future research-mode framing. Do not present this MVP as actual brain-reading or guaranteed attention prediction.

