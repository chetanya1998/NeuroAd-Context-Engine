# Cloudflare R2 migration

NeuroAd can keep durable videos, keyframes, and exports in Cloudflare R2 while
using local Railway disk only as short-lived FFmpeg/OpenCV scratch space. Do not
mount R2 as a filesystem and do not point `NEUROAD_STORAGE_DIR` at R2.

## 1. Create the R2 bucket and credentials

Create a private bucket such as `neuroad-production`. Create an S3 API token
limited to this bucket with object read, write, and delete access. Add these
variables to both the Railway API service and any separate Railway worker:

```text
NEUROAD_OBJECT_STORAGE=r2
R2_ACCOUNT_ID=your-cloudflare-account-id
R2_BUCKET=neuroad-production
R2_ACCESS_KEY_ID=your-r2-access-key-id
R2_SECRET_ACCESS_KEY=your-r2-secret-access-key
R2_REGION=auto
R2_PRESIGN_TTL_SECONDS=900
NEUROAD_SCRATCH_DIR=/tmp/neuroad
```

`R2_ENDPOINT_URL` is optional. When omitted, the API builds it from the account
ID as `https://<account-id>.r2.cloudflarestorage.com`.

Never add R2 credentials to Netlify or to a `NEXT_PUBLIC_*` variable.

## 2. Configure R2 bucket CORS

Add a bucket CORS rule with the exact public frontend origins, for example:

```json
[
  {
    "AllowedOrigins": ["https://your-site.netlify.app", "https://app.your-domain.com"],
    "AllowedMethods": ["PUT", "GET", "HEAD"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

This is separate from the API's `CORS_ORIGINS` setting. The API CORS setting
controls control-plane calls to Railway; R2 CORS controls browser `PUT` uploads.

## 3. Deploy the code, then enable R2

Deploy this version before setting `NEUROAD_OBJECT_STORAGE=r2`. Until that
variable is enabled, uploads continue using the existing API-to-volume flow.

After enabling R2, the health response must show:

```json
"object_storage": { "backend": "r2", "enabled": true, "ready": true }
```

The browser then asks the API for a short-lived signed URL, uploads the video
directly to R2, and tells the API to verify the upload. Analysis downloads the
object to `/tmp/neuroad/<video-id>` only while processing it. Video sources are
stored with keys like `uploads/<video-id>/source.mp4`; keyframes and exports use
the existing `frames/` and `reports/` prefixes.

## 4. Migrate historical assets safely

1. Back up the Railway volume and SQLite database.
2. Copy the existing `storage/uploads`, `storage/frames`, and `storage/reports`
   prefixes to R2 while preserving their relative paths.
3. Update `videos.file_path` from the local absolute path to
   `r2://<bucket>/<relative-key>`, for example
   `r2://neuroad-production/uploads/video_abc/source.mp4`.
4. Verify one old dashboard, one export download, and one reanalysis.
5. Keep the Railway volume until those checks pass; then remove old media data.

SQLite is not moved by this change. Keep it on a Railway volume temporarily or
migrate the application database separately to Postgres.

## 5. Add lifecycle rules before production use

Use R2 lifecycle rules to abort incomplete multipart uploads after one day,
delete failed/orphaned uploads after a short window, and enforce your source
video retention policy. With a 10 GB cap, retaining 200 MB originals alone
allows about 50 maximum-size videos before frames and reports are included.
