"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/shell";
import { Card } from "@/components/ui";
import { getComparisonStatus } from "@/lib/api";

export default function ComparisonAnalyzePage() {
  const params = useParams<{ comparisonId: string }>();
  const router = useRouter();
  const statusQuery = useQuery({
    queryKey: ["comparison-status", params.comparisonId],
    queryFn: () => getComparisonStatus(params.comparisonId),
    refetchInterval: (query) => query.state.data?.status === "processing" || query.state.data?.status === "queued" ? 1200 : false
  });
  const status = statusQuery.data;

  useEffect(() => {
    if (status?.consolidated_report_ready && ["completed", "partial"].includes(status.status)) router.push(`/compare/${params.comparisonId}`);
  }, [params.comparisonId, router, status]);

  return (
    <AppShell>
      <main className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-5xl items-center px-5 py-10 lg:px-10">
        <div className="w-full">
          <p className="text-center text-sm uppercase tracking-[0.24em] text-zinc-500">Comparison in progress</p>
          <h1 className="mt-4 text-center text-4xl font-semibold text-white md:text-6xl">Building individual evidence first.</h1>
          <Card className="mt-10 border-white/10 bg-black p-6 md:p-8">
            <div className="mb-7 flex items-end justify-between gap-4">
              <div>
                <p className="text-sm text-zinc-500">Completed videos</p>
                <p className="mt-2 text-3xl font-semibold text-white">{status?.completed_videos ?? 0} / {status?.total_videos ?? 0}</p>
              </div>
              <p className="text-sm text-zinc-500">The consolidated report appears after two successful analyses.</p>
            </div>
            <div className="space-y-3">
              {(status?.videos ?? []).map((video, index) => {
                const Icon = video.status === "completed" ? CheckCircle2 : video.status === "failed" ? XCircle : video.status === "processing" ? Loader2 : Circle;
                return <div key={video.video_id} className="flex items-center justify-between gap-4 rounded-lg border border-white/10 bg-zinc-950 p-4">
                  <div className="flex items-center gap-3"><Icon className={`h-5 w-5 ${video.status === "completed" ? "text-success" : video.status === "failed" ? "text-danger" : video.status === "processing" ? "animate-spin text-white" : "text-zinc-600"}`} /><span className="font-medium text-white">Video {index + 1}</span></div>
                  <span className="text-sm text-zinc-500">{video.status === "processing" ? `${video.progress}%` : video.error ?? video.status}</span>
                </div>;
              })}
            </div>
          </Card>
        </div>
      </main>
    </AppShell>
  );
}
