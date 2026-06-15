"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/shell";
import { Card } from "@/components/ui";
import { getJob, startAnalysis } from "@/lib/api";

const steps = [
  ["metadata", "Ingest media"],
  ["frames", "Extract frames"],
  ["audio", "Read audio"],
  ["transcript", "Build transcript"],
  ["objects", "Detect objects"],
  ["topics", "Map topics"],
  ["attention", "Score attention"],
  ["ad_scoring", "Match ads"],
  ["report", "Generate report"]
] as const;

const stepDescriptions: Record<string, string> = {
  metadata: "Preparing the source video and reading duration, title, thumbnail, and media metadata.",
  frames: "Sampling visual frames and segment thumbnails for scene-level understanding.",
  audio: "Extracting a 16kHz mono audio track and measuring energy across the timeline.",
  transcript: "Transcribing speech with timestamps and aligning it to video segments.",
  objects: "Running object detection on sampled frames and keeping the strongest detections.",
  topics: "Classifying transcript and context into creator and ad-relevant topics.",
  attention: "Combining visual novelty, object clarity, audio, speech density, and topic signals.",
  ad_scoring: "Ranking contextual ad opportunities and avoid-ad zones per segment.",
  report: "Packaging the dashboard payload and export files."
};

export default function AnalyzePage() {
  const params = useParams<{ videoId: string }>();
  const router = useRouter();
  const videoId = params.videoId;

  const startMutation = useMutation({ mutationFn: () => startAnalysis(videoId) });

  useEffect(() => {
    startMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const jobId = startMutation.data?.job_id;
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 1200;
    }
  });

  const job = jobQuery.data;
  const progress = job?.progress ?? (startMutation.isPending ? 3 : 0);
  const currentStep = job?.current_step ?? "metadata";
  const currentIndex = Math.max(0, steps.findIndex(([key]) => key === currentStep));

  useEffect(() => {
    if (job?.status === "completed") {
      router.push(`/dashboard/${videoId}`);
    }
  }, [job?.status, router, videoId]);

  return (
    <AppShell>
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-6xl items-center px-5 py-10 lg:px-10">
        <div className="w-full">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm uppercase tracking-[0.24em] text-zinc-500">Analysis in progress</p>
            <h1 className="mt-4 text-4xl font-semibold leading-tight text-white md:text-6xl">Building your context timeline</h1>
            <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-zinc-400">
              Keep this page open while NeuroAd Context Engine ingests the video, reads the media, scores each segment, and prepares the dashboard.
            </p>
          </div>

          <Card className="mt-10 overflow-hidden border-white/10 bg-black">
            <div className="border-b border-white/10 p-6 md:p-8">
              <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
                <div>
                  <p className="text-sm text-zinc-500">Current step</p>
                  <h2 className="mt-2 text-2xl font-semibold text-white md:text-3xl">
                    {steps[currentIndex]?.[1] ?? "Preparing"}
                  </h2>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-500">
                    {stepDescriptions[currentStep] ?? "Starting the worker and preparing analysis."}
                  </p>
                </div>
                <div className="text-left md:text-right">
                  <p className="text-5xl font-semibold text-white">{progress}%</p>
                  <p className="mt-1 text-sm text-zinc-500">complete</p>
                </div>
              </div>

              <div className="mt-7 h-3 overflow-hidden rounded-full bg-zinc-900">
                <div className="h-full bg-white transition-all duration-500" style={{ width: `${Math.max(4, progress)}%` }} />
              </div>
            </div>

            <div className="grid gap-px bg-white/10 md:grid-cols-3">
              {steps.map(([key, label], index) => {
                const done = job?.status === "completed" || index < currentIndex;
                const active = key === currentStep && job?.status !== "failed";
                const failed = key === currentStep && job?.status === "failed";
                return (
                  <div key={key} className="bg-black p-5">
                    <div className="flex items-center gap-3">
                      {failed ? (
                        <XCircle className="h-5 w-5 text-danger" />
                      ) : done ? (
                        <CheckCircle2 className="h-5 w-5 text-success" />
                      ) : active ? (
                        <Loader2 className="h-5 w-5 animate-spin text-white" />
                      ) : (
                        <Circle className="h-5 w-5 text-zinc-700" />
                      )}
                      <span className={active ? "font-medium text-white" : done ? "text-zinc-200" : "text-zinc-500"}>{label}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {job?.status === "failed" ? (
            <div className="mt-6 rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {job.error ?? "Analysis failed."}
            </div>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}
