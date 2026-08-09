# Cloudflare R2 migration

NeuroAd stores durable source videos, keyframes, and exports in private
Cloudflare R2 while using `/tmp/neuroad` only for FFmpeg/OpenCV scratch files.
Do not mount R2 as a filesystem or point `NEUROAD_STORAGE_DIR` at it.

Set these variables on the Railway API and worker services:

```text
NEUROAD_OBJECT_STORAGE=r2
R2_ACCOUNT_ID=your-account-id
R2_BUCKET=neuroad-production
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key
R2_REGION=auto
R2_PRESIGN_TTL_SECONDS=900
NEUROAD_SCRATCH_DIR=/tmp/neuroad
```

Keep R2 private. Add a bucket CORS rule for the exact frontend origin with
`PUT`, `GET`, and `HEAD`, and allow the `Content-Type` header. These settings
are distinct from the API's `CORS_ORIGINS` variable.

After deployment, `/health` must report `object_storage.ready: true`. New
uploads go directly from the browser to R2 through a short-lived signed URL.

For historic data, back up the Railway volume and SQLite database, copy
`storage/uploads`, `storage/frames`, and `storage/reports` to matching R2 keys,
then change `videos.file_path` values to `r2://<bucket>/<key>`. Keep the Railway
volume until old reports and reanalysis have been verified. R2 does not replace
the SQLite database; migrate that separately to Postgres when ready.
