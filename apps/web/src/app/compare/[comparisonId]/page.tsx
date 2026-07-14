"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, BarChart3, CircleCheckBig, Download, FileJson, GitCompareArrows, Lightbulb, PlayCircle, Scale, Trophy } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { comparisonExportUrl, formatRange, getComparison } from "@/lib/api";
import type { ComparisonVideo } from "@/lib/types";

const metricLabel: Record<string, string> = {
  attention: "Viewer attention",
  monetization: "Campaign opportunity",
  drop_risk: "Viewer drop risk",
  brand_safety: "Brand safety",
  visual_quality: "Visual clarity",
  transcript_clarity: "Speech clarity",
  creator_readiness: "Campaign readiness",
  ad_slot: "Best ad moment"
};

const metricHelp: Record<string, string> = {
  attention: "How likely people are to stay interested.",
  monetization: "How ready the video looks for a campaign opportunity.",
  drop_risk: "How likely people are to lose interest. Lower is better.",
  brand_safety: "How safe the content looks for a brand.",
  visual_quality: "How clear and usable the visuals look.",
  transcript_clarity: "How clearly the spoken words were understood.",
  creator_readiness: "How close the video is to being campaign-ready.",
  ad_slot: "How natural the best ad moment looks."
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
  const runnerUp = data.rankings[1];
  const scoreGap = winner && runnerUp ? Math.max(0, (winner.score ?? 0) - (runnerUp.score ?? 0)) : 0;
  const bestSlot = winner?.strongest_ad_slot;

  return (
    <AppShell>
      <main className="mx-auto max-w-7xl px-5 py-10 lg:px-10">
        <header className="flex flex-col justify-between gap-5 xl:flex-row xl:items-end">
          <div>
            <div className="flex flex-wrap gap-2"><Badge tone="cyan">{data.comparison.comparison_mode === "same_category" ? "Same-category comparison" : "Video comparison"}</Badge><Badge tone="cyan">Beta</Badge></div>
            <h1 className="mt-4 text-4xl font-semibold text-white md:text-6xl">{titleCase(data.comparison.title)}</h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-400">{data.comparison.completed_videos} videos ready · Category: {data.comparison.inferred_category}</p>
          </div>
          {data.rankings.length >= 2 ? <div className="flex gap-3"><a href={comparisonExportUrl(params.comparisonId, "csv")}><Button variant="secondary"><Download className="h-4 w-4" /> CSV</Button></a><a href={comparisonExportUrl(params.comparisonId, "json")}><Button variant="secondary"><FileJson className="h-4 w-4" /> JSON</Button></a></div> : null}
        </header>

        {data.caveats.length ? <div className="mt-7 flex gap-3 rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm leading-6 text-warning"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />These videos are from different categories. Use this result to choose the stronger video in this upload set, not to decide which category is best overall.</div> : null}

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          <DecisionCard title="Best overall choice" value={winner ? displayTitle(winner.title) : "Awaiting videos"} detail={winner ? `${scoreLabel(winner.score ?? 0)} result: ${winner.score}/100. This is the strongest of your ${data.rankings.length} uploads.` : "At least two videos must complete."} icon={<Trophy className="h-5 w-5" />} score={winner?.score} />
          <DecisionCard title="Why it ranked first" value={winner && runnerUp ? `${scoreGap} points ahead` : "—"} detail={winner && runnerUp ? `${displayTitle(winner.title)} scored ${winner.score}/100. The next video scored ${runnerUp.score}/100.` : "A comparison needs at least two completed videos."} icon={<GitCompareArrows className="h-5 w-5" />} score={winner && runnerUp ? scoreGap : undefined} />
          <DecisionCard title="Ad placement check" value={bestSlot ? slotLabel(bestSlot.score) : "Not ready"} detail={bestSlot ? `Best time: ${formatRange(bestSlot.start, bestSlot.end)}. Placement score ${bestSlot.score}/100 — review the clip before approval.` : "No suitable ad moment was found yet."} icon={<CircleCheckBig className="h-5 w-5" />} score={bestSlot?.score} />
        </section>

        <section className="mt-8 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <ComparisonScoreboard rankings={data.rankings} />
          <Card className="min-w-0 p-6">
            <div className="flex flex-wrap items-center gap-2"><Lightbulb className="h-5 w-5 text-warning" /><h2 className="text-2xl font-semibold text-white">Ideas for the next version</h2><Badge tone="cyan">Beta</Badge></div>
            <p className="mt-2 text-sm leading-6 text-zinc-500">Use the strongest video as a starting point, then improve the weak areas shown below.</p>
            <div className="mt-5 flex flex-wrap gap-2">{data.shared_keywords.length ? data.shared_keywords.map((keyword) => <Badge key={keyword} tone="cyan">{keyword}</Badge>) : <p className="text-sm text-zinc-500">No shared keywords yet.</p>}</div>
            {winner?.keywords?.filter((keyword) => keyword.type === "content").length ? <div className="mt-6 border-t border-white/10 pt-5"><p className="text-sm font-semibold text-white">Main topic in the top video</p><div className="mt-3 flex flex-wrap gap-2">{winner.keywords.filter((keyword) => keyword.type === "content").slice(0, 4).map((keyword) => <Badge key={keyword.keyword}>{keyword.keyword}</Badge>)}</div></div> : null}
            <DashboardNote title="Next step" body="Use the top video as your starting point. Its score is still low, so improve the hook, visuals, or pacing before using it in a campaign." />
          </Card>
        </section>

        <section className="mt-8"><MetricComparison metrics={data.metric_comparison} rankings={data.rankings} /></section>

        {data.ab ? <section className="mt-8"><Card className="min-w-0 p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex flex-wrap gap-2"><Badge tone="cyan">A/B comparison</Badge><Badge tone="cyan">Beta</Badge></div><h2 className="mt-3 text-2xl font-semibold text-white">Overall result: {data.ab.winner === "tie" ? "No clear winner" : `Video ${data.ab.winner} wins`}</h2></div><p className="text-sm text-zinc-500">Confidence {data.ab.confidence}</p></div><div className="mt-6 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="border-b border-white/10 text-zinc-500"><tr><th className="pb-3 font-medium">What we checked</th><th className="pb-3 font-medium">Video A</th><th className="pb-3 font-medium">Video B</th><th className="pb-3 font-medium">Difference</th><th className="pb-3 font-medium">Result</th></tr></thead><tbody>{data.ab.deltas.map((delta) => <tr key={delta.metric} className="border-b border-white/5 text-zinc-200"><td className="py-3">{metricLabel[delta.metric] ?? delta.metric}</td><td>{delta.video_a}</td><td>{delta.video_b}</td><td>{delta.delta > 0 ? "+" : ""}{delta.delta}</td><td>{delta.winner === "tie" ? "Tie" : `Video ${delta.winner}`}</td></tr>)}</tbody></table></div></Card></section> : null}

        <section className="mt-8 grid gap-5 xl:grid-cols-2">
          <Card className="min-w-0 p-6"><div className="flex flex-wrap items-center gap-2"><ArrowUpRight className="h-5 w-5 text-success" /><h2 className="text-2xl font-semibold text-white">Best moments for an ad</h2><Badge tone="cyan">Beta</Badge></div><p className="mt-2 text-sm leading-6 text-zinc-500">These are the points where the content is most likely to support a natural ad break.</p><div className="mt-5 space-y-3">{data.rankings.map((video) => <AdSlotRow key={video.video_id} video={video} />)}</div><DashboardNote title="How to use this" body="Open the individual report to review the exact clip before approving a placement." /></Card>
          <ComparisonExplanation winner={winner} runnerUp={runnerUp} metrics={data.metric_comparison} />
        </section>
      </main>
    </AppShell>
  );
}

function DecisionCard({ title, value, detail, icon, score }: { title: string; value: string; detail: string; icon: React.ReactNode; score?: number }) {
  const tone = score === undefined ? "cyan" : scoreTone(score);
  const iconColors = {
    success: "border-success/25 bg-success/10 text-success shadow-[0_0_24px_rgba(34,197,94,0.12)]",
    warning: "border-warning/25 bg-warning/10 text-warning shadow-[0_0_24px_rgba(245,158,11,0.12)]",
    danger: "border-danger/25 bg-danger/10 text-danger shadow-[0_0_24px_rgba(239,68,68,0.12)]",
    cyan: "border-white/15 bg-white/[0.06] text-white shadow-[0_0_24px_rgba(255,255,255,0.08)]"
  };
  return <Card className="min-w-0 p-5"><div className="flex min-w-0 items-center justify-between gap-3"><p className="text-sm font-medium text-zinc-500">{title}</p><span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${iconColors[tone]}`}>{icon}</span></div><p className="mt-4 break-words text-2xl font-semibold text-white">{value}</p><p className="mt-2 break-words text-sm leading-6 text-zinc-500">{detail}</p>{score !== undefined ? <div className="mt-4"><ScorePill score={score} /></div> : null}</Card>;
}

function ComparisonScoreboard({ rankings }: { rankings: ComparisonVideo[] }) {
  return (
    <Card className="min-w-0 overflow-hidden p-6">
      <div className="flex flex-wrap items-center gap-2"><BarChart3 className="h-5 w-5 text-zinc-200" /><h2 className="text-2xl font-semibold text-white">Which video is strongest?</h2><Badge tone="cyan">Beta</Badge></div>
      <p className="mt-2 text-sm leading-6 text-zinc-500">Every bar uses the same 0–100 scale. 70+ is strong, 40–69 needs review, and below 40 needs improvement.</p>
      <div className="mt-5 space-y-4">
        {rankings.map((video) => {
          const score = video.score ?? 0;
          const width = Math.max(3, Math.round(score));
          return (
            <div key={video.video_id} className="min-w-0 rounded-lg border border-white/10 bg-zinc-950 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3"><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-sm font-semibold text-zinc-200">{video.rank ?? "—"}</span><div className="min-w-0"><p className="break-words font-semibold text-white">{displayTitle(video.title)}</p><p className="mt-1 text-xs text-zinc-500">{video.category ?? "Category still being identified"} · Result reliability: {confidenceLabel(video.evidence_confidence ?? 0)}</p></div></div>
                <ScorePill score={score} />
              </div>
              <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-gradient-to-r from-danger/20 via-warning/20 to-success/20"><div className={`h-full rounded-full ${barColor(score)}`} style={{ width: `${width}%` }} /></div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-500"><span>{video.rank === 1 ? "Best of your uploads" : `Rank ${video.rank} of ${rankings.length}`} · {scoreLabel(score)}</span>{video.individual_report_url ? <Link href={video.individual_report_url} className="inline-flex items-center gap-1 text-zinc-100 hover:text-white"><PlayCircle className="h-4 w-4" /> Open video report</Link> : null}</div>
            </div>
          );
        })}
      </div>
      <DashboardNote title="What this means" body="The first video is the strongest choice from these uploads. If its score is below 40, treat it as a starting point to improve — not a final campaign-ready video." />
    </Card>
  );
}

function MetricComparison({ metrics, rankings }: { metrics: Array<{ metric: string; values: Array<{ video_id: string; value: number; rank: number }> }>; rankings: ComparisonVideo[] }) {
  const videoById = new Map(rankings.map((video) => [video.video_id, video]));
  const visibleMetrics = metrics.filter((metric) => metric.values.length).slice(0, 8);
  return (
    <Card className="min-w-0 overflow-hidden p-6">
      <div className="flex flex-wrap items-center gap-2"><Scale className="h-5 w-5 text-zinc-200" /><h2 className="text-2xl font-semibold text-white">What made one video better?</h2><Badge tone="cyan">Beta</Badge></div>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-500">Each row checks one part of the video. Longer bars are better, except for viewer drop risk — lower is better there.</p>
      {visibleMetrics.length ? <div className="mt-6 space-y-5">{visibleMetrics.map((metric) => {
        const isRisk = metric.metric === "drop_risk";
        return <div key={metric.metric} className="rounded-lg border border-white/10 bg-zinc-950 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold text-white">{metricLabel[metric.metric] ?? metric.metric}</p><p className="mt-1 text-xs leading-5 text-zinc-500">{metricHelp[metric.metric] ?? "A comparison of this signal across your uploads."}</p></div><Badge tone={isRisk ? "warning" : "default"}>{isRisk ? "Lower is better" : "Higher is better"}</Badge></div><div className="mt-4 space-y-3">{metric.values.map((value) => {
          const video = videoById.get(value.video_id);
          const width = Math.max(3, Math.round(value.value));
          const tone = metricScoreTone(metric.metric, value.value);
          return <div key={value.video_id} className="grid min-w-0 gap-2 sm:grid-cols-[minmax(110px,0.32fr)_minmax(0,1fr)_56px]"><span className="truncate text-sm text-zinc-400" title={video?.title}>{displayTitle(video?.title ?? `Video ${value.rank}`)}</span><div className="h-6 overflow-hidden rounded-md bg-gradient-to-r from-danger/20 via-warning/20 to-success/20"><div className={`h-full rounded-md ${barColorForTone(tone)}`} style={{ width: `${width}%` }} /></div><span className={`text-right text-sm font-semibold ${numberColorForTone(tone)}`}>{Math.round(value.value)}/100</span></div>;
        })}</div></div>;
      })}</div> : <p className="mt-6 rounded-lg border border-white/10 bg-zinc-950 p-4 text-sm text-zinc-500">Metric-by-metric comparison will appear when individual video analyses are complete.</p>}
      <DashboardNote title="Next step" body="Look for the biggest gap. Open that video’s report, keep what worked, and improve the weaker parts in the next edit." />
    </Card>
  );
}

function ComparisonExplanation({ winner, runnerUp, metrics }: { winner?: ComparisonVideo; runnerUp?: ComparisonVideo; metrics: Array<{ metric: string; values: Array<{ video_id: string; value: number; rank: number }> }> }) {
  if (!winner) return null;
  const winnerMetrics = winner.metrics ?? {};
  const comparisonMetrics = ["attention", "visual_quality", "ad_slot"]
    .map((metric) => {
      const nextValue = runnerUp?.metrics?.[metric] ?? 0;
      const winnerValue = winnerMetrics[metric] ?? 0;
      return { metric, winnerValue, nextValue, gap: winnerValue - nextValue };
    })
    .filter((item) => item.gap > 0)
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 3);
  const lowReliability = (winner.evidence_confidence ?? 0) < 45;
  const bestSlot = winner.strongest_ad_slot;

  return (
    <Card className="min-w-0 p-6">
      <div className="flex flex-wrap items-center gap-2"><Scale className="h-5 w-5 text-zinc-200" /><h2 className="text-2xl font-semibold text-white">What this result means</h2><Badge tone="cyan">Beta</Badge></div>
      <p className="mt-2 text-sm leading-6 text-zinc-500">A simple explanation of the result and the safest next action.</p>
      <div className="mt-5 space-y-4">
        <ExplanationRow number="1" title="Best choice right now" body={`${displayTitle(winner.title)} is the strongest of these uploads with ${winner.score ?? 0}/100. ${runnerUp ? `It is ${Math.max(0, (winner.score ?? 0) - (runnerUp.score ?? 0))} points ahead of ${displayTitle(runnerUp.title)}.` : ""}`} />
        <ExplanationRow number="2" title="What helped it" body={comparisonMetrics.length ? comparisonMetrics.map((item) => `${metricLabel[item.metric]} was ${Math.round(item.winnerValue)} vs ${Math.round(item.nextValue)}`).join("; ") + "." : "It had the strongest combined result across the available checks."} />
        <ExplanationRow number="3" title="What to be careful about" body={lowReliability ? `The result reliability is ${confidenceLabel(winner.evidence_confidence ?? 0)}. Check the individual report before making a final campaign decision.` : "The evidence is clear enough for a normal review, but the individual report should still be checked before approval."} />
        <ExplanationRow number="4" title="Recommended next action" body={bestSlot ? `${slotLabel(bestSlot.score)}: review ${formatRange(bestSlot.start, bestSlot.end)} in the individual report. ${bestSlot.score >= 60 ? "It may be worth testing as an ad break." : "Do not approve this ad break until the clip is reviewed and improved if needed."}` : "Open the top video report, improve the weak moments, and analyse the new version again."} />
      </div>
      {metrics.length ? <DashboardNote title="Important" body="These numbers compare the videos you uploaded. They do not replace a human review of the video, brand, or final ad placement." /> : null}
    </Card>
  );
}

function ExplanationRow({ number, title, body }: { number: string; title: string; body: string }) {
  return <div className="flex gap-3 rounded-lg border border-white/10 bg-zinc-950 p-4"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-sm font-semibold text-black">{number}</span><div className="min-w-0"><p className="font-semibold text-white">{title}</p><p className="mt-1 break-words text-sm leading-6 text-zinc-400">{body}</p></div></div>;
}

function DashboardNote({ title, body }: { title: string; body: string }) {
  return <div className="mt-5 flex gap-3 rounded-lg border border-white/10 bg-white/[0.03] p-4"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warning" /><div><p className="text-sm font-semibold text-white">{title}</p><p className="mt-1 break-words text-sm leading-6 text-zinc-400">{body}</p></div></div>;
}

function displayTitle(title: string) {
  const cleaned = title.replace(/[_-]+/g, " ").replace(/\b\d{8,}\b/g, "").replace(/\s+/g, " ").trim();
  return cleaned || title;
}

function scoreLabel(score: number) {
  if (score >= 70) return "Strong";
  if (score >= 40) return "Needs review";
  return "Needs improvement";
}

function scoreTone(score: number): "success" | "warning" | "danger" {
  if (score >= 70) return "success";
  if (score >= 40) return "warning";
  return "danger";
}

function metricScoreTone(metric: string, score: number): "success" | "warning" | "danger" {
  if (metric === "drop_risk") {
    if (score <= 25) return "success";
    if (score <= 50) return "warning";
    return "danger";
  }
  return scoreTone(score);
}

function barColorForTone(tone: "success" | "warning" | "danger") {
  return tone === "success" ? "bg-success shadow-[0_0_14px_rgba(34,197,94,0.45)]" : tone === "warning" ? "bg-warning shadow-[0_0_14px_rgba(245,158,11,0.38)]" : "bg-danger shadow-[0_0_14px_rgba(239,68,68,0.38)]";
}

function barColor(score: number) {
  return barColorForTone(scoreTone(score));
}

function numberColorForTone(tone: "success" | "warning" | "danger") {
  return tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : "text-danger";
}

function ScorePill({ score }: { score: number }) {
  const tone = scoreTone(score);
  const classes = tone === "success" ? "border-success/30 bg-success/10 text-success" : tone === "warning" ? "border-warning/30 bg-warning/10 text-warning" : "border-danger/30 bg-danger/10 text-danger";
  return <span className={`inline-flex items-center rounded-md border px-2.5 py-1 text-sm font-semibold ${classes}`}>{Math.round(score)}/100</span>;
}

function confidenceLabel(confidence: number) {
  if (confidence >= 70) return `high (${Math.round(confidence)}/100)`;
  if (confidence >= 45) return `medium (${Math.round(confidence)}/100)`;
  return `low (${Math.round(confidence)}/100)`;
}

function slotLabel(score: number) {
  if (score >= 75) return "Good to test";
  if (score >= 60) return "Worth reviewing";
  return "Needs review";
}

function titleCase(value: string) {
  return value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function AdSlotRow({ video }: { video: ComparisonVideo }) {
  const slot = video.strongest_ad_slot;
  return <div className="min-w-0 rounded-lg border border-white/10 bg-zinc-950 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><p className="break-words font-medium text-white">{displayTitle(video.title)}</p><p className="mt-1 text-sm text-zinc-500">{slot ? formatRange(slot.start, slot.end) : "No clear moment yet"}</p></div>{slot ? <ScorePill score={slot.score} /> : null}</div>{slot?.reasons?.length ? <p className="mt-3 break-words text-xs leading-5 text-zinc-500">{slot.reasons.slice(0, 3).join(" · ")}</p> : null}{video.individual_report_url ? <Link href={video.individual_report_url} className="mt-3 inline-flex text-sm text-zinc-200 hover:text-white">Review this video →</Link> : null}</div>;
}
