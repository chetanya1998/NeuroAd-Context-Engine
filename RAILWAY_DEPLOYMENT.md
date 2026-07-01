# Railway + Netlify Deployment

Use Railway for the FastAPI Docker backend and Netlify for the Next.js frontend.

Railway should deploy only the backend service from:

```text
apps/api
```

That matters because Railway looks for a `Dockerfile` at the root of the service source directory. The backend Dockerfile is:

```text
apps/api/Dockerfile
```

## 1. Push Code

Commit and push the deployment files:

```bash
git add .
git commit -m "Configure Railway backend deployment"
git push origin V1.0
```

## 2. Create Railway Backend

In Railway:

1. Create a new project.
2. Deploy from GitHub repo.
3. Select the `V1.0` branch.
4. Set the service root/source directory to:

```text
apps/api
```

5. Railway should detect `Dockerfile`.
## 2.5. YouTube Download Bypassing
If your Railway IP gets blocked by YouTube (HTTP 400 or empty chunks), you need to route traffic through a RapidAPI service. 
You do not need an extra service; just add the following variables to your **API Service Variables**:

1. Create a free account on [RapidAPI.com](https://rapidapi.com/).
2. Subscribe to a free tier YouTube downloader API (e.g., "YouTube Video and Shorts Downloader" or similar that returns JSON with a video URL).
3. Add these variables to your Railway API service:
```bash
RAPIDAPI_KEY=your_rapidapi_key_here
RAPIDAPI_HOST=the_api_host_here
RAPIDAPI_URL=https://the-api-host-here/endpoint
```

## 3. Add Railway Volume

Add one volume to the backend service.

Mount path:

```text
/data
```

This stores:

```text
/data/neuroad/storage
/data/neuroad/neuroad.db
```

## 4. Add Railway Variables

Set these backend variables in Railway:

```bash
PORT=8000
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
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
RAPIDAPI_KEY=your_key_here
RAPIDAPI_HOST=your_host_here
RAPIDAPI_URL=your_endpoint_here
```

After Netlify deploys, update `CORS_ORIGINS` with your Netlify URL.

## 5. Deploy And Test Railway

After Railway deploys, open:

```text
https://your-railway-domain.up.railway.app/health
```

Expected:

```text
ready: true
vosk.model_ready: true
mobilenet_ssd.available: true
```

## 6. Deploy Netlify Frontend

In Netlify:

1. Add new project.
2. Import the same GitHub repo.
3. Select branch `V1.0`.
4. Use these settings:

```text
Base directory: repository root
Build command: npm --workspace apps/web run build
Publish directory: apps/web/.next
```

Set Netlify variables:

```bash
NEXT_PUBLIC_API_BASE=https://your-railway-domain.up.railway.app
NODE_VERSION=22
NETLIFY_NEXT_SKEW_PROTECTION=true
```

Deploy Netlify.

## 7. Final CORS Update

Copy your Netlify URL and update Railway:

```bash
CORS_ORIGINS=https://your-netlify-site.netlify.app,http://localhost:3000,http://127.0.0.1:3000
```

Redeploy/restart the Railway backend.

## 8. Final Smoke Test

Check:

```text
https://your-railway-domain.up.railway.app/health
https://your-railway-domain.up.railway.app/api/system/dependencies
https://your-netlify-site.netlify.app
```

Then upload a short MP4 and run analysis.
