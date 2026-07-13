"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, Download, FileJson, Sparkles, Trophy } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { comparisonExportUrl, formatRange, getComparison } from "@/lib/api";
import type { ComparisonVideo } from "@/lib/types";

const metricLabel: Record<string, string> = {
  attention: "Attention",
  monetization: "Monetization",
  drop_risk: "Drop risk",
  brand_safety: "Brand safety",
  visual_quality: "Visual quality",
  transcript_clarity: "Transcript clarity",
  creator_readiness: "Creator ready",
  ad_slot: "Ad-slot strength"
};

export default function ComparisonDashboardPage() {
  const params = useParams<{ comparisonId: string }>();
  const comparisonQuery = useQuery({
    queryKey: ["comparison", params.comparisonId],
    queryFn: () => getComparison(params.comparisonId),
    refetchInterval: (query) => ["queued", "processing"].includes(query.state.data?.comparison.status ?? "") ? 2500 : false
  });
  const data = comparisonQuery.data;

  if (comparisonQuery.isLoading) return <AppShell><main className="p-8 text-zinc-400">Loading comparison…</main></AppShell>;
  if (!data) return <AppShell><main className="p-8 text-danger">{comparisonQuery.error instanceof Error ? comparisonQuery.error.message : "Comparison not found."}</main></AppShell>;
  const winner = data.rankings[0];

  return (
    <AppShell>
      <main className="mx-auto max-w-7xl px-5 py-10 lg:px-10">
        <header className="flex flex-col justify-between gap-5 xl:flex-row xl:items-end">
          <div>
            <Badge tone="cyan">{data.comparison.comparison_mode === "same_category" ? "Same-category benchmark" : "Directional comparison"}</Badge>
            <h1 className="mt-4 text-4xl font-semibold text-white md:text-6xl">{data.comparison.title}</h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-400">{data.comparison.completed_videos} completed videos · Inferred category: {data.comparison.inferred_category}</p>
          </div>
          {data.rankings.length >= 2 ? <div className="flex gap-3"><a href={comparisonExportUrl(params.comparisonId, "csv")}><Button variant="secondary"><Download className="h-4 w-4" /> CSV</Button></a><a href={comparisonExportUrl(params.comparisonId, "json")}><Button variant="secondary"><FileJson className="h-4 w-4" /> JSON</Button></a></div> : null}
        </header>

        {data.caveats.length ? <div className="mt-7 flex gap-3 rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm leading-6 text-warning"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />{data.caveats.join(" ")}</div> : null}

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          <DecisionCard title="Recommended video" value={winner?.title ?? "Awaiting videos"} detail={winner ? `Score ${winner.score} · Evidence confidence ${winner.evidence_confidence}` : "At least two videos must complete."} icon={<Trophy className="h-5 w-5" />} />
          <DecisionCard title="Category position" value={winner ? `${winner.percentile}th percentile` : "—"} detail={data.comparison.comparison_mode === "same_category" ? "Relative to this comparison set" : "Cross-category ranking is directional"} icon={<Sparkles className="h-5 w-5" />} />
          <DecisionCard title="Best ad slot" value={winner?.strongest_ad_slot ? formatRange(winner.strongest_ad_slot.start, winner.strongest_ad_slot.end) : "—"} detail={winner?.strongest_ad_slot ? `Slot strength ${winner.strongest_ad_slot.score} · Ad fit ${winner.strongest_ad_slot.ad_fit_score}` : "No confident slot yet"} icon={<ArrowUpRight className="h-5 w-5" />} />
        </section>

        <section className="mt-8 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <Card className="p-6">
            <h2 className="text-2xl font-semibold text-white">Video ranking</h2>
            <div className="mt-5 space-y-3">
              {data.rankings.map((video) => <RankingRow key={video.video_id} video={video} />)}
            </div>
          </Card>
          <Card className="p-6">
            <h2 className="text-2xl font-semibold text-white">Recommended keywords</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-500">Shared category signals and high-confidence words from transcript, topic, and contextual ad evidence.</p>
            <div className="mt-5 flex flex-wrap gap-2">{data.shared_keywords.length ? data.shared_keywords.map((keyword) => <Badge key={keyword} tone="cyan">{keyword}</Badge>) : <p className="text-sm text-zinc-500">No shared keywords yet.</p>}</div>
            {winner?.keywords?.length ? <div className="mt-6 border-t border-white/10 pt-5"><p className="text-sm font-semibold text-white">Winning-video opportunities</p><div className="mt-3 flex flex-wrap gap-2">{winner.keywords.slice(0, 8).map((keyword) => <Badge key={keyword.keyword}>{keyword.keyword} · {keyword.confidence}</Badge>)}</div></div> : null}
          </Card>
        </section>

        {data.ab ? <section className="mt-8"><Card className="p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><Badge tone="cyan">A/B analysis</Badge><h2 className="mt-3 text-2xl font-semibold text-white">Overall result: {data.ab.winner === "tie" ? "No clear winner" : `Video ${data.ab.winner} wins`}</h2></div><p className="text-sm text-zinc-500">Evidence confidence {data.ab.confidence}</p></div><div className="mt-6 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="border-b border-white/10 text-zinc-500"><tr><th className="pb-3 font-medium">Metric</th><th className="pb-3 font-medium">Video A</th><th className="pb-3 font-medium">Video B</th><th className="pb-3 font-medium">Delta</th><th className="pb-3 font-medium">Result</th></tr></thead><tbody>{data.ab.deltas.map((delta) => <tr key={delta.metric} className="border-b border-white/5 text-zinc-200"><td className="py-3">{metricLabel[delta.metric] ?? delta.metric}</td><td>{delta.video_a}</td><td>{delta.video_b}</td><td>{delta.delta > 0 ? "+" : ""}{delta.delta}</td><td>{delta.winner === "tie" ? "Tie" : `Video ${delta.winner}`}</td></tr>)}</tbody></table></div></Card></section> : null}

        <section className="mt-8 grid gap-5 xl:grid-cols-2">
          <Card className="p-6"><h2 className="text-2xl font-semibold text-white">Strongest ad slots</h2><div className="mt-5 space-y-3">{data.rankings.map((video) => <AdSlotRow key={video.video_id} video={video} />)}</div></Card>
          <Card className="p-6"><h2 className="text-2xl font-semibold text-white">Decision evidence</h2><div className="mt-5 space-y-4">{data.recommendations.map((recommendation) => <div key={`${recommendation.title}-${recommendation.timestamp ?? ""}`} className="border-l-2 border-white/20 pl-4"><p className="font-medium text-white">{recommendation.title}</p><p className="mt-1 text-sm leading-6 text-zinc-400">{recommendation.body}</p></div>)}</div></Card>
        </section>
      </main>
    </AppShell>
  );
}

function DecisionCard({ title, value, detail, icon }: { title: string; value: string; detail: string; icon: React.ReactNode }) {
  return <Card className="p-5"><div className="flex items-center justify-between text-zinc-500"><p className="text-sm font-medium">{title}</p>{icon}</div><p className="mt-4 text-2xl font-semibold text-white">{value}</p><p className="mt-2 text-sm leading-6 text-zinc-500">{detail}</p></Card>;
}

function RankingRow({ video }: { video: ComparisonVideo }) {
  return <div className="rounded-lg border border-white/10 bg-zinc-950 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm text-zinc-500">Rank #{video.rank} · {video.category}</p><p className="mt-1 font-semibold text-white">{video.title}</p></div><Badge tone={video.rank === 1 ? "success" : "default"}>{video.score}</Badge></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-white" style={{ width: `${video.normalized_score ?? 0}%` }} /></div><div className="mt-3 flex flex-wrap justify-between gap-2 text-xs text-zinc-500"><span>{video.percentile}th percentile</span><span>Evidence {video.evidence_confidence}</span>{video.individual_report_url ? <Link href={video.individual_report_url} className="text-zinc-200 hover:text-white">Open report →</Link> : null}</div></div>;
}

function AdSlotRow({ video }: { video: ComparisonVideo }) {
  const slot = video.strongest_ad_slot;
  return <div className="rounded-lg border border-white/10 bg-zinc-950 p-4"><div className="flex items-center justify-between gap-3"><div><p className="font-medium text-white">{video.title}</p><p className="mt-1 text-sm text-zinc-500">{slot ? formatRange(slot.start, slot.end) : "No confident ad slot"}</p></div>{slot ? <Badge tone={slot.score >= 75 ? "success" : "warning"}>{slot.score}</Badge> : null}</div>{slot?.reasons?.length ? <p className="mt-3 text-xs leading-5 text-zinc-500">{slot.reasons.slice(0, 3).join(" · ")}</p> : null}</div>;
}
