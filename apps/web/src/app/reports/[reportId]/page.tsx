"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Badge, Card } from "@/components/ui";
import { formatRange, getAnalysis } from "@/lib/api";

export default function ReportPage() {
  const params = useParams<{ reportId: string }>();
  const reportId = params.reportId;
  const analysisQuery = useQuery({
    queryKey: ["report-analysis", reportId],
    queryFn: () => getAnalysis(reportId)
  });

  const analysis = analysisQuery.data;

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl px-5 py-8 lg:px-10">
        <Badge tone="cyan">Recommendation Report</Badge>
        <h1 className="mt-4 text-4xl font-semibold">{analysis?.video.title ?? "Loading report..."}</h1>
        {analysis ? (
          <div className="mt-8 space-y-5">
            <Card className="p-6">
              <h2 className="text-xl font-semibold">Executive summary</h2>
              <p className="mt-3 text-slate-400">
                Overall Attention Proxy Score is {analysis.summary.overall_attention_score}. Top ad category is{" "}
                {analysis.summary.top_ad_category}. The best ad slot is{" "}
                {analysis.summary.best_ad_slot
                  ? formatRange(analysis.summary.best_ad_slot.start, analysis.summary.best_ad_slot.end)
                  : "not available"}
                .
              </p>
            </Card>
            {analysis.recommendations.map((item) => (
              <Card key={`${item.title}-${item.timestamp}`} className="p-6">
                <Badge>{item.timestamp}</Badge>
                <h2 className="mt-4 text-xl font-semibold">{item.title}</h2>
                <p className="mt-3 leading-7 text-slate-400">{item.body}</p>
              </Card>
            ))}
          </div>
        ) : (
          <p className="mt-8 text-slate-400">{analysisQuery.error?.message ?? "Loading..."}</p>
        )}
      </div>
    </AppShell>
  );
}
