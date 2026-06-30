"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  AudioLines,
  BarChart3,
  Brain,
  FileText,
  FileVideo,
  Layers,
  LayoutDashboard,
  Link2,
  ScanSearch,
  Settings2,
  UploadCloud,
  Video,
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
    copy: "Upload a file, paste a video page URL, paste a direct video URL, or analyze a YouTube video you have permission to process."
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

  function isHttpUrl(value: string) {
    try {
      const protocol = new URL(value).protocol;
      return protocol === "http:" || protocol === "https:";
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
    if (!isHttpUrl(trimmedUrl)) {
      setError("Paste a valid http(s) video URL.");
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
                  <p className="text-sm text-zinc-500">Use a YouTube watch link, a supported public media page, or a direct video file URL such as MP4, MOV, WebM, AVI, MKV, or FLV.</p>
                </div>
              </div>

              <div className="mt-5 rounded-lg border border-white/10 bg-zinc-950 p-4 text-sm leading-6 text-zinc-400">
                The engine extracts frames and audio, transcribes speech, identifies visual context, scores attention by timestamp, and produces ad-fit recommendations with exportable reports.
              </div>

              <div className="mt-5 flex flex-col gap-3 lg:flex-row">
                <input
                  value={videoUrl}
                  onChange={(event) => setVideoUrl(event.target.value)}
                  placeholder="https://www.youtube.com/watch?v=... or https://example.com/video"
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

        {/* --- NEW SECTIONS --- */}
        {/* 1. Analyze Section */}
        <section className="border-t border-white/10 py-24">
          <div className="mb-12 text-center">
            <Badge tone="cyan">Step 1: Analyze</Badge>
            <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">Deep Frame-by-Frame Extraction</h2>
            <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
              We separate video, audio, and speech to analyze every micro-moment of your content.
            </p>
          </div>
          <div className="grid gap-6 md:grid-cols-3">
            <Card className="border-white/10 bg-black p-6">
              <div className="mb-6 flex items-center justify-between">
                <h3 className="font-semibold text-white">Visual Frames</h3>
                <Video className="h-5 w-5 text-zinc-400" />
              </div>
              <div className="relative h-32 overflow-hidden rounded-lg bg-zinc-950">
                <div className="absolute inset-y-0 left-0 flex w-[200%] animate-scroll-left items-center gap-2 px-2">
                  {[...Array(10)].map((_, i) => (
                    <div key={i} className="h-24 w-16 shrink-0 rounded border border-white/20 bg-zinc-900 shadow-glow" />
                  ))}
                </div>
              </div>
            </Card>
            <Card className="border-white/10 bg-black p-6">
              <div className="mb-6 flex items-center justify-between">
                <h3 className="font-semibold text-white">Audio Energy</h3>
                <Activity className="h-5 w-5 text-success" />
              </div>
              <div className="flex h-32 items-end justify-center gap-1 rounded-lg bg-zinc-950 p-4">
                {[...Array(24)].map((_, i) => (
                  <div
                    key={i}
                    className="w-2 rounded-full bg-success/80 animate-wave"
                    style={{ animationDelay: `${i * 0.1}s`, height: `${Math.max(20, Math.random() * 100)}%` }}
                  />
                ))}
              </div>
            </Card>
            <Card className="border-white/10 bg-black p-6">
              <div className="mb-6 flex items-center justify-between">
                <h3 className="font-semibold text-white">Transcript & NLP</h3>
                <FileText className="h-5 w-5 text-warning" />
              </div>
              <div className="relative h-32 rounded-lg bg-zinc-950 p-4">
                <div className="space-y-3">
                  <div className="h-2 w-3/4 rounded bg-white/10" />
                  <div className="h-2 w-full rounded bg-white/10" />
                  <div className="h-2 w-5/6 rounded bg-white/10" />
                  <div className="absolute bottom-4 right-4 animate-pulse-slow rounded bg-warning/20 px-2 py-1 text-xs text-warning">
                    Extracting context...
                  </div>
                </div>
              </div>
            </Card>
          </div>
        </section>

        {/* 2. Pipeline Section */}
        <section className="border-t border-white/10 py-24">
          <div className="mb-12 text-center">
            <Badge tone="success">Step 2: Pipeline</Badge>
            <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">The Context Engine</h2>
            <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
              Raw signals flow through our proprietary AI models to calculate the Attention Proxy Score and ad-fit metrics.
            </p>
          </div>
          <div className="relative flex min-h-[300px] flex-col items-center justify-center gap-8 md:flex-row md:gap-16">
            <div className="absolute top-1/2 -z-10 hidden h-0.5 w-full -translate-y-1/2 bg-white/10 md:block overflow-hidden">
              <div className="h-full w-1/3 animate-scroll-left bg-gradient-to-r from-transparent via-success to-transparent" />
            </div>

            <div className="flex h-24 w-24 animate-float flex-col items-center justify-center rounded-2xl border border-white/10 bg-zinc-950 shadow-glow" style={{ animationDelay: "0s" }}>
              <Layers className="h-8 w-8 text-zinc-400" />
              <span className="mt-2 text-xs text-zinc-500">Raw Data</span>
            </div>

            <div className="flex h-24 w-24 animate-float flex-col items-center justify-center rounded-2xl border border-success/30 bg-success/10 shadow-glow" style={{ animationDelay: "0.5s" }}>
              <Brain className="h-8 w-8 text-success" />
              <span className="mt-2 text-xs text-success">Scoring</span>
            </div>

            <div className="flex h-24 w-24 animate-float flex-col items-center justify-center rounded-2xl border border-white/40 bg-white/5 shadow-glow" style={{ animationDelay: "1s" }}>
              <Settings2 className="h-8 w-8 text-white" />
              <span className="mt-2 text-xs text-white">Vectors</span>
            </div>
          </div>
        </section>

        {/* 3. Reports Section */}
        <section className="border-t border-white/10 py-24">
          <div className="mb-12 text-center">
            <Badge tone="warning">Step 3: Reports</Badge>
            <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">Actionable Insights</h2>
            <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
              Export precise timestamps, scores, and context tags directly to your ad-serving platform.
            </p>
          </div>
          <div className="mx-auto max-w-4xl animate-slide-up">
            <Card className="relative overflow-hidden border-white/10 bg-black p-0 shadow-glow">
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-warning/5 to-transparent" />
              <div className="flex items-center gap-4 border-b border-white/10 bg-zinc-950/50 p-4">
                <LayoutDashboard className="h-5 w-5 text-zinc-400" />
                <div className="text-sm font-medium text-white">Campaign Report.csv</div>
                <Badge tone="success">Ready</Badge>
              </div>
              <div className="p-6">
                <div className="space-y-4">
                  {[
                    { t: "00:15 - 00:20", score: "91", cat: "Productivity", fit: "High" },
                    { t: "01:10 - 01:15", score: "88", cat: "Lifestyle", fit: "High" },
                    { t: "03:45 - 03:50", score: "74", cat: "Tech", fit: "Medium" }
                  ].map((row, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg border border-white/5 bg-zinc-950 p-4 transition hover:bg-white/[0.02]">
                      <div className="flex gap-8">
                        <div>
                          <p className="text-xs text-zinc-500">Timestamp</p>
                          <p className="mt-1 font-mono text-sm text-white">{row.t}</p>
                        </div>
                        <div>
                          <p className="text-xs text-zinc-500">Score</p>
                          <p className="mt-1 text-sm text-success">{row.score}</p>
                        </div>
                        <div className="hidden sm:block">
                          <p className="text-xs text-zinc-500">Category</p>
                          <p className="mt-1 text-sm text-zinc-300">{row.cat}</p>
                        </div>
                      </div>
                      <Badge tone={row.fit === "High" ? "success" : "warning"}>{row.fit} Fit</Badge>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </div>
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
              ? "FFmpeg, FFprobe, and yt-dlp are ready. YouTube links, supported media pages, direct video URLs, and uploads can enter the real analysis pipeline."
              : dependencyQuery.data?.ready
                ? "FFmpeg and FFprobe are ready. Uploads and direct video URLs can be analyzed; install yt-dlp for media-page and YouTube extraction."
                : "Install FFmpeg/FFprobe before real video analysis. The processing page will surface missing runtime details clearly."}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
