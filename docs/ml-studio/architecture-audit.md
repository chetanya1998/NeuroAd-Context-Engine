# ML Studio architecture audit

## Current application

- `apps/web` is the public Next.js 15/React 19 application, using TypeScript, Tailwind, TanStack Query, Zustand, Recharts, and a typed fetch client.
- `apps/admin` is the existing private Next.js 15 Admin application. It uses a custom CSS design system and session-authenticated internal APIs; it is not linked from the public product.
- The Admin role model is `platform_admin`, `ml_operator`, `labeler`, `reviewer`, and `observer`. Internal APIs are isolated below `/internal/admin/v1` and use server-side sessions, audit events, and explicit Admin CORS origins.

## Backend and data

- `apps/api` is a FastAPI application. The current MVP uses SQLite and local Railway-volume media, with Celery/Redis enabled for production-style background jobs and an in-process fallback for development.
- The existing video pipeline already provides FFmpeg/FFprobe, transcription, visual detection, OCR, semantic signals, extractor caching, versioned analysis runs, evidence artifacts, and background job records.
- Existing Admin tables cover consents, taxonomies, early dataset versions, labels, scoring configurations, evaluations, releases, and audit events. ML Studio must evolve these rather than introduce a second control plane.

## Existing AI and deployment integrations

- RunPod GPT-OSS access is implemented through `runpod_client.py` and is used only for evidence-grounded insight generation.
- RunPod GPU feature work must use a separate client and endpoint configuration; raw video must not be sent to GPT-OSS.
- Railway currently hosts FastAPI, worker, Redis, and persistent-volume storage. Netlify hosts the public and private Next.js applications.

## ML Studio integration points and risks

- Phase 1 adds `/ml-studio/**` inside `apps/admin`, using existing session protection and visual tokens.
- Phase 2 replaces the SQLite/Railway-volume production boundary with Railway PostgreSQL and private Cloudflare R2 through versioned migrations and checksum-verified asset transfer.
- The main migration risks are preserving public API contracts, maintaining current analysis/insight workflows while moving storage, and reconciling existing `ml_*` control-plane records with canonical dataset/model entities.
- The current repository contains no ORM or migration framework. Use versioned SQL migrations and a PostgreSQL repository adapter rather than introducing a new ORM.
