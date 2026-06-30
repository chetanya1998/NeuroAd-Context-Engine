"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  AudioLines,
  BarChart3,
  Brain,
  ChevronRight,
  Cpu,
  FileText,
  FileVideo,
  LayoutDashboard,
  Link2,
  ScanSearch,
  Sparkles,
  UploadCloud,
  Video,
  WandSparkles
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Reveal } from "@/components/Reveal";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { useInView } from "@/lib/useInView";
import {
  createVideoFromUrl,
  getSystemDependencies,
  ingestYouTubeVideo,
  uploadVideo
} from "@/lib/api";

/* ─── Static data ─── */

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

const pipelineStages = [
  { icon: UploadCloud, label: "Ingest", desc: "Video, audio, frames" },
  { icon: Video, label: "Frames", desc: "Scene extraction" },
  { icon: AudioLines, label: "Audio & NLP", desc: "Speech, tone, topics" },
  { icon: Brain, label: "Scoring", desc: "Attention proxy" },
  { icon: Sparkles, label: "Output", desc: "Reports & ads" }
];

const reportRows = [
  { t: "00:15 – 00:20", score: 91, cat: "Productivity", fit: "High" as const },
  { t: "01:10 – 01:15", score: 88, cat: "Lifestyle", fit: "High" as const },
  { t: "03:45 – 03:50", score: 74, cat: "Tech", fit: "Medium" as const }
];

/* ─── Counter hook ─── */

function useCounter(target: number, active: boolean) {
  const [value, setValue] = useState(0);
  const frameRef = useRef(0);

  useEffect(() => {
    if (!active) return;
    const duration = 1200;
    const startTime = performance.now();
    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * target));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      }
    }
    frameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, active]);

  return value;
}

/* ─── Main Page ─── */

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
      setError(
        "YouTube blocked server-side access for this video. Upload the video file directly for reliable analysis."
      );
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
    mutationFn: ({ url, hasPermission }: { url: string; hasPermission: boolean }) =>
      ingestYouTubeVideo(url, hasPermission),
    onSuccess: (payload) => router.push(`/analyze/${payload.video_id}`),
    onError: showActionError
  });

  const busy =
    uploadMutation.isPending || urlMutation.isPending || youtubeMutation.isPending;

  function isYouTubePageUrl(value: string) {
    try {
      const host = new URL(value).hostname.replace(/^www\./, "");
      return (
        host === "youtube.com" || host === "youtu.be" || host.endsWith(".youtube.com")
      );
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
        setError(
          "Confirm that you own or have permission to analyze this YouTube video."
        );
        return;
      }
      youtubeMutation.mutate({
        url: trimmedUrl,
        hasPermission: hasYouTubePermission
      });
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
      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 — HERO
       ═══════════════════════════════════════════════════════════ */}
      <section className="relative flex min-h-[100vh] flex-col items-center justify-center overflow-hidden px-5">
        {/* Animated dot-grid background */}
        <div className="dot-grid pointer-events-none absolute inset-0 -z-10 opacity-40" />
        {/* Radial vignette overlay */}
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,transparent_30%,#000_80%)]" />

        <Badge tone="cyan">Attention Proxy Score · v0.1</Badge>

        <h1 className="shimmer-text mt-8 max-w-4xl text-center text-5xl font-semibold leading-[1.05] md:text-7xl lg:text-8xl">
          NeuroAd Context Engine
        </h1>

        <p className="mt-6 max-w-2xl text-center text-lg leading-8 text-zinc-400 md:text-xl">
          Frame-by-frame video intelligence that turns attention signals into
          precise, contextual ad placements — scored, timestamped, and ready to
          export.
        </p>

        <div className="mt-10 flex gap-4">
          <Button
            onClick={() =>
              document.getElementById("input-section")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            Get Started <ArrowRight className="h-4 w-4" />
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            How It Works
          </Button>
        </div>

        {/* Scroll indicator */}
        <div className="absolute bottom-8 flex flex-col items-center gap-2">
          <span className="text-xs tracking-widest text-zinc-600">SCROLL</span>
          <ArrowDown className="h-4 w-4 animate-bounce-arrow text-zinc-500" />
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-5 lg:px-10">
        {/* ═══════════════════════════════════════════════════════════
            SECTION 2 — INPUT CARD
         ═══════════════════════════════════════════════════════════ */}
        <section id="input-section" className="py-20">
          <Reveal>
            <Card className="glow-border mx-auto max-w-3xl border-white/10 bg-black p-6 shadow-glow-lg md:p-8">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-white/15 bg-white text-black">
                  <Link2 className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-white">
                    Paste a video link
                  </h2>
                  <p className="text-sm text-zinc-500">
                    YouTube watch link, media page URL, or direct video file URL
                    (MP4, MOV, WebM, AVI, MKV, FLV).
                  </p>
                </div>
              </div>

              <div className="mt-6 rounded-lg border border-white/10 bg-zinc-950 p-4 text-sm leading-6 text-zinc-400">
                The engine extracts frames and audio, transcribes speech,
                identifies visual context, scores attention by timestamp, and
                produces ad-fit recommendations with exportable reports.
              </div>

              <div className="mt-6 flex flex-col gap-3 lg:flex-row">
                <input
                  value={videoUrl}
                  onChange={(event) => setVideoUrl(event.target.value)}
                  placeholder="https://www.youtube.com/watch?v=... or https://example.com/video"
                  className="min-h-12 flex-1 rounded-lg border border-white/10 bg-zinc-950 px-4 text-sm text-white outline-none ring-white/20 transition placeholder:text-zinc-700 focus:ring-2"
                />
                <Button onClick={handleVideoUrl} disabled={busy}>
                  {busy ? "Opening progress..." : "Analyze"}{" "}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>

              <label className="mt-4 flex items-start gap-3 rounded-lg border border-white/10 bg-zinc-950 p-3 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={hasYouTubePermission}
                  onChange={(event) =>
                    setHasYouTubePermission(event.target.checked)
                  }
                  className="mt-1 h-4 w-4 accent-white"
                />
                <span>
                  I own this YouTube video or have permission to download and
                  analyze it. If YouTube blocks server access, upload the video
                  file directly.
                </span>
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
                    <span className="font-semibold text-white">
                      Upload a video file
                    </span>
                    <p className="mt-1 text-sm text-zinc-500">
                      MP4, MOV, WebM, or M4V under 200 MB.
                    </p>
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
                <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                  {error}
                </div>
              ) : null}
            </Card>
          </Reveal>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 3 — HOW IT WORKS (3-step flow)
         ═══════════════════════════════════════════════════════════ */}
        <section id="how-it-works" className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-16 text-center">
              <Badge tone="cyan">How It Works</Badge>
              <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">
                Three Steps to Insight
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-zinc-400">
                From raw video to actionable ad intelligence in minutes.
              </p>
            </div>
          </Reveal>

          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                step: "01",
                title: "Analyze",
                desc: "We extract every frame, every word, every sound — building a complete sensory map of your content.",
                icon: ScanSearch
              },
              {
                step: "02",
                title: "Pipeline",
                desc: "Raw signals flow through our AI scoring engine to compute Attention Proxy and ad-fit metrics.",
                icon: Cpu
              },
              {
                step: "03",
                title: "Reports",
                desc: "Get timestamped scores, context tags, and ad recommendations — exported as CSV or JSON.",
                icon: LayoutDashboard
              }
            ].map((item, i) => {
              const Icon = item.icon;
              return (
                <Reveal key={item.step} delay={i * 150}>
                  <Card className="relative border-white/10 bg-black p-6 transition hover:border-white/20">
                    <div className="flex items-center justify-between">
                      <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/20 bg-white text-black">
                        <Icon className="h-6 w-6" />
                      </div>
                      <span className="text-3xl font-bold text-zinc-800">
                        {item.step}
                      </span>
                    </div>
                    <h3 className="mt-5 text-xl font-semibold text-white">
                      {item.title}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-zinc-500">
                      {item.desc}
                    </p>
                    {i < 2 && (
                      <ChevronRight className="absolute -right-3 top-1/2 hidden h-6 w-6 -translate-y-1/2 text-zinc-700 md:block" />
                    )}
                  </Card>
                </Reveal>
              );
            })}
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 4 — ANALYZE DEEP-DIVE
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-12 text-center">
              <Badge tone="cyan">Step 1 · Analyze</Badge>
              <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">
                Deep Frame-by-Frame Extraction
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
                We separate video, audio, and speech to analyze every
                micro-moment of your content.
              </p>
            </div>
          </Reveal>

          <div className="grid gap-6 md:grid-cols-3">
            {/* Frames */}
            <Reveal delay={0}>
              <Card className="border-white/10 bg-black p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Visual Frames</h3>
                  <Video className="h-5 w-5 text-zinc-400" />
                </div>
                <div className="relative h-36 overflow-hidden rounded-lg border border-white/5 bg-zinc-950">
                  <div className="absolute inset-y-0 left-0 flex w-[200%] animate-scroll-left items-center gap-2 px-2">
                    {[...Array(12)].map((_, i) => (
                      <div
                        key={i}
                        className="relative h-28 w-20 shrink-0 overflow-hidden rounded border border-white/10 bg-zinc-900"
                      >
                        <div
                          className="absolute inset-0 bg-gradient-to-br from-white/[0.06] to-transparent"
                          style={{ animationDelay: `${i * 0.3}s` }}
                        />
                        <div className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[9px] text-zinc-400">
                          {String(i).padStart(2, "0")}:{String((i * 5) % 60).padStart(2, "0")}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            </Reveal>

            {/* Audio */}
            <Reveal delay={150}>
              <Card className="border-white/10 bg-black p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Audio Energy</h3>
                  <Activity className="h-5 w-5 text-success" />
                </div>
                <div className="flex h-36 items-end justify-center gap-[3px] rounded-lg border border-white/5 bg-zinc-950 px-4 pb-4">
                  {[...Array(32)].map((_, i) => {
                    const h = 15 + Math.abs(Math.sin(i * 0.7)) * 75;
                    return (
                      <div
                        key={i}
                        className="w-[6px] shrink-0 rounded-full animate-wave"
                        style={{
                          animationDelay: `${i * 0.08}s`,
                          height: `${h}%`,
                          background: `linear-gradient(to top, rgba(34,197,94,0.4), rgba(255,255,255,${0.5 + Math.sin(i * 0.5) * 0.3}))`
                        }}
                      />
                    );
                  })}
                </div>
              </Card>
            </Reveal>

            {/* Transcript */}
            <Reveal delay={300}>
              <Card className="border-white/10 bg-black p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Transcript & NLP</h3>
                  <FileText className="h-5 w-5 text-warning" />
                </div>
                <div className="relative h-36 rounded-lg border border-white/5 bg-zinc-950 p-4">
                  <div className="space-y-3">
                    <div className="overflow-hidden whitespace-nowrap typing-cursor pr-1 text-xs text-zinc-500" style={{ animation: "typing 4s steps(48) infinite alternate" }}>
                      &quot;Welcome back to our deep dive into productivity tools that actually work...&quot;
                    </div>
                    <div className="h-2 w-5/6 rounded bg-white/[0.06]" />
                    <div className="h-2 w-3/4 rounded bg-white/[0.06]" />
                    <div className="h-2 w-full rounded bg-white/[0.06]" />
                  </div>
                  <div className="absolute bottom-3 right-3 flex items-center gap-2">
                    <div className="h-2 w-2 animate-pulse rounded-full bg-warning" />
                    <span className="text-[10px] text-warning">
                      Extracting context…
                    </span>
                  </div>
                </div>
              </Card>
            </Reveal>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 5 — PIPELINE VISUALIZATION
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-16 text-center">
              <Badge tone="success">Step 2 · Pipeline</Badge>
              <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">
                The Context Engine
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
                Raw signals flow through our AI models to calculate the Attention
                Proxy Score and ad-fit metrics.
              </p>
            </div>
          </Reveal>

          <div className="mx-auto max-w-5xl">
            {/* Desktop pipeline */}
            <div className="hidden md:block">
              <div className="relative flex items-center justify-between">
                {/* Connector line behind nodes */}
                <div className="absolute left-[10%] right-[10%] top-1/2 h-px -translate-y-1/2 bg-white/10" />
                {/* Traveling particles */}
                <div className="pipeline-connector absolute left-[10%] right-[10%] top-1/2 h-px -translate-y-1/2" />
                <div
                  className="pipeline-connector absolute left-[10%] right-[10%] top-1/2 h-px -translate-y-1/2"
                  style={{ animationDelay: "1.2s" }}
                />

                {pipelineStages.map((stage, i) => {
                  const Icon = stage.icon;
                  return (
                    <Reveal key={stage.label} delay={i * 120}>
                      <div className="relative z-10 flex flex-col items-center gap-3">
                        <div
                          className="flex h-16 w-16 items-center justify-center rounded-2xl border border-white/15 bg-zinc-950 shadow-glow animate-node-pulse"
                          style={{ animationDelay: `${i * 0.4}s` }}
                        >
                          <Icon className="h-7 w-7 text-white" />
                        </div>
                        <span className="text-sm font-medium text-white">
                          {stage.label}
                        </span>
                        <span className="text-xs text-zinc-600">
                          {stage.desc}
                        </span>
                      </div>
                    </Reveal>
                  );
                })}
              </div>
            </div>

            {/* Mobile pipeline (vertical) */}
            <div className="flex flex-col items-center gap-2 md:hidden">
              {pipelineStages.map((stage, i) => {
                const Icon = stage.icon;
                return (
                  <Reveal key={stage.label} delay={i * 100}>
                    <div className="flex items-center gap-4 rounded-xl border border-white/10 bg-zinc-950 p-4">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-black">
                        <Icon className="h-6 w-6 text-white" />
                      </div>
                      <div>
                        <p className="font-medium text-white">{stage.label}</p>
                        <p className="text-xs text-zinc-500">{stage.desc}</p>
                      </div>
                    </div>
                    {i < pipelineStages.length - 1 && (
                      <div className="mx-auto h-6 w-px bg-white/10" />
                    )}
                  </Reveal>
                );
              })}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 6 — LIVE OUTPUT PREVIEW
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-12 text-center">
              <Badge tone="cyan">Live Preview</Badge>
              <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">
                Attention Proxy Score
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
                A dashboard-style visualization appears after analysis with
                attention, objects, topics, and ad-fit markers per timestamp.
              </p>
            </div>
          </Reveal>

          <Reveal delay={200}>
            <Card className="mx-auto max-w-4xl overflow-hidden border-white/10 bg-black p-0">
              <div className="border-b border-white/10 p-6">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm uppercase tracking-[0.22em] text-zinc-500">
                      Live output preview
                    </p>
                    <h3 className="mt-2 text-2xl font-semibold text-white">
                      Attention Timeline
                    </h3>
                  </div>
                  <AudioLines className="h-7 w-7 text-zinc-400" />
                </div>
              </div>

              <div className="p-6">
                <div className="rounded-lg border border-white/10 bg-zinc-950 p-5">
                  <div className="h-56">
                    <svg
                      viewBox="0 0 640 220"
                      className="h-full w-full"
                      role="img"
                      aria-label="Attention score visualization preview"
                    >
                      <defs>
                        <linearGradient
                          id="line-grad"
                          x1="0"
                          x2="1"
                          y1="0"
                          y2="0"
                        >
                          <stop offset="0%" stopColor="#ffffff" />
                          <stop offset="55%" stopColor="#22c55e" />
                          <stop offset="100%" stopColor="#f59e0b" />
                        </linearGradient>
                        <linearGradient
                          id="area-grad"
                          x1="0"
                          x2="0"
                          y1="0"
                          y2="1"
                        >
                          <stop
                            offset="0%"
                            stopColor="rgba(255,255,255,0.06)"
                          />
                          <stop
                            offset="100%"
                            stopColor="rgba(255,255,255,0)"
                          />
                        </linearGradient>
                      </defs>
                      {[40, 80, 120, 160, 200].map((y) => (
                        <line
                          key={y}
                          x1="24"
                          x2="616"
                          y1={y}
                          y2={y}
                          stroke="rgba(255,255,255,0.06)"
                        />
                      ))}
                      <path
                        d="M 28 156 C 86 68, 118 82, 166 116 S 244 196, 296 90 S 386 32, 450 62 S 536 150, 610 82"
                        fill="none"
                        stroke="url(#line-grad)"
                        strokeLinecap="round"
                        strokeWidth="5"
                      />
                      <path
                        d="M 28 156 C 86 68, 118 82, 166 116 S 244 196, 296 90 S 386 32, 450 62 S 536 150, 610 82 L 610 206 L 28 206 Z"
                        fill="url(#area-grad)"
                      />
                      {(
                        [
                          [88, 77, "Hook"],
                          [294, 90, "Product"],
                          [450, 62, "Best ad"]
                        ] as const
                      ).map(([x, y, label]) => (
                        <g key={label}>
                          <circle
                            cx={x}
                            cy={y}
                            r="8"
                            fill="none"
                            stroke="rgba(255,255,255,0.3)"
                            strokeWidth="2"
                          >
                            <animate
                              attributeName="r"
                              values="8;14;8"
                              dur="2s"
                              repeatCount="indefinite"
                            />
                            <animate
                              attributeName="opacity"
                              values="1;0;1"
                              dur="2s"
                              repeatCount="indefinite"
                            />
                          </circle>
                          <circle cx={x} cy={y} r="5" fill="#ffffff" />
                          <text
                            x={x + 14}
                            y={y - 10}
                            fill="#a1a1aa"
                            fontSize="12"
                            fontWeight="500"
                          >
                            {label}
                          </text>
                        </g>
                      ))}
                    </svg>
                  </div>

                  <div className="mt-5 grid grid-cols-6 gap-2">
                    {previewSegments.map((segment) => (
                      <div key={segment.time} className="min-w-0">
                        <div className="flex h-24 items-end rounded-md border border-white/10 bg-black p-2">
                          <div
                            className={`w-full rounded-sm ${segment.tone} transition-all duration-1000`}
                            style={{ height: `${segment.score}%` }}
                          />
                        </div>
                        <p className="mt-2 text-xs text-zinc-500">
                          {segment.time}
                        </p>
                        <p className="truncate text-xs text-zinc-300">
                          {segment.label}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
                    <p className="text-sm text-zinc-500">Best ad slot</p>
                    <p className="mt-2 text-2xl font-semibold text-white">
                      00:15-00:20
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
                    <p className="text-sm text-zinc-500">Top category</p>
                    <p className="mt-2 text-2xl font-semibold text-white">
                      Productivity
                    </p>
                  </div>
                </div>
              </div>
            </Card>
          </Reveal>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 7 — REPORTS PREVIEW
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-12 text-center">
              <Badge tone="warning">Step 3 · Reports</Badge>
              <h2 className="mt-4 text-3xl font-semibold text-white md:text-5xl">
                Actionable Insights
              </h2>
              <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
                Export precise timestamps, scores, and context tags directly to
                your ad-serving platform.
              </p>
            </div>
          </Reveal>

          {/* Score counters */}
          <Reveal delay={100}>
            <ReportCounters />
          </Reveal>

          {/* Report table preview */}
          <Reveal delay={250}>
            <Card className="relative mx-auto mt-8 max-w-4xl overflow-hidden border-white/10 bg-black p-0 shadow-glow">
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-warning/[0.03] to-transparent" />
              <div className="flex items-center gap-4 border-b border-white/10 bg-zinc-950/50 p-4">
                <LayoutDashboard className="h-5 w-5 text-zinc-400" />
                <div className="text-sm font-medium text-white">
                  Campaign Report.csv
                </div>
                <Badge tone="success">Ready</Badge>
              </div>
              <div className="p-6">
                <div className="space-y-3">
                  {reportRows.map((row, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between rounded-lg border border-white/5 bg-zinc-950 p-4 opacity-0 animate-stagger-fade transition hover:bg-white/[0.02]"
                      style={{ animationDelay: `${400 + i * 200}ms` }}
                    >
                      <div className="flex gap-8">
                        <div>
                          <p className="text-xs text-zinc-500">Timestamp</p>
                          <p className="mt-1 font-mono text-sm text-white">
                            {row.t}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-zinc-500">Score</p>
                          <p className="mt-1 text-sm text-success">
                            {row.score}
                          </p>
                        </div>
                        <div className="hidden sm:block">
                          <p className="text-xs text-zinc-500">Category</p>
                          <p className="mt-1 text-sm text-zinc-300">
                            {row.cat}
                          </p>
                        </div>
                      </div>
                      <Badge
                        tone={row.fit === "High" ? "success" : "warning"}
                      >
                        {row.fit} Fit
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </Reveal>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 8 — CONCEPT STEPS (preserved)
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-16">
          <Reveal>
            <div className="mb-10 text-center">
              <h2 className="text-2xl font-semibold text-white md:text-3xl">
                From Media to Monetization
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-zinc-500">
                Four steps that turn your raw video into precise ad
                intelligence.
              </p>
            </div>
          </Reveal>

          <div className="grid gap-4 md:grid-cols-4">
            {conceptSteps.map((step, index) => {
              const Icon = step.icon;
              return (
                <Reveal key={step.title} delay={index * 100}>
                  <Card className="border-white/10 bg-black p-5 transition hover:border-white/20">
                    <div className="flex items-center justify-between">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-black">
                        <Icon className="h-5 w-5" />
                      </div>
                      <span className="text-sm text-zinc-600">
                        0{index + 1}
                      </span>
                    </div>
                    <h3 className="mt-5 text-lg font-semibold text-white">
                      {step.title}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-zinc-500">
                      {step.copy}
                    </p>
                  </Card>
                </Reveal>
              );
            })}
          </div>

          {/* Dependency status bar (preserved) */}
          <Reveal delay={200}>
            <div className="mt-6 rounded-lg border border-white/10 bg-black p-5 text-sm leading-6 text-zinc-500">
              {dependencyQuery.data?.youtube_ingest_ready
                ? "FFmpeg, FFprobe, and yt-dlp are ready. YouTube links, supported media pages, direct video URLs, and uploads can enter the real analysis pipeline."
                : dependencyQuery.data?.ready
                  ? "FFmpeg and FFprobe are ready. Uploads and direct video URLs can be analyzed; install yt-dlp for media-page and YouTube extraction."
                  : "Install FFmpeg/FFprobe before real video analysis. The processing page will surface missing runtime details clearly."}
            </div>
          </Reveal>
        </section>
      </div>
    </AppShell>
  );
}

/* ─── Report Counters Sub-Component ─── */

function ReportCounters() {
  const { ref, inView } = useInView();

  const attention = useCounter(87, inView);
  const monetization = useCounter(91, inView);
  const segments = useCounter(24, inView);

  return (
    <div ref={ref} className="mx-auto grid max-w-3xl gap-4 sm:grid-cols-3">
      <div className="rounded-xl border border-white/10 bg-zinc-950 p-6 text-center">
        <p className="text-4xl font-bold text-white">{attention}</p>
        <p className="mt-2 text-sm text-zinc-500">Overall Attention</p>
      </div>
      <div className="rounded-xl border border-white/10 bg-zinc-950 p-6 text-center">
        <p className="text-4xl font-bold text-success">{monetization}</p>
        <p className="mt-2 text-sm text-zinc-500">Monetization Score</p>
      </div>
      <div className="rounded-xl border border-white/10 bg-zinc-950 p-6 text-center">
        <p className="text-4xl font-bold text-white">{segments}</p>
        <p className="mt-2 text-sm text-zinc-500">Segments Analyzed</p>
      </div>
    </div>
  );
}
