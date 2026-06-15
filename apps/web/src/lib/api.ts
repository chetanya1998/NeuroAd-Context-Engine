import type { AnalysisPayload, JobStatus } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      // Keep the HTTP status text.
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

export async function uploadVideo(file: File) {
  const form = new FormData();
  form.append("file", file);
  return parseResponse<{ video_id: string; status: string }>(
    await fetch(`${API_BASE}/api/videos/upload`, { method: "POST", body: form })
  );
}

export async function createVideoFromUrl(url: string) {
  return parseResponse<{ video_id: string; status: string }>(
    await fetch(`${API_BASE}/api/videos/url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    })
  );
}

export async function ingestYouTubeVideo(url: string, hasPermission: boolean) {
  return parseResponse<{ video_id: string; status: string }>(
    await fetch(`${API_BASE}/api/videos/youtube/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, has_permission: hasPermission })
    })
  );
}

export async function startAnalysis(videoId: string) {
  return parseResponse<{ job_id: string; status: string }>(
    await fetch(`${API_BASE}/api/videos/${videoId}/analyze`, { method: "POST" })
  );
}

export async function getJob(jobId: string) {
  return parseResponse<JobStatus>(await fetch(`${API_BASE}/api/jobs/${jobId}`));
}

export async function getAnalysis(videoId: string) {
  return parseResponse<AnalysisPayload>(await fetch(`${API_BASE}/api/videos/${videoId}/analysis`));
}

export async function getSystemDependencies() {
  return parseResponse<{
    ready: boolean;
    youtube_ingest_ready: boolean;
    youtube_cookies_configured: boolean;
    dependencies: {
      ffmpeg: { available: boolean; path?: string | null };
      ffprobe: { available: boolean; path?: string | null };
      yt_dlp: { available: boolean; path?: string | null };
    };
  }>(await fetch(`${API_BASE}/api/system/dependencies`));
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
