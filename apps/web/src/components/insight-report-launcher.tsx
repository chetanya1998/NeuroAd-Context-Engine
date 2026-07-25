"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FileText, LoaderCircle, Sparkles } from "lucide-react";
import { createComparisonInsightReport, createVideoInsightReport, getInsightJob } from "@/lib/api";
import type { DetailedInsightReportStatus } from "@/lib/types";
import { Button, Card } from "@/components/ui";

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
        setState({ report_id: job.report_id, job_id: job.id, status: job.status, progress: job.progress, stage: job.stage, error: job.error, report_url: job.report_url });
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
  if (state?.status === "completed") return <Card className="mt-8 flex flex-wrap items-center justify-between gap-4 p-5"><div><p className="font-semibold text-white">Detailed Insight Report ready</p><p className="mt-1 text-sm text-zinc-400">Validated GPT-OSS evidence, brand prospects, placements, and exports.</p></div><Link href={`/insights/${state.report_id}`}><Button><FileText className="h-4 w-4" /> View Detailed Report</Button></Link></Card>;
  return <Card className="mt-8 p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="font-semibold text-white">Detailed Insight Report</p><p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">Uses GPT-OSS with your transcript, on-screen text, objects, topics, and score evidence. A cold start can take a few minutes. Brand prospects are exploratory and must be independently verified.</p></div><Button onClick={start} disabled={busy}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{busy ? `${state?.stage ?? "queued"} ${state?.progress ?? 0}%` : state?.status === "failed" ? "Retry Detailed Report" : "Generate Detailed Insight Report"}</Button></div>{busy ? <p className="mt-3 text-xs text-zinc-500">Stage: {state.stage ?? "queued"} · progress {state.progress ?? 0}%</p> : null}{error || state?.error ? <div className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3"><p className="text-sm font-semibold text-danger">Detailed report failed</p><p className="mt-1 text-sm leading-6 text-red-200">{state?.error ?? error}</p><p className="mt-2 text-xs text-zinc-400">Open Railway logs and search for “Insight job failed” for the full technical trace. No API key or prompt content is included in the UI error.</p></div> : null}</Card>;
}
