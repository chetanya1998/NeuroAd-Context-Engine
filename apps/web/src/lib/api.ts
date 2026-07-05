import type { AnalysisPayload, JobStatus } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type UploadOptions = {
  onProgress?: (progress: number) => void;
};

function apiConnectionErrorMessage() {
  if (typeof window !== "undefined") {
    if (window.navigator && !window.navigator.onLine) {
      return "Your internet connection appears to be offline. Reconnect, then try the upload again.";
    }
    try {
      const apiUrl = new URL(API_BASE, window.location.href);
      const isLocalApi = ["localhost", "127.0.0.1", "::1"].includes(apiUrl.hostname);
      if (window.location.protocol === "https:" && apiUrl.protocol === "http:" && !isLocalApi) {
        return "Uploads cannot reach the API because this secure site is configured with an insecure API URL. Set NEXT_PUBLIC_API_BASE to the backend HTTPS URL and redeploy.";
      }
    } catch {
      return "Uploads cannot reach the API because NEXT_PUBLIC_API_BASE is not a valid URL.";
    }
  }

  return `Uploads cannot reach the NeuroAd API at ${API_BASE}. Check that the backend is online and that CORS_ORIGINS includes this website origin.`;
}

async function apiFetch(input: string, init?: RequestInit) {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(apiConnectionErrorMessage());
    }
    throw error;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      // Keep the HTTP status text.
    }
    if (response.status === 413) {
      message = "Upload was rejected before processing because the video is too large for the current server limit.";
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function absoluteMediaUrl(path?: string | null) {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

export async function uploadVideo(file: File, options?: UploadOptions) {
  const form = new FormData();
  form.append("file", file);
  return new Promise<{ video_id: string; status: string }>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/api/videos/upload`);
    request.timeout = 10 * 60 * 1000;

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options?.onProgress?.(Math.min(99, Math.round((event.loaded / event.total) * 100)));
      }
    };

    request.onload = () => {
      options?.onProgress?.(100);
      const response = new Response(request.responseText, {
        status: request.status,
        statusText: request.statusText,
        headers: { "Content-Type": request.getResponseHeader("Content-Type") ?? "application/json" }
      });
      parseResponse<{ video_id: string; status: string }>(response).then(resolve).catch(reject);
    };

    request.onerror = () => {
      reject(new Error(apiConnectionErrorMessage()));
    };

    request.ontimeout = () => {
      reject(
        new Error(
          "The upload is taking too long on this connection. Try a smaller file, move to a stronger network, or upload again when the connection is stable."
        )
      );
    };

    request.send(form);
  });
}

export async function uploadCookies(file: File) {
  const form = new FormData();
  form.append("file", file);
  return parseResponse<{ status: string; message: string }>(
    await apiFetch(`${API_BASE}/api/system/cookies`, { method: "POST", body: form })
  );
}

export async function createVideoFromUrl(url: string) {
  return parseResponse<{ video_id: string; status: string }>(
    await apiFetch(`${API_BASE}/api/videos/url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    })
  );
}

export async function ingestYouTubeVideo(url: string, hasPermission: boolean) {
  return parseResponse<{ video_id: string; status: string }>(
    await apiFetch(`${API_BASE}/api/videos/youtube/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, has_permission: hasPermission })
    })
  );
}

export async function startAnalysis(videoId: string) {
  return parseResponse<{ job_id: string; status: string }>(
    await apiFetch(`${API_BASE}/api/videos/${videoId}/analyze`, { method: "POST" })
  );
}

export async function getJob(jobId: string) {
  return parseResponse<JobStatus>(await apiFetch(`${API_BASE}/api/jobs/${jobId}`));
}

export async function getAnalysis(videoId: string) {
  return parseResponse<AnalysisPayload>(await apiFetch(`${API_BASE}/api/videos/${videoId}/analysis`));
}

export async function getSystemDependencies() {
  return parseResponse<{
    ready: boolean;
    youtube_ingest_ready: boolean;
    youtube_cookies_configured: boolean;
    limits?: {
      max_upload_mb: number;
      max_source_seconds: number;
      max_analysis_seconds: number;
    };
    dependencies: {
      ffmpeg: { available: boolean; path?: string | null };
      ffprobe: { available: boolean; path?: string | null };
      yt_dlp: { available: boolean; path?: string | null };
    };
  }>(await apiFetch(`${API_BASE}/api/system/dependencies`));
}

export function exportUrl(videoId: string, format: "csv" | "json") {
  return `${API_BASE}/api/videos/${videoId}/export?format=${format}`;
}

export function formatTime(seconds: number) {
  const total = Math.floor(seconds);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function formatRange(start: number, end: number) {
  return `${formatTime(start)}-${formatTime(end)}`;
}
