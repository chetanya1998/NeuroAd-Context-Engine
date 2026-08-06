# Internal ML Dashboard

The control plane is a separate Next.js application in `apps/admin`. It is not
linked from the public NeuroAd site and should be deployed as a separate private
Netlify site, for example `https://admin.neuroad.example`.

## Deployment

1. Create a Netlify site from the repository with base directory `apps/admin`.
2. Attach the private admin subdomain and set:

   ```dotenv
   NEXT_PUBLIC_ADMIN_API_BASE=https://api.neuroad.example
   ```

3. Add the admin origin to the Railway API service. Keep public origins and
   admin origins separate:

   ```dotenv
   CORS_ORIGINS=https://app.neuroad.example
   ADMIN_CORS_ORIGINS=https://admin.neuroad.example
   NEUROAD_ADMIN_BOOTSTRAP_EMAIL=admin@company.example
   NEUROAD_ADMIN_BOOTSTRAP_PASSWORD=replace-with-a-long-unique-password
   NEUROAD_TRAINING_CONSENT_POLICY_VERSION=2026-08-01
   NEUROAD_GIT_SHA=<injected-by-CI>
   NEUROAD_GIT_BRANCH=main
   NEUROAD_BUILD_TIME=<injected-by-CI>
   NEUROAD_RELEASE_ID=<injected-by-CI>
   NEUROAD_SCORING_MANIFEST_VERSION=attention-proxy-v1
   ```

The bootstrap account is created only if the address does not already exist.
Remove `NEUROAD_ADMIN_BOOTSTRAP_PASSWORD` after the first administrator is
created, then use the dashboard invitation API for additional staff.

## Boundaries

- All control-plane APIs are under `/internal/admin/v1` and require an internal
  session.
- The API rejects admin browser origins that are not in `ADMIN_CORS_ORIGINS`.
- Customer data can enter labeling and dataset snapshots only when its stored
  consent status is `opted_in`.
- Release records expose GitHub/Railway/Netlify metadata. To create a signed
  manifest-only GitHub release PR, provide a short-lived GitHub App installation
  token as `NEUROAD_GITHUB_INSTALLATION_TOKEN` plus
  `NEUROAD_GITHUB_REPOSITORY`. Deployment credentials must remain server-side.

## Local access

Run the API with its bootstrap environment variables, then run:

```bash
npm run dev:admin
```

Open `http://localhost:3001` directly. The public app at port 3000 does not
contain any link or route to the internal dashboard.
