"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, FileText, LoaderCircle, Sparkles } from "lucide-react";
import { createComparisonInsightReport, createVideoInsightReport, getInsightJob } from "@/lib/api";
import type { DetailedInsightReportStatus } from "@/lib/types";
import { Button, Card } from "@/components/ui";

const stages = [
  ["queued", "Queued"],
  ["preparing_evidence", "Preparing evidence"],
  ["generating", "Generating with GPT-OSS"],
  ["validating", "Validating grounded evidence"],
  ["publishing", "Publishing dashboard"],
] as const;

export function InsightReportLauncher({ targetType, targetId, initial }: { targetType: "video" | "comparison"; targetId: string; initial?: DetailedInsightReportStatus | null }) {
  const [state, setState] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const busy = state?.status === "queued" || state?.status === "processing";
  useEffect(() => {
    if (!busy || !state?.job_id) return;
    const timer = window.setInterval(async () => {
      try {
        const job = await getInsightJob(state.job_id!);
        setError(null);
        setState({ report_id: job.report_id, job_id: job.id, status: job.status, progress: job.progress, stage: job.stage, attempts: job.attempts, created_at: job.created_at, updated_at: job.updated_at, error: job.error, report_url: job.report_url });
      } catch (err) { setError(err instanceof Error ? err.message : "Could not check report status."); }
    }, 2200);
    return () => window.clearInterval(timer);
  }, [busy, state?.job_id]);
  async function start() {
    setError(null);
    try {
      const result = targetType === "video" ? await createVideoInsightReport(targetId) : await createComparisonInsightReport(targetId);
      setState({ report_id: result.report_id, job_id: result.job_id, status: result.status, progress: result.progress, stage: result.stage, report_url: result.report_url });
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start the report."); }
  }
  if (state?.status === "completed") return <Card className="mt-8 flex flex-wrap items-center justify-between gap-4 p-5"><div><p className="font-semibold text-white">Detailed Insight Report ready</p><p className="mt-1 text-sm text-zinc-400">Explore GPT-OSS findings, brand prospects, placements, and creative actions in the dashboard.</p></div><Link href={`/insights/${state.report_id}`}><Button><FileText className="h-4 w-4" /> View Detailed Report</Button></Link></Card>;
  const progress = Math.max(0, Math.min(100, state?.progress ?? 0));
  const currentStage = state?.stage ?? "queued";
  const currentIndex = stages.findIndex(([key]) => key === currentStage);
  return <Card className="mt-8 overflow-hidden p-0">
    <div className="border-b border-white/10 bg-white/[0.02] p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="font-semibold text-white">Detailed Insight Report</p><p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">Uses GPT-OSS with your transcript, on-screen text, objects, topics, and score evidence. Brand prospects are exploratory and must be independently verified.</p><p className="mt-2 text-xs leading-5 text-cyan">Beta: report generation can take a few minutes, especially for multi-video comparisons or a RunPod cold start.</p></div>
        <Button onClick={start} disabled={busy}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{busy ? "Generating report" : state?.status === "failed" ? "Retry Detailed Report" : "Generate Detailed Insight Report"}</Button>
      </div>
      {busy ? <div className="mt-5"><div className="flex items-center justify-between text-sm"><span className="font-medium text-white">{stageMessage(currentStage)}</span><span className="tabular-nums text-cyan">{progress}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-cyan via-blue-400 to-violet-400 transition-[width] duration-500" style={{ width: `${Math.max(3, progress)}%` }} /></div><p className="mt-2 text-xs leading-5 text-zinc-500">You can leave this page; progress is saved and resumes after a Railway restart. A RunPod cold start can take a few minutes.</p></div> : null}
    </div>
    {busy ? <div className="grid gap-2 p-5 sm:grid-cols-2 lg:grid-cols-5">{stages.map(([key, label], index) => <div key={key} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${index < currentIndex ? "border-success/30 bg-success/10 text-success" : index === currentIndex ? "border-cyan/30 bg-cyan/10 text-cyan" : "border-white/10 text-zinc-500"}`}>{index < currentIndex ? <Check className="h-3.5 w-3.5" /> : index === currentIndex ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <span className="h-2 w-2 rounded-full bg-current opacity-60" />}{label}</div>)}</div> : null}
    {error || state?.error ? <div className="m-5 rounded-md border border-danger/30 bg-danger/10 p-3"><p className="text-sm font-semibold text-danger">Detailed report failed</p><p className="mt-1 text-sm leading-6 text-red-200">{state?.error ?? error}</p><p className="mt-2 text-xs text-zinc-400">Open Railway logs and search for “Insight job failed” for the full technical trace. No API key or prompt content is included in the UI error.</p></div> : null}
  </Card>;
}

function stageMessage(stage: string) {
  if (stage === "queued") return "Waiting for the report worker";
  if (stage === "preparing_evidence") return "Preparing grounded video evidence";
  if (stage === "generating") return "GPT-OSS is generating the report";
  if (stage === "validating") return "Checking citations, timestamps, and scores";
  if (stage === "publishing") return "Publishing your interactive report dashboard";
  return "Preparing your insight report";
}
