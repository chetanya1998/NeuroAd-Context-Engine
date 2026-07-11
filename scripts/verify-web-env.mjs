const apiBase = process.env.NEXT_PUBLIC_API_BASE;

function fail(message) {
  console.error(`\n[NeuroAd deploy check] ${message}\n`);
  process.exit(1);
}

if (!apiBase) {
  fail(
    "NEXT_PUBLIC_API_BASE is required for public web deploys. Set it to your deployed API URL, for example https://api.your-domain.com."
  );
}

let parsed;
try {
  parsed = new URL(apiBase);
} catch {
  fail(`NEXT_PUBLIC_API_BASE is not a valid URL: ${apiBase}`);
}

const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
if (localHosts.has(parsed.hostname)) {
  fail(
    `NEXT_PUBLIC_API_BASE is set to ${apiBase}. Public users cannot upload to localhost; use the deployed API URL.`
  );
}

if (parsed.protocol !== "https:") {
  fail(
    `NEXT_PUBLIC_API_BASE must use HTTPS for public deploys. Current value: ${apiBase}`
  );
}

console.log(`[NeuroAd deploy check] API URL OK: ${apiBase}`);
