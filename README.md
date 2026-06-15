# NeuroAd Context Engine

A local full-stack MVP for multimodal video intelligence: upload a short video or provide a direct video file URL, process it with AI models, then inspect attention proxy moments, object/context moments, transcript topics, ad-placement opportunities, and creator recommendations.

## Stack

- Frontend: Next.js, TypeScript, Tailwind, Recharts, Zustand, TanStack Query
- Backend: FastAPI, SQLite, local file storage, in-process background jobs
- AI pipeline: FFmpeg, OpenCV, Whisper, Ultralytics YOLO, sentence-transformers, pandas, numpy

## Local Setup

```bash
brew install ffmpeg

python3 -m venv apps/api/.venv
source apps/api/.venv/bin/activate
pip install -r apps/api/requirements.txt

npm install
```

Run both services:

```bash
npm run dev:api
npm run dev:web
```

Open `http://localhost:3000`.

## Notes

- Direct `.mp4`, `.mov`, `.webm`, and `.m4v` URLs are downloaded and analyzed through the real pipeline.
- YouTube URLs can be ingested with `yt-dlp` only after the user confirms they own or have permission to analyze the video.
- If YouTube returns HTTP 403, restart the API with browser cookies enabled, for example `YTDLP_COOKIES_BROWSER=chrome npm run dev:api`, or use `YTDLP_COOKIES_FILE=/path/to/cookies.txt`.
- Uploaded videos are analyzed locally and privately under `apps/api/storage`.
- Scores are labeled as `Attention Proxy Score`; this app does not claim to read or predict actual brain activity.
- TRIBE v2 is represented only as a future research-mode placeholder.
