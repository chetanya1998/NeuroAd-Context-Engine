"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  AudioLines,
  BarChart3,
  FileVideo,
  Link2,
  ScanSearch,
  UploadCloud,
  WandSparkles
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { createVideoFromUrl, getSystemDependencies, ingestYouTubeVideo, uploadVideo } from "@/lib/api";

const previewSegments = [
  { time: "00:00", score: 72, label: "Hook", tone: "bg-white" },
  { time: "00:05", score: 38, label: "Drop risk", tone: "bg-red-500" },
  { time: "00:10", score: 81, label: "Object visible", tone: "bg-emerald-400" },
  { time: "00:15", score: 91, label: "Best ad slot", tone: "bg-white" },
  { time: "00:20", score: 64, label: "Topic shift", tone: "bg-amber-300" },
  { time: "00:25", score: 47, label: "Neutral", tone: "bg-zinc-500" }
];

const conceptSteps = [
  {
    icon: FileVideo,
    title: "Start with media",
    copy: "Upload a file, paste a direct video URL, or analyze a YouTube video you have permission to process."
  },
  {
    icon: ScanSearch,
    title: "Read the moment",
    copy: "Frames, audio energy, transcript, objects, and topics are extracted segment by segment."
  },
  {
    icon: BarChart3,
    title: "Score context",
    copy: "Attention Proxy Score and ad-fit scoring turn the raw signals into useful decisions."
  },
  {
    icon: WandSparkles,
    title: "Act on it",
    copy: "Open the dashboard, inspect exact timestamps, and export CSV or JSON reports."
  }
];

export default function HomePage() {
  const router = useRouter();
  const [videoUrl, setVideoUrl] = useState("");
  const [hasYouTubePermission, setHasYouTubePermission] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dependencyQuery = useQuery({
    queryKey: ["system-dependencies"],
    queryFn: getSystemDependencies,
    refetchInterval: 15000
  });

  function showActionError(err: Error) {
    if (err.message.toLowerCase().includes("sign in to confirm")) {
      setError("YouTube blocked server-side access for this video. Upload the video file directly for reliable analysis.");
      return;
    }
    setError(err.message);
  }

  const uploadMutation = useMutation({
    mutationFn: uploadVideo,
    onSuccess: (payload) => router.push(`/analyze/${payload.video_id}`),
    onError: showActionError
  });

  const urlMutation = useMutation({
    mutationFn: createVideoFromUrl,
    onSuccess: (payload) => router.push(`/analyze/${payload.video_id}`),
    onError: showActionError
  });

  const youtubeMutation = useMutation({
    mutationFn: ({ url, hasPermission }: { url: string; hasPermission: boolean }) => ingestYouTubeVideo(url, hasPermission),
    onSuccess: (payload) => router.push(`/analyze/${payload.video_id}`),
    onError: showActionError
  });

  const busy = uploadMutation.isPending || urlMutation.isPending || youtubeMutation.isPending;

  function isYouTubePageUrl(value: string) {
    try {
      const host = new URL(value).hostname.replace(/^www\./, "");
      return host === "youtube.com" || host === "youtu.be" || host.endsWith(".youtube.com");
    } catch {
      return false;
    }
  }

  function isDirectVideoUrl(value: string) {
    try {
      const pathname = new URL(value).pathname.toLowerCase();
      return [".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv", ".flv", ".wmv", ".mpg", ".mpeg", ".3gp", ".3g2", ".ogv"].some(
        (extension) => pathname.endsWith(extension)
      );
    } catch {
      return false;
    }
  }

  function handleFile(file?: File) {
    setError(null);
    if (!file) return;
    uploadMutation.mutate(file);
  }

  function handleVideoUrl() {
    setError(null);
    const trimmedUrl = videoUrl.trim();
    if (!trimmedUrl) {
      setError("Paste a YouTube URL you can analyze, or a direct public video file URL.");
      return;
    }
    if (isYouTubePageUrl(trimmedUrl)) {
      if (!hasYouTubePermission) {
        setError("Confirm that you own or have permission to analyze this YouTube video.");
        return;
      }
      youtubeMutation.mutate({ url: trimmedUrl, hasPermission: hasYouTubePermission });
      return;
    }
    if (!isDirectVideoUrl(trimmedUrl)) {
      setError("Paste a YouTube URL, or a direct video file URL ending in .mp4, .mov, .webm, .m4v, .avi, .mkv, .flv, .wmv, .mpg, .mpeg, .3gp, .3g2, or .ogv.");
      return;
    }
    urlMutation.mutate(trimmedUrl);
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-5 py-10 lg:px-10 lg:py-14">
        <section className="grid min-h-[calc(100vh-7rem)] items-center gap-8 xl:grid-cols-[1.02fr_0.98fr]">
          <div>
            <Badge tone="cyan">Attention Proxy Score</Badge>
            <h1 className="mt-6 max-w-5xl text-5xl font-semibold leading-[0.95] text-white md:text-7xl">
              NeuroAd Context Engine
            </h1>
            <p className="mt-6 max-w-3xl text-lg leading-8 text-zinc-400 md:text-xl">
              It analyzes video frames, speech, objects, topics, and audio energy to produce a moment-level attention timeline and contextual ad recommendations.
            </p>

            <Card className="mt-8 border-white/10 bg-black p-4 shadow-glow md:p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-white/15 bg-white text-black">
                  <Link2 className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-white">Paste a video link</h2>
                  <p className="text-sm text-zinc-500">Use a YouTube watch link or a direct video file URL such as MP4, MOV, WebM, M4V, AVI, MKV, or FLV.</p>
                </div>
              </div>

              <div className="mt-5 rounded-lg border border-white/10 bg-zinc-950 p-4 text-sm leading-6 text-zinc-400">
                The engine extracts frames and audio, transcribes speech, identifies visual context, scores attention by timestamp, and produces ad-fit recommendations with exportable reports.
              </div>

              <div className="mt-5 flex flex-col gap-3 lg:flex-row">
                <input
                  value={videoUrl}
                  onChange={(event) => setVideoUrl(event.target.value)}
                  placeholder="https://www.youtube.com/watch?v=... or https://example.com/video.mkv"
                  className="min-h-12 flex-1 rounded-lg border border-white/10 bg-zinc-950 px-4 text-sm text-white outline-none ring-white/20 transition placeholder:text-zinc-700 focus:ring-2"
                />
                <Button onClick={handleVideoUrl} disabled={busy}>
                  {busy ? "Opening progress..." : "Analyze"} <ArrowRight className="h-4 w-4" />
                </Button>
              </div>

              <label className="mt-4 flex items-start gap-3 rounded-lg border border-white/10 bg-zinc-950 p-3 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={hasYouTubePermission}
                  onChange={(event) => setHasYouTubePermission(event.target.checked)}
                  className="mt-1 h-4 w-4 accent-white"
                />
                <span>I own this YouTube video or have permission to download and analyze it. If YouTube blocks server access, upload the video file directly.</span>
              </label>

              <div className="mt-5 flex items-center gap-3 text-sm text-zinc-600">
                <span className="h-px flex-1 bg-white/10" />
                OR
                <span className="h-px flex-1 bg-white/10" />
              </div>

              <label className="mt-5 flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-dashed border-white/15 bg-zinc-950 p-4 transition hover:border-white/40">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-white text-black">
                    <UploadCloud className="h-5 w-5" />
                  </div>
                  <div>
                    <span className="font-semibold text-white">Upload a video file</span>
                    <p className="mt-1 text-sm text-zinc-500">MP4, MOV, WebM, or M4V under 200 MB.</p>
                  </div>
                </div>
                <ArrowRight className="hidden h-5 w-5 text-zinc-500 sm:block" />
                <input
                  type="file"
                  accept="video/mp4,video/quicktime,video/webm,video/x-m4v"
                  className="sr-only"
                  disabled={busy}
                  onChange={(event) => handleFile(event.target.files?.[0])}
                />
              </label>

              {error ? (
                <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">{error}</div>
              ) : null}
            </Card>
          </div>

          <Card className="overflow-hidden border-white/10 bg-black p-0">
            <div className="border-b border-white/10 p-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm uppercase tracking-[0.22em] text-zinc-500">Live output preview</p>
                  <h2 className="mt-3 text-3xl font-semibold text-white">Attention Proxy Score</h2>
                </div>
                <AudioLines className="h-7 w-7 text-zinc-400" />
              </div>
              <p className="mt-3 text-sm leading-6 text-zinc-500">
                A dashboard-style visualization appears after analysis with attention, objects, topics, and ad-fit markers per timestamp.
              </p>
            </div>

            <div className="p-6">
              <div className="rounded-lg border border-white/10 bg-zinc-950 p-5">
                <div className="h-64">
                  <svg viewBox="0 0 640 260" className="h-full w-full" role="img" aria-label="Attention score visualization preview">
                    <defs>
                      <linearGradient id="line" x1="0" x2="1" y1="0" y2="0">
                        <stop offset="0%" stopColor="#ffffff" />
                        <stop offset="55%" stopColor="#22c55e" />
                        <stop offset="100%" stopColor="#f59e0b" />
                      </linearGradient>
                    </defs>
                    {[40, 90, 140, 190, 240].map((y) => (
                      <line key={y} x1="24" x2="616" y1={y} y2={y} stroke="rgba(255,255,255,0.08)" />
                    ))}
                    <path
                      d="M 28 176 C 86 78, 118 92, 166 136 S 244 226, 296 100 S 386 38, 450 72 S 536 170, 610 92"
                      fill="none"
                      stroke="url(#line)"
                      strokeLinecap="round"
                      strokeWidth="6"
                    />
                    <path
                      d="M 28 176 C 86 78, 118 92, 166 136 S 244 226, 296 100 S 386 38, 450 72 S 536 170, 610 92 L 610 236 L 28 236 Z"
                      fill="rgba(255,255,255,0.045)"
                    />
                    {[
                      [88, 87, "Hook"],
                      [294, 100, "Product"],
                      [450, 72, "Best ad"]
                    ].map(([x, y, label]) => (
                      <g key={label}>
                        <circle cx={Number(x)} cy={Number(y)} r="7" fill="#ffffff" />
                        <text x={Number(x) + 12} y={Number(y) - 12} fill="#d4d4d8" fontSize="14">
                          {label}
                        </text>
                      </g>
                    ))}
                  </svg>
                </div>

                <div className="mt-5 grid grid-cols-6 gap-2">
                  {previewSegments.map((segment) => (
                    <div key={segment.time} className="min-w-0">
                      <div className="flex h-28 items-end rounded-md border border-white/10 bg-black p-2">
                        <div className={`w-full rounded-sm ${segment.tone}`} style={{ height: `${segment.score}%` }} />
                      </div>
                      <p className="mt-2 text-xs text-zinc-500">{segment.time}</p>
                      <p className="truncate text-xs text-zinc-300">{segment.label}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
                  <p className="text-sm text-zinc-500">Best ad slot</p>
                  <p className="mt-2 text-2xl font-semibold text-white">00:15-00:20</p>
                </div>
                <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
                  <p className="text-sm text-zinc-500">Top category</p>
                  <p className="mt-2 text-2xl font-semibold text-white">Productivity</p>
                </div>
              </div>
            </div>
          </Card>
        </section>

        <section className="border-t border-white/10 py-12">
          <div className="grid gap-4 md:grid-cols-4">
            {conceptSteps.map((step, index) => {
              const Icon = step.icon;
              return (
                <Card key={step.title} className="border-white/10 bg-black p-5">
                  <div className="flex items-center justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-black">
                      <Icon className="h-5 w-5" />
                    </div>
                    <span className="text-sm text-zinc-600">0{index + 1}</span>
                  </div>
                  <h3 className="mt-5 text-lg font-semibold text-white">{step.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-zinc-500">{step.copy}</p>
                </Card>
              );
            })}
          </div>

          <div className="mt-6 rounded-lg border border-white/10 bg-black p-5 text-sm leading-6 text-zinc-500">
            {dependencyQuery.data?.youtube_ingest_ready
              ? "FFmpeg, FFprobe, and yt-dlp are ready. YouTube links, direct video URLs, and uploads can enter the real local analysis pipeline."
              : dependencyQuery.data?.ready
                ? "FFmpeg and FFprobe are ready. Uploads and direct video URLs can be analyzed; install yt-dlp for YouTube ingestion."
                : "Install FFmpeg/FFprobe before real video analysis. The processing page will surface missing runtime details clearly."}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
