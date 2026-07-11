"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
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
  ScanSearch,
  UploadCloud,
  Video,
  WifiOff,
  WandSparkles
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Reveal } from "@/components/Reveal";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import HeroContextAnimation from "@/components/animations/HeroContextAnimation";
import { useInView } from "@/lib/useInView";
import {
  getSystemDependencies,
  uploadVideo
} from "@/lib/api";

/* ─── Static data ─── */


const conceptSteps = [
  {
    icon: FileVideo,
    title: "Bring an approved video",
    copy: "Upload an owned or permission-cleared file with size checks, progress feedback, and clear recovery guidance."
  },
  {
    icon: ScanSearch,
    title: "Decode each segment",
    copy: "Frames, speech, audio energy, objects, topics, and scene context are aligned to exact timestamps."
  },
  {
    icon: BarChart3,
    title: "Score attention fit",
    copy: "Attention Proxy Score, category signals, and brand-safety context turn raw media into placement guidance."
  },
  {
    icon: WandSparkles,
    title: "Move to activation",
    copy: "Inspect the dashboard, review recommended ad slots, and export CSV or JSON for downstream campaign work."
  }
];


const reportRows = [
  { t: "00:15 – 00:20", score: 91, cat: "Productivity", fit: "High" as const },
  { t: "01:10 – 01:15", score: 88, cat: "Lifestyle", fit: "High" as const },
  { t: "03:45 – 03:50", score: 74, cat: "Tech", fit: "Medium" as const }
];

const featureHighlights = [
  {
    icon: UploadCloud,
    title: "Flexible ingest",
    copy: "Upload owned or permission-cleared video files with clear transfer progress and format checks."
  },
  {
    icon: AudioLines,
    title: "Multimodal signals",
    copy: "Sync visual frames, transcript, audio energy, detected objects, and topics into one segment timeline."
  },
  {
    icon: Brain,
    title: "Attention Proxy Score",
    copy: "Rank moments by attention potential and ad-fit context instead of relying on manual scrubbing."
  },
  {
    icon: LayoutDashboard,
    title: "Review-ready outputs",
    copy: "Open timestamped dashboards, compare fit by category, and export clean CSV or JSON reports."
  }
];

const pipelineStages = {
  ingest: {
    icon: UploadCloud,
    title: "Ingest",
    subtitle: "Video & Audio",
    detail: "The engine gathers the approved video, audio, and timing signals into one clean source.",
    result: "One timeline",
    accent: "white"
  },
  vision: {
    icon: Video,
    title: "Vision AI",
    subtitle: "Objects & Scenes",
    detail: "It recognizes the setting, products, people, actions, and visual mood in each moment.",
    result: "Scene context",
    accent: "green"
  },
  audio: {
    icon: AudioLines,
    title: "Audio AI",
    subtitle: "Speech & Tone",
    detail: "It listens for voice, pace, energy, topics, and sentiment so the ad does not interrupt the mood.",
    result: "Mood signal",
    accent: "amber"
  },
  score: {
    icon: Brain,
    title: "Scoring Engine",
    subtitle: "Attention Proxy",
    detail: "It combines the signals and highlights moments where an ad feels timely, relevant, and premium.",
    result: "Best ad slot",
    accent: "white"
  }
};

type PipelineStepId = keyof typeof pipelineStages;

const FALLBACK_MAX_UPLOAD_MB = 200;
const SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mov", ".webm", ".m4v"];

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const [isDraggingUpload, setIsDraggingUpload] = useState(false);
  const [activePipelineStep, setActivePipelineStep] = useState<PipelineStepId>("score");
  const dependencyQuery = useQuery({
    queryKey: ["system-dependencies"],
    queryFn: getSystemDependencies,
    refetchInterval: 15000
  });

  function showActionError(err: Error) {
    setUploadProgress(null);
    setUploadNotice(null);
    if (err.message.toLowerCase().includes("sign in to confirm")) {
      setError(
        "YouTube blocked server-side access for this video. Upload the video file directly for reliable analysis."
      );
      return;
    }
    setError(err.message);
  }

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadVideo(file, { onProgress: setUploadProgress }),
    onMutate: () => {
      setUploadProgress(0);
      setUploadNotice("Uploading video. Keep this tab open while the file transfers.");
    },
    onSuccess: (payload) => {
      setUploadProgress(100);
      setUploadNotice("Upload complete. Opening the analysis workspace...");
      router.push(`/analyze/${payload.video_id}`);
    },
    onError: showActionError
  });

  const busy = uploadMutation.isPending;
  const activePipeline = pipelineStages[activePipelineStep];
  const ActivePipelineIcon = activePipeline.icon;
  const maxUploadMb = dependencyQuery.data?.limits?.max_upload_mb ?? FALLBACK_MAX_UPLOAD_MB;
  const hasConnectionError =
    error?.toLowerCase().includes("connection") ||
    error?.toLowerCase().includes("offline") ||
    error?.toLowerCase().includes("cannot reach") ||
    error?.toLowerCase().includes("taking too long") ||
    error?.toLowerCase().includes("localhost:8000");
  const hasApiConfigError =
    error?.toLowerCase().includes("localhost:8000") ||
    error?.toLowerCase().includes("next_public_api_base") ||
    error?.toLowerCase().includes("insecure api url");

  useEffect(() => {
    if (!uploadMutation.isPending) return;
    const timer = window.setTimeout(() => {
      setUploadNotice(
        "Still uploading. Large videos can take a while on slower networks; keep this tab open until it finishes."
      );
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [uploadMutation.isPending]);

  function handleFile(file?: File) {
    setError(null);
    setUploadNotice(null);
    if (!file) return;
    if (typeof window !== "undefined" && !window.navigator.onLine) {
      setError("Your internet connection appears to be offline. Reconnect, then try the upload again.");
      return;
    }
    const suffix = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!SUPPORTED_VIDEO_EXTENSIONS.includes(suffix)) {
      setError("Use a supported video file: MP4, MOV, WebM, or M4V.");
      return;
    }
    const maxUploadBytes = maxUploadMb * 1024 * 1024;
    if (file.size > maxUploadBytes) {
      setError(
        `${file.name} is ${formatFileSize(file.size)}. Upload a video under ${maxUploadMb} MB, or trim/compress it before uploading.`
      );
      return;
    }
    uploadMutation.mutate(file);
  }

  return (
    <AppShell>
      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 — HERO
       ═══════════════════════════════════════════════════════════ */}
      <section className="pointer-events-none relative isolate flex min-h-[58svh] w-screen max-w-[100vw] flex-col items-center justify-center overflow-hidden px-5 py-12 sm:py-14">
        <HeroContextAnimation />
        {/* Radial vignette overlay */}
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,transparent_30%,#000_80%)]" />

        <div className="pointer-events-auto">
          <Badge tone="cyan">Attention Proxy Score · v0.1</Badge>
        </div>

        <h1 className="hero-wordmark mt-8 w-full max-w-[96vw] whitespace-nowrap pb-3 text-center text-[clamp(1.95rem,7.2vw,5.4rem)] font-semibold leading-none">
          <span className="hero-wordmark__shimmer">NeuroAd Context Engine</span>
        </h1>

        <p className="mt-6 w-full max-w-[340px] text-center text-base leading-7 text-zinc-400 sm:max-w-3xl sm:text-lg md:text-xl md:leading-8">
          <span className="block">Find the video moments that earn attention.</span>
          <span className="block">Place ads where they feel natural and on time.</span>
        </p>

        <div className="mt-8 flex w-full max-w-[350px] flex-col gap-3 sm:w-auto sm:max-w-none sm:flex-row sm:gap-4 pointer-events-auto">
          <Button
            className="w-full sm:w-auto"
            onClick={() =>
              document.getElementById("input-section")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            Analyze Video <ArrowRight className="h-4 w-4" />
          </Button>
          <Button
            variant="secondary"
            className="w-full sm:w-auto"
            onClick={() =>
              document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            How It Works
          </Button>
        </div>

        {/* Scroll indicator */}
        <div className="absolute bottom-5 hidden flex-col items-center gap-2 md:flex">
          <span className="text-xs tracking-widest text-zinc-600">SCROLL</span>
          <ArrowDown className="h-4 w-4 animate-bounce-arrow text-zinc-500" />
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-5 lg:px-10">
        {/* ═══════════════════════════════════════════════════════════
            SECTION 2 — INPUT CARD
         ═══════════════════════════════════════════════════════════ */}
        <section id="input-section" className="py-10 md:py-14">
          <Reveal>
            <Card className="glow-border mx-auto max-w-6xl border-white/10 bg-black p-6 shadow-glow-lg sm:p-8 md:p-10">
              <div className="grid gap-8 lg:grid-cols-[minmax(0,0.78fr)_minmax(0,1.22fr)] lg:items-center">
                <div>
                  <Badge tone="cyan">Secure Upload</Badge>
                  <h2 className="signal-shimmer-title mt-4 text-3xl font-semibold tracking-tight md:text-5xl">
                    Upload a video file
                  </h2>
                  <p className="mt-4 text-base leading-7 text-zinc-400 md:text-lg">
                    Add an owned or permission-cleared video and the engine will open the analysis workspace when ingest is ready.
                  </p>

                  <div className="mt-6 grid gap-3 text-sm text-zinc-500 sm:grid-cols-3 lg:grid-cols-1">
                    <div className="rounded-lg border border-white/10 bg-zinc-950 px-4 py-3">
                      <span className="font-medium text-zinc-300">Formats</span>
                      <p className="mt-1">MP4, MOV, WebM, M4V</p>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-zinc-950 px-4 py-3">
                      <span className="font-medium text-zinc-300">Limit</span>
                      <p className="mt-1">Up to {maxUploadMb} MB</p>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-zinc-950 px-4 py-3">
                      <span className="font-medium text-zinc-300">Network</span>
                      <p className="mt-1">Keep this tab open</p>
                    </div>
                  </div>
                </div>

                <label
                  className={[
                    "relative flex min-h-[360px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition",
                    isDraggingUpload
                      ? "border-white bg-white/[0.08]"
                      : "border-white/30 bg-zinc-950 hover:border-white/60 hover:bg-white/[0.04]",
                    busy ? "pointer-events-none opacity-70" : ""
                  ].join(" ")}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setIsDraggingUpload(true);
                  }}
                  onDragLeave={() => setIsDraggingUpload(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setIsDraggingUpload(false);
                    handleFile(event.dataTransfer.files?.[0]);
                  }}
                >
                  <div className="absolute inset-4 rounded-lg border border-white/5" />
                  <div className="relative flex h-24 w-24 items-center justify-center rounded-2xl bg-white text-black shadow-[0_0_56px_rgba(255,255,255,0.18)]">
                    <UploadCloud className="h-10 w-10" />
                  </div>
                  <span className="relative mt-7 text-2xl font-semibold text-white">
                    {isDraggingUpload ? "Drop video to upload" : "Drop your video here"}
                  </span>
                  <span className="relative mt-3 text-base leading-7 text-zinc-500">
                    or select a file from your computer
                  </span>
                  <span className="relative mt-7 inline-flex items-center gap-2 rounded-lg bg-white px-6 py-3 text-base font-semibold text-black">
                    Choose file <ArrowRight className="h-4 w-4" />
                  </span>
                  <input
                    type="file"
                    accept="video/mp4,video/quicktime,video/webm,video/x-m4v"
                    className="sr-only"
                    disabled={busy}
                    onChange={(event) => {
                      handleFile(event.target.files?.[0]);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>

              <div className="mt-8 rounded-lg border border-white/10 bg-zinc-950 p-5 text-base leading-7 text-zinc-400">
                The engine extracts frames and audio, transcribes speech,
                identifies visual context, scores attention by segment, and
                produces review-ready ad-fit recommendations.
              </div>

              {/* Video URL Section commented out per current landing-page direction. */}

              {uploadMutation.isPending && uploadProgress !== null ? (
                <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-3">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="font-medium text-white">Uploading video</span>
                    <span className="font-mono text-xs text-zinc-400">{uploadProgress}%</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-white transition-all duration-300"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  {uploadNotice ? (
                    <p className="mt-3 text-xs leading-5 text-zinc-400">{uploadNotice}</p>
                  ) : null}
                </div>
              ) : null}

              {error ? (
                <div className="mt-4 rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
                  <div className="flex items-start gap-3">
                    {hasConnectionError ? (
                      <WifiOff className="mt-0.5 h-5 w-5 shrink-0" />
                    ) : (
                      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
                    )}
                    <div>
                      <p className="font-semibold">
                        {hasApiConfigError
                          ? "API deployment setup needed"
                          : hasConnectionError
                            ? "Upload connection issue"
                            : "Upload could not start"}
                      </p>
                      <p className="mt-1 leading-6 text-red-200/90">{error}</p>
                      {hasApiConfigError ? (
                        <div className="mt-3 grid gap-2 text-xs leading-5 text-red-100/75 sm:grid-cols-3">
                          <span>Set NEXT_PUBLIC_API_BASE to the public API URL.</span>
                          <span>Add this website origin to CORS_ORIGINS on the API.</span>
                          <span>Redeploy the web app after changing the environment variable.</span>
                        </div>
                      ) : hasConnectionError ? (
                        <div className="mt-3 grid gap-2 text-xs leading-5 text-red-100/75 sm:grid-cols-3">
                          <span>Check your connection and retry.</span>
                          <span>Use a smaller or compressed file on slow networks.</span>
                          <span>Confirm the API URL and CORS settings in deployment.</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : null}
            </Card>
          </Reveal>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 3 — FEATURE HIGHLIGHTS
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-16">
          <Reveal>
            <div className="mb-10 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div>
                <Badge tone="cyan">New Capabilities</Badge>
                <h2 className="mt-4 max-w-2xl text-3xl font-semibold text-white md:text-4xl">
                  Built for faster placement review
                </h2>
              </div>
              <p className="max-w-xl text-sm leading-6 text-zinc-500 md:text-right">
                Move from source media to scored, timestamped recommendations
                with less manual scrubbing and clearer export paths.
              </p>
            </div>
          </Reveal>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {featureHighlights.map((feature, index) => {
              const Icon = feature.icon;
              return (
                <Reveal key={feature.title} delay={index * 100} className="h-full">
                  <Card className="capability-card flex h-full flex-col overflow-hidden border-white/10 bg-black p-5 transition hover:border-white/20">
                    <div className="capability-card__rail" />
                    <div className="relative flex h-11 w-11 items-center justify-center rounded-lg border border-white/15 bg-zinc-950 text-white">
                      <Icon className="h-5 w-5" />
                    </div>
                    <h3 className="mt-5 text-base font-semibold text-white">
                      {feature.title}
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-zinc-500">
                      {feature.copy}
                    </p>
                  </Card>
                </Reveal>
              );
            })}
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 4 — HOW IT WORKS (3-step flow)
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

          <div className="mx-auto grid max-w-6xl items-stretch gap-5 sm:grid-cols-2 xl:grid-cols-3">
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
                <Reveal key={item.step} delay={i * 150} className="h-full min-w-0">
                  <Card className="relative flex h-full min-h-[260px] flex-col border-white/10 bg-black p-5 transition hover:border-white/20 sm:p-6">
                    <div className="flex items-center justify-between">
                      <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/20 bg-white text-black">
                        <Icon className="h-6 w-6" />
                      </div>
                      <span className="text-3xl font-bold text-zinc-800">
                        {item.step}
                      </span>
                    </div>

                    <h3 className="mt-8 text-xl font-semibold text-white">
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
        <section id="section-analyze" className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-12 text-center">
              <Badge tone="cyan">Step 1 · Analyze</Badge>
              <h2 className="signal-shimmer-title mt-4 text-3xl font-semibold md:text-5xl">
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
              <Reveal delay={0} className="min-w-0">
              <Card className="border-white/10 bg-black p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Visual Frames</h3>
                  <Video className="h-5 w-5 text-zinc-400" />
                </div>
                <div className="relative h-36 overflow-hidden rounded-lg border border-white/5 bg-zinc-950">
                  <div className="absolute inset-y-0 left-0 flex w-[200%] animate-scroll-left items-center gap-2 px-2">
                    {[...Array(12)].map((_, i) => {
                      const images = [
                        "/assets/landing_frame_productivity_hyperreal.jpg",
                        "/assets/landing_frame_auto_hyperreal.jpg",
                        "/assets/landing_frame_coffee_hyperreal.jpg",
                        "/assets/landing_frame_travel_hyperreal.jpg",
                      ];
                      const imgSrc = images[i % images.length];
                      return (
                        <div
                          key={i}
                          className="relative h-28 w-20 shrink-0 overflow-hidden rounded border border-white/10 bg-zinc-900"
                        >
                          <img src={imgSrc} alt="sample video frame" className="absolute inset-0 h-full w-full object-cover opacity-85" />
                          <div
                            className="absolute inset-0 bg-gradient-to-br from-white/[0.06] to-transparent"
                            style={{ animationDelay: `${i * 0.3}s` }}
                          />
                          <div className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[9px] text-zinc-300 font-medium">
                            {String(i).padStart(2, "0")}:{String((i * 5) % 60).padStart(2, "0")}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </Card>
            </Reveal>

            {/* Audio */}
              <Reveal delay={150} className="min-w-0">
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
              <Reveal delay={300} className="min-w-0">
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
        <section id="section-pipeline" className="border-t border-white/10 py-32">
          <Reveal>
            <div className="mb-20 text-center">
              <Badge tone="success">Step 2 · Context Engine</Badge>
              <h2 className="signal-shimmer-title mt-4 text-4xl font-semibold tracking-tight md:text-5xl">
                Parallel Data Processing
              </h2>
              <p className="mx-auto mt-5 max-w-xl text-lg text-zinc-400">
                Raw media is split into synchronized visual and audio streams,
                processed by specialized AI models, and synthesized into a final score.
              </p>
            </div>
          </Reveal>

          <div className="mx-auto max-w-6xl px-4">
            <Reveal delay={200}>
              <div className="pipeline-board signal-sheen-panel relative overflow-hidden rounded-2xl border border-white/10 bg-black/50 p-6 shadow-2xl md:p-12">
                {/* Background grid lines */}
                <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)]" />
                <div className="pipeline-aurora pipeline-aurora--green" />
                <div className="pipeline-aurora pipeline-aurora--amber" />

                <div className="relative z-10 mb-8 grid gap-5 border-b border-white/10 pb-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.28em] text-zinc-600">
                      Live capability map
                    </p>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
                      Click a stage to see how raw media becomes a confident ad placement decision.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {(["ingest", "vision", "audio", "score"] as PipelineStepId[]).map((stepId) => (
                      <button
                        key={stepId}
                        type="button"
                        onClick={() => setActivePipelineStep(stepId)}
                        onPointerDown={() => setActivePipelineStep(stepId)}
                        onPointerEnter={() => setActivePipelineStep(stepId)}
                        onFocus={() => setActivePipelineStep(stepId)}
                        className="whitespace-nowrap rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:border-white/30 hover:text-white data-[active=true]:border-white/40 data-[active=true]:bg-white data-[active=true]:text-black"
                        data-active={activePipelineStep === stepId}
                      >
                        {pipelineStages[stepId].title}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="pipeline-diagram relative flex flex-col items-center gap-12 md:block md:min-h-[520px]">
                  {/* Node 1: Ingest */}
                  <button
                    type="button"
                    onClick={() => setActivePipelineStep("ingest")}
                    onPointerDown={() => setActivePipelineStep("ingest")}
                    onPointerEnter={() => setActivePipelineStep("ingest")}
                    onMouseEnter={() => setActivePipelineStep("ingest")}
                    onFocus={() => setActivePipelineStep("ingest")}
                    className="pipeline-node pipeline-node--ingest group z-10 flex w-48 flex-col items-center gap-4 text-center"
                    data-active={activePipelineStep === "ingest"}
                  >
                    <div className="pipeline-node__icon flex h-20 w-20 items-center justify-center rounded-2xl border border-white/20 bg-zinc-950 shadow-glow transition-all duration-500 group-hover:scale-110 group-hover:border-white/40">
                      <UploadCloud className="h-8 w-8 text-white" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-white">Ingest</h3>
                      <p className="mt-1 text-sm text-zinc-500">Video & Audio</p>
                    </div>
                  </button>

                  {/* Split branches (Desktop) */}
                  <div className="pointer-events-none absolute inset-0 hidden md:block">
                    <svg className="h-full w-full" viewBox="0 0 1000 520" preserveAspectRatio="none">
                      {/* Top branch */}
                      <path
                        d="M 176 208 C 320 208, 320 120, 500 120"
                        fill="none"
                        stroke="rgba(255,255,255,0.15)"
                        strokeWidth="2"
                      />
                      <path
                        d="M 176 208 C 320 208, 320 120, 500 120"
                        fill="none"
                        stroke="url(#data-flow-top)"
                        strokeWidth="3"
                        className="pipeline-flow-line pipeline-flow-line--top"
                      />
                      {/* Bottom branch */}
                      <path
                        d="M 176 208 C 320 208, 320 330, 500 330"
                        fill="none"
                        stroke="rgba(255,255,255,0.15)"
                        strokeWidth="2"
                      />
                      <path
                        d="M 176 208 C 320 208, 320 330, 500 330"
                        fill="none"
                        stroke="url(#data-flow-bottom)"
                        strokeWidth="3"
                        className="pipeline-flow-line pipeline-flow-line--bottom"
                      />
                      {/* Merge back top */}
                      <path
                        d="M 500 120 C 680 120, 680 208, 824 208"
                        fill="none"
                        stroke="rgba(255,255,255,0.15)"
                        strokeWidth="2"
                      />
                      <path
                        d="M 500 120 C 680 120, 680 208, 824 208"
                        fill="none"
                        stroke="url(#data-flow-merge)"
                        strokeWidth="3"
                        className="pipeline-flow-line pipeline-flow-line--merge"
                      />
                      {/* Merge back bottom */}
                      <path
                        d="M 500 330 C 680 330, 680 208, 824 208"
                        fill="none"
                        stroke="rgba(255,255,255,0.15)"
                        strokeWidth="2"
                      />
                      <path
                        d="M 500 330 C 680 330, 680 208, 824 208"
                        fill="none"
                        stroke="url(#data-flow-merge)"
                        strokeWidth="3"
                        className="pipeline-flow-line pipeline-flow-line--merge pipeline-flow-line--late"
                      />

                      <circle r="6" fill="#22C55E" className="pipeline-packet">
                        <animateMotion
                          dur="3.8s"
                          repeatCount="indefinite"
                          path="M 176 208 C 320 208, 320 120, 500 120 C 680 120, 680 208, 824 208"
                        />
                      </circle>
                      <circle r="6" fill="#F59E0B" className="pipeline-packet pipeline-packet--late">
                        <animateMotion
                          dur="4.4s"
                          repeatCount="indefinite"
                          path="M 176 208 C 320 208, 320 330, 500 330 C 680 330, 680 208, 824 208"
                        />
                      </circle>
                      <circle r="4" fill="#F8FAFC" className="pipeline-packet pipeline-packet--spark">
                        <animateMotion
                          dur="2.8s"
                          repeatCount="indefinite"
                          path="M 824 208 C 844 208, 856 208, 876 208"
                        />
                      </circle>
                      
                      <defs>
                        <linearGradient id="data-flow-top" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor="transparent" />
                          <stop offset="50%" stopColor="#22C55E">
                            <animate attributeName="stop-color" values="#22C55E;#3B82F6;#22C55E" dur="3s" repeatCount="indefinite" />
                          </stop>
                          <stop offset="100%" stopColor="transparent" />
                        </linearGradient>
                        <linearGradient id="data-flow-bottom" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor="transparent" />
                          <stop offset="50%" stopColor="#F59E0B">
                            <animate attributeName="stop-color" values="#F59E0B;#EF4444;#F59E0B" dur="3s" repeatCount="indefinite" />
                          </stop>
                          <stop offset="100%" stopColor="transparent" />
                        </linearGradient>
                        <linearGradient id="data-flow-merge" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0%" stopColor="transparent" />
                          <stop offset="50%" stopColor="#E5E7EB" />
                          <stop offset="100%" stopColor="transparent" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>

                  {/* Parallel Tracks */}
                  <div className="z-10 flex flex-col gap-16 md:contents">
                    {/* Vision Track */}
                    <button
                      type="button"
                      onClick={() => setActivePipelineStep("vision")}
                      onPointerDown={() => setActivePipelineStep("vision")}
                      onPointerEnter={() => setActivePipelineStep("vision")}
                      onMouseEnter={() => setActivePipelineStep("vision")}
                      onFocus={() => setActivePipelineStep("vision")}
                      className="pipeline-node pipeline-node--vision group flex w-48 flex-col items-center gap-4 text-center"
                      data-active={activePipelineStep === "vision"}
                    >
                      <div className="pipeline-node__icon flex h-20 w-20 items-center justify-center rounded-2xl border border-white/20 bg-zinc-950 shadow-[0_0_30px_rgba(34,197,94,0.15)] transition-all duration-500 group-hover:scale-110 group-hover:border-green-500/50">
                        <Video className="h-8 w-8 text-green-400" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-white">Vision AI</h3>
                        <p className="mt-1 text-sm text-zinc-500">Objects & Scenes</p>
                      </div>
                    </button>

                    {/* Audio Track */}
                    <button
                      type="button"
                      onClick={() => setActivePipelineStep("audio")}
                      onPointerDown={() => setActivePipelineStep("audio")}
                      onPointerEnter={() => setActivePipelineStep("audio")}
                      onMouseEnter={() => setActivePipelineStep("audio")}
                      onFocus={() => setActivePipelineStep("audio")}
                      className="pipeline-node pipeline-node--audio group flex w-48 flex-col items-center gap-4 text-center"
                      data-active={activePipelineStep === "audio"}
                    >
                      <div className="pipeline-node__icon flex h-20 w-20 items-center justify-center rounded-2xl border border-white/20 bg-zinc-950 shadow-[0_0_30px_rgba(245,158,11,0.15)] transition-all duration-500 group-hover:scale-110 group-hover:border-amber-500/50">
                        <AudioLines className="h-8 w-8 text-amber-400" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-white">Audio AI</h3>
                        <p className="mt-1 text-sm text-zinc-500">Speech & Tone</p>
                      </div>
                    </button>
                  </div>

                  {/* Node 3: Synthesis */}
                  <button
                    type="button"
                    onClick={() => setActivePipelineStep("score")}
                    onPointerDown={() => setActivePipelineStep("score")}
                    onPointerEnter={() => setActivePipelineStep("score")}
                    onMouseEnter={() => setActivePipelineStep("score")}
                    onFocus={() => setActivePipelineStep("score")}
                    className="pipeline-node pipeline-node--score group z-10 flex w-48 flex-col items-center gap-4 text-center"
                    data-active={activePipelineStep === "score"}
                  >
                    <div className="pipeline-node__icon flex h-20 w-20 items-center justify-center rounded-2xl border border-white/20 bg-white shadow-[0_0_40px_rgba(255,255,255,0.2)] transition-all duration-500 group-hover:scale-110 group-hover:shadow-[0_0_60px_rgba(255,255,255,0.4)]">
                      <Brain className="h-8 w-8 text-black" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-white">Scoring Engine</h3>
                      <p className="mt-1 text-sm text-zinc-500">Attention Proxy</p>
                    </div>
                  </button>
                </div>

                <div className="relative z-10 mt-10 grid gap-4 md:grid-cols-[1fr_0.8fr]">
                  <div className="pipeline-insight rounded-xl border border-white/10 bg-zinc-950/80 p-5 backdrop-blur">
                    <div className="flex items-start gap-4">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-white/15 bg-white text-black">
                        <ActivePipelineIcon className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="flex flex-wrap items-center gap-3">
                          <h3 className="text-lg font-semibold text-white">
                            {activePipeline.title}
                          </h3>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs text-zinc-400">
                            {activePipeline.result}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-zinc-400">
                          {activePipeline.detail}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    {[
                      ["91", "ad-fit"],
                      ["24", "segments"],
                      ["3", "exports"]
                    ].map(([value, label]) => (
                      <div key={label} className="pipeline-metric rounded-xl border border-white/10 bg-white/[0.03] p-4 text-center">
                        <p className="text-2xl font-semibold text-white">{value}</p>
                        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-zinc-600">
                          {label}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Mobile connectors (vertical line) */}
                <div className="pointer-events-none absolute bottom-[20%] top-[10%] left-1/2 -ml-px w-px bg-gradient-to-b from-white/0 via-white/20 to-white/0 md:hidden" />
              </div>
            </Reveal>
          </div>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 6 — LIVE OUTPUT PREVIEW
         ═══════════════════════════════════════════════════════════ */}
        <section className="border-t border-white/10 py-32">
          <Reveal>
            <div className="mb-20 text-center">
              <Badge tone="cyan">Live Preview</Badge>
              <h2 className="signal-shimmer-title mt-4 text-4xl font-semibold tracking-tight md:text-5xl">
                Real-Time Analysis
              </h2>
              <p className="mx-auto mt-5 max-w-2xl text-lg text-zinc-400">
                Watch the Context Engine parse your media in real-time, mapping
                attention proxy scores to precise, frame-accurate timestamps.
              </p>
            </div>
          </Reveal>

          <Reveal delay={200}>
            {/* Mock OS Window Frame */}
            <div className="signal-sheen-panel mx-auto max-w-6xl overflow-hidden rounded-2xl border border-white/10 bg-black shadow-glow-lg">
              {/* Window Header */}
              <div className="flex h-12 items-center border-b border-white/10 bg-white/[0.02] px-4">
                <div className="flex gap-2">
                  <div className="h-3 w-3 rounded-full bg-red-500/80" />
                  <div className="h-3 w-3 rounded-full bg-amber-500/80" />
                  <div className="h-3 w-3 rounded-full bg-green-500/80" />
                </div>
                <div className="mx-auto flex items-center gap-2 text-xs text-zinc-500">
                  <Activity className="h-3.5 w-3.5" />
                  <span>project_alpha_final.mp4 — Analyzing</span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr]">
                {/* Left Col: Media Player Mock */}
                <div className="border-b border-white/10 bg-zinc-950 p-6 md:border-b-0 md:border-r">
                  <div className="relative aspect-video w-full overflow-hidden rounded-xl border border-white/10 bg-black">
                    <img src="/assets/landing_dashboard_video_hyperreal.jpg" alt="Live analysis feed" className="absolute inset-0 h-full w-full object-cover opacity-75" />
                    {/* Shimmer background */}
                    <div className="absolute inset-0 bg-gradient-to-r from-zinc-900 via-zinc-800 to-zinc-900 bg-[length:200%_100%] animate-shimmer opacity-40 mix-blend-overlay" />
                    
                    {/* Scanning Line */}
                    <div className="absolute bottom-0 top-0 w-px bg-white/50 shadow-[0_0_10px_#fff] animate-scrub" />

                    {/* Pop-up Tags */}
                    <div className="absolute bottom-4 left-4 flex flex-col gap-2">
                      <div className="flex items-center gap-2 rounded-full border border-green-500/30 bg-green-500/10 px-3 py-1 text-xs font-medium text-green-400 backdrop-blur-sm animate-pulse-slow">
                        <ScanSearch className="h-3 w-3" />
                        Object: Laptop (98%)
                      </div>
                      <div className="flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-400 backdrop-blur-sm animate-pulse-slow" style={{ animationDelay: '1s' }}>
                        <AudioLines className="h-3 w-3" />
                        Tone: Upbeat
                      </div>
                    </div>
                  </div>

                  <div className="mt-6 flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="relative flex h-2 w-2 items-center justify-center">
                        <div className="absolute h-full w-full rounded-full bg-cyan-400 animate-pulse-ring" />
                        <div className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
                      </div>
                      <span className="text-sm font-medium text-zinc-300">Live Analysis</span>
                    </div>
                    <span className="font-mono text-xs text-zinc-500">00:14 / 00:30</span>
                  </div>
                </div>

                {/* Right Col: Timeline & Chart */}
                <div className="p-6">
                  <div className="flex items-center justify-between mb-8">
                    <div>
                      <h3 className="text-lg font-semibold text-white">Attention Timeline</h3>
                      <p className="text-sm text-zinc-500">Proxy score mapped to semantic segments</p>
                    </div>
                    <Badge tone="success">Optimal ad slot found</Badge>
                  </div>

                  {/* SVG Chart with Scrubber */}
                  <div className="relative h-48 w-full rounded-xl border border-white/5 bg-white/[0.01] p-4">
                    {/* The animated scrubber line */}
                    <div className="absolute bottom-4 top-4 z-10 w-px bg-white/30 animate-scrub">
                      <div className="absolute -top-1 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-white shadow-[0_0_8px_#fff]" />
                    </div>

                    <svg
                      viewBox="0 0 640 160"
                      className="h-full w-full overflow-visible"
                      preserveAspectRatio="none"
                    >
                      <defs>
                        <linearGradient id="line-grad" x1="0" x2="1" y1="0" y2="0">
                          <stop offset="0%" stopColor="#ef4444" />
                          <stop offset="50%" stopColor="#22c55e" />
                          <stop offset="100%" stopColor="#f59e0b" />
                        </linearGradient>
                        <linearGradient id="area-grad" x1="0" x2="0" y1="0" y2="1">
                          <stop offset="0%" stopColor="rgba(34,197,94,0.2)" />
                          <stop offset="100%" stopColor="rgba(34,197,94,0)" />
                        </linearGradient>
                      </defs>

                      {/* Grid Lines */}
                      {[20, 60, 100, 140].map((y) => (
                        <line key={y} x1="0" x2="640" y1={y} y2={y} stroke="rgba(255,255,255,0.05)" strokeDasharray="4 4" />
                      ))}

                      {/* The Curve */}
                      <path
                        d="M 0 120 C 80 120, 120 40, 200 40 S 300 140, 400 60 S 520 80, 640 20"
                        fill="none"
                        stroke="url(#line-grad)"
                        strokeWidth="4"
                        strokeLinecap="round"
                      />
                      <path
                        d="M 0 120 C 80 120, 120 40, 200 40 S 300 140, 400 60 S 520 80, 640 20 L 640 160 L 0 160 Z"
                        fill="url(#area-grad)"
                      />

                      {/* Plot Points */}
                      <g className="animate-pulse-slow">
                        <circle cx="200" cy="40" r="5" fill="#fff" stroke="#22c55e" strokeWidth="2" />
                        <text x="190" y="25" fill="#a1a1aa" fontSize="12" fontWeight="500">Hook Peak</text>
                      </g>
                      <g className="animate-pulse-slow" style={{ animationDelay: '1s' }}>
                        <circle cx="400" cy="60" r="5" fill="#fff" stroke="#22c55e" strokeWidth="2" />
                        <text x="390" y="45" fill="#a1a1aa" fontSize="12" fontWeight="500">Ad Target</text>
                      </g>
                    </svg>
                  </div>

                  {/* Segment Blocks */}
                  <div className="mt-4 grid grid-cols-5 gap-2">
                    <div className="space-y-1">
                      <div className="h-6 w-full rounded border border-red-500/20 bg-red-500/10" />
                      <div className="flex justify-between text-[10px] text-zinc-500 font-mono"><span>0s</span><span>6s</span></div>
                      <div className="text-xs text-zinc-400">Intro / Drop</div>
                    </div>
                    <div className="space-y-1">
                      <div className="h-6 w-full rounded border border-green-500/20 bg-green-500/10" />
                      <div className="flex justify-between text-[10px] text-zinc-500 font-mono"><span>6s</span><span>12s</span></div>
                      <div className="text-xs text-zinc-400">Hook</div>
                    </div>
                    <div className="space-y-1">
                      <div className="h-6 w-full rounded border border-zinc-500/20 bg-zinc-500/10" />
                      <div className="flex justify-between text-[10px] text-zinc-500 font-mono"><span>12s</span><span>18s</span></div>
                      <div className="text-xs text-zinc-400">Context Build</div>
                    </div>
                    <div className="space-y-1">
                      <div className="h-6 w-full rounded border border-green-500/40 bg-green-500/20 relative overflow-hidden">
                        <div className="absolute inset-0 bg-white/10 animate-pulse" />
                      </div>
                      <div className="flex justify-between text-[10px] text-green-500 font-mono"><span>18s</span><span>24s</span></div>
                      <div className="text-xs font-semibold text-green-400">Best Ad Slot</div>
                    </div>
                    <div className="space-y-1">
                      <div className="h-6 w-full rounded border border-amber-500/20 bg-amber-500/10" />
                      <div className="flex justify-between text-[10px] text-zinc-500 font-mono"><span>24s</span><span>30s</span></div>
                      <div className="text-xs text-zinc-400">Outro</div>
                    </div>
                  </div>

                </div>
              </div>
            </div>
          </Reveal>
        </section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 7 — REPORTS PREVIEW
         ═══════════════════════════════════════════════════════════ */}
        <section id="section-reports" className="border-t border-white/10 py-24">
          <Reveal>
            <div className="mb-12 text-center">
              <Badge tone="warning">Step 3 · Reports</Badge>
              <h2 className="signal-shimmer-title mt-4 text-3xl font-semibold md:text-5xl">
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

          <div className="grid items-stretch gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {conceptSteps.map((step, index) => {
              const Icon = step.icon;
              return (
                <Reveal key={step.title} delay={index * 100} className="h-full min-w-0">
                  <Card className="flex h-full min-h-[292px] flex-col border-white/10 bg-black p-5 transition hover:border-white/20">
                    <div className="flex items-center justify-between">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-black">
                        <Icon className="h-5 w-5" />
                      </div>
                      <span className="text-sm text-zinc-600">
                        0{index + 1}
                      </span>
                    </div>

                    <h3 className="mt-8 text-lg font-semibold text-white">
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
          {dependencyQuery.data?.ready ? (
            <Reveal delay={200}>
              <div className="mt-6 rounded-lg border border-white/10 bg-black p-5 text-sm leading-6 text-zinc-500">
                {dependencyQuery.data.youtube_ingest_ready
                  ? "The media runtime is ready. Uploaded videos can enter the real analysis pipeline."
                  : "FFmpeg and FFprobe are ready. Uploaded videos can enter the real analysis pipeline."}
              </div>
            </Reveal>
          ) : null}
        </section>

        <footer className="border-t border-white/10 py-8">
          <div className="flex flex-col gap-6 text-sm text-zinc-600 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="font-semibold text-zinc-400">NeuroAd Context Engine</p>
              <p className="mt-1 max-w-xl leading-6">
                Attention scoring, context extraction, and exportable video ad
                intelligence for owned or permission-cleared media.
              </p>
            </div>
            <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <a className="transition hover:text-zinc-300" href="#input-section">
                Analyze
              </a>
              <a className="transition hover:text-zinc-300" href="#section-pipeline">
                Pipeline
              </a>
              <a className="transition hover:text-zinc-300" href="#section-reports">
                Reports
              </a>
              <span className="text-zinc-700">v0.1</span>
            </nav>
          </div>
        </footer>
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
