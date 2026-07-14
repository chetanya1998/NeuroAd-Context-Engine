"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleHelp, Download, Eye, FileJson, FileText, Search, ShieldCheck, TrendingDown, TrendingUp, Zap } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
  ZAxis
} from "recharts";
import { AttentionTimeline } from "@/components/attention-timeline";
import { BrandFitPanel } from "@/components/brand-fit-panel";
import { SegmentDrawer } from "@/components/segment-drawer";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { absoluteMediaUrl, exportUrl, formatRange, getAnalysis } from "@/lib/api";
import type { AnalysisPayload, RecommendationTier, Segment } from "@/lib/types";

const tabs = ["Segments", "Objects", "Transcript", "Evidence", "Ad Matches", "Recommendations"] as const;

const metricGuides: Record<string, { definition: string; example: string }> = {
  "Overall Attention": {
    definition: "How likely the video is to hold attention, based on pace, movement, and clarity.",
    example: "A clear opening with movement and useful speech usually scores higher."
  },
  Monetization: {
    definition: "How ready the video is for an ad opportunity, based on its best moments and safety checks.",
    example: "A clear, safe tutorial can create more opportunities than an unclear video."
  },
  "Creator Ready": {
    definition: "How close the video is to being ready for a campaign review.",
    example: "Clear speech, good visuals, and fewer weak moments make this stronger."
  },
  "Brand Safety": {
    definition: "How suitable the video appears for brands after checking for risky claims and context.",
    example: "Unverified promises can lower this score."
  },
  "Drop Risk": {
    definition: "Where viewers may lose interest because a moment is slow, repetitive, quiet, or unclear.",
    example: "Long silent moments can increase this score."
  },
  "Visual Quality": {
    definition: "How clear and usable the video looks in the sampled frames.",
    example: "Sharp, well-lit scenes score higher than dark or blurry ones."
  },
  "Transcript Confidence": {
    definition: "How confidently the system understood the spoken words and their timing.",
    example: "Clear speech helps this score; repeated or unclear words reduce it."
  },
  "Object Evidence": {
    definition: "How clearly the video shows useful visual context for a brand decision.",
    example: "A clearly visible product is stronger evidence than a person alone."
  }
};

export default function DashboardPage() {
  const params = useParams<{ videoId: string }>();
  const videoId = params.videoId;
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Segments");
  const [query, setQuery] = useState("");

  const analysisQuery = useQuery({
    queryKey: ["analysis", videoId],
    queryFn: () => getAnalysis(videoId)
  });

  const analysis = analysisQuery.data;
  const filteredSegments = useMemo(() => {
    if (!analysis) return [];
    const needle = query.toLowerCase();
    if (!needle) return analysis.segments;
    return analysis.segments.filter((segment) => {
      const haystack = [
        segment.transcript,
        segment.summary,
        segment.recommendation,
        ...segment.objects.map((object) => object.label),
        ...segment.topics.map((topic) => topic.label),
        ...segment.ad_matches.map((match) => match.ad_category)
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [analysis, query]);

  if (analysisQuery.isLoading) {
    return (
      <AppShell>
        <div className="p-8 text-slate-400">Loading dashboard...</div>
      </AppShell>
    );
  }

  if (!analysis) {
    return (
      <AppShell>
        <div className="p-8 text-danger">{analysisQuery.error?.message ?? "Dashboard not found."}</div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-7xl px-5 py-10 lg:px-10">
        <header className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div>
            <Badge tone="cyan">Video report</Badge>
            <h1 className="mt-4 text-4xl font-semibold md:text-6xl">{analysis.video.title}</h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-slate-400 md:text-lg">
              Clear video findings, the best ad moment, and simple next steps for your review.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <a href={exportUrl(videoId, "csv")}>
              <Button variant="secondary">
                <Download className="h-4 w-4" /> CSV
              </Button>
            </a>
            <a href={exportUrl(videoId, "json")}>
              <Button variant="secondary">
                <FileJson className="h-4 w-4" /> JSON
              </Button>
            </a>
          </div>
        </header>

        <DashboardSnapshot analysis={analysis} />

        <EvidenceReadiness analysis={analysis} />

        <section className="mt-6 grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
          <VideoPreview analysis={analysis} />
          <PlacementDecision analysis={analysis} />
        </section>

        <section className="mt-6">
          <BrandFitPanel videoId={videoId} />
        </section>

        <section className="mt-6">
          <PrePostKeywords analysis={analysis} />
        </section>

        <section className="mt-8 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <OverallVideoTrend segments={analysis.segments} />

          <div className="space-y-5">
            <MetricGroup title="Viewer response">
              <Metric title="Overall Attention" value={analysis.summary.overall_attention_score} icon={<Zap className="h-5 w-5" />} />
              <Metric title="Drop Risk" value={analysis.summary.overall_drop_risk_score ?? 0} icon={<AlertTriangle className="h-5 w-5" />} />
              <Moment title="Best Hook" moment={analysis.summary.best_hook} />
              <Moment title="Weak Segment" moment={analysis.summary.weakest_segment} danger />
            </MetricGroup>
            <MetricGroup title="How reliable is this report?" beta>
              <Metric title="Transcript Confidence" value={averageTranscriptConfidence(analysis.segments)} icon={<FileText className="h-5 w-5" />} />
              <Metric title="Visual Quality" value={analysis.summary.visual_quality_score ?? 0} icon={<Eye className="h-5 w-5" />} />
              <Metric title="Object Evidence" value={objectEvidenceScore(analysis.segments)} icon={<Search className="h-5 w-5" />} />
              <Metric title="Brand Safety" value={analysis.summary.brand_safety_score ?? 100} icon={<ShieldCheck className="h-5 w-5" />} />
            </MetricGroup>
            <MetricGroup title="Campaign opportunity" beta>
              <Metric title="Monetization" value={analysis.summary.monetization_opportunity_score} icon={<TrendingUp className="h-5 w-5" />} />
              <Metric title="Creator Ready" value={analysis.summary.creator_readiness_score ?? 0} icon={<FileText className="h-5 w-5" />} />
              <Card className="p-6 sm:col-span-2">
                <div className="flex flex-wrap items-center gap-2"><GuidedLabel label="Best matching ad category" guide="The category that fits this video best based on the available evidence." /><Badge tone="cyan">Beta</Badge></div>
                <p className="mt-3 text-3xl font-semibold">{analysis.summary.top_ad_category ?? "No confident match"}</p>
                <p className="mt-4 text-base leading-7 text-slate-500">
                  We compare the spoken content, visuals, audio, and safety context with {analysis.summary.ad_catalog_size ?? 0}+ ad categories.
                </p>
              </Card>
            </MetricGroup>
          </div>
        </section>

        <section className="mt-6">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 className="text-2xl font-semibold">Viewer attention over time</h2>
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter objects, topics, transcript..."
                className="h-11 w-full rounded-lg border border-border bg-surface pl-10 pr-3 text-base outline-none focus:ring-2 focus:ring-white/20"
              />
            </div>
          </div>
          <AttentionTimeline segments={filteredSegments} />
        </section>

        <section className="mt-8 space-y-4">
          <SectionTitle title="Evidence Charts" body="Compare attention, safety, transcript quality, and ad-fit before opening the timestamp evidence." />
          <div className="grid gap-5 xl:grid-cols-2">
            <EvidenceHeatmap segments={filteredSegments} />
            <BrandFitRadar segments={filteredSegments} />
            <AttentionAdFitScatter segments={filteredSegments} />
            <ScoringMethodologyTable catalogSize={analysis.summary.ad_catalog_size ?? 0} />
          </div>
        </section>

        <section className="mt-8">
          <SectionTitle title="Segment Evidence" body="Review the exact timestamp evidence behind objects, transcript, ad matches, and recommendations." />
          <div className="flex flex-wrap gap-2 border-b border-border">
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`border-b-2 px-4 py-4 text-base font-semibold ${
                  activeTab === tab ? "border-zinc-100 text-zinc-100" : "border-transparent text-slate-500"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="mt-5">
            {activeTab === "Segments" ? <SegmentsTab segments={filteredSegments} /> : null}
            {activeTab === "Objects" ? <ObjectsTab segments={filteredSegments} /> : null}
            {activeTab === "Transcript" ? <TranscriptTab segments={filteredSegments} /> : null}
            {activeTab === "Evidence" ? <EvidenceTab segments={filteredSegments} /> : null}
            {activeTab === "Ad Matches" ? <AdMatchesTab segments={filteredSegments} /> : null}
            {activeTab === "Recommendations" ? <RecommendationsTab recommendations={analysis.recommendations} /> : null}
          </div>
        </section>
      </div>
      <SegmentDrawer />
    </AppShell>
  );
}

function EvidenceReadiness({ analysis }: { analysis: AnalysisPayload }) {
  const segments = analysis.segments;
  const transcript = averageTranscriptConfidence(segments);
  const visual = Math.round(analysis.summary.visual_quality_score ?? 0);
  const objects = objectEvidenceScore(segments);
  const safety = Math.round(analysis.summary.brand_safety_score ?? 100);
  const directEvidence = segments.filter((segment) => segment.evidence_mode === "transcript_visual" || segment.evidence_mode === "audio_visual").length;
  const weakEvidence = segments.filter((segment) => segment.evidence_mode === "weak_evidence" || (segment.failed_or_weak_signals?.length ?? 0) > 0).length;
  const confidence = Math.round(transcript * 0.35 + visual * 0.25 + objects * 0.20 + safety * 0.20);
  const rows = [
    { label: "Speech", value: transcript, detail: "how clearly words and timing were understood" },
    { label: "Visuals", value: visual, detail: "how clear the sampled video frames are" },
    { label: "On-screen context", value: objects, detail: "how much useful visual context was found" },
    { label: "Safety", value: safety, detail: "screening for risky claims and context" }
  ];
  return (
    <section className="mt-6">
      <Card className="overflow-hidden border-white/10 bg-black">
        <div className="flex flex-col gap-4 border-b border-white/10 p-5 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex flex-wrap gap-2"><Badge tone="cyan">Evidence confidence</Badge><Badge tone="cyan">Beta</Badge></div>
            <h2 className="mt-3 text-2xl font-semibold text-white">How much can you trust these findings?</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">A strong video score is more useful when the speech, visuals, and on-screen context are clear. Use this as a quick confidence check before you act.</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3 text-left md:text-right">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">Confidence in this report</p>
            <p className="mt-1 text-3xl font-semibold text-white">{confidence}</p>
          </div>
        </div>
        <div className="grid divide-y divide-white/10 md:grid-cols-4 md:divide-x md:divide-y-0">
          {rows.map((row) => (
            <div key={row.label} className="p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-white">{row.label}</p>
                <Badge tone={row.value >= 70 ? "success" : row.value >= 45 ? "warning" : "danger"}>{row.value}</Badge>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-500">{row.detail}</p>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2 border-t border-white/10 bg-white/[0.02] px-5 py-3 text-sm text-slate-400 sm:flex-row sm:items-center sm:justify-between">
          <span>{directEvidence}/{segments.length} moments have clear speech or audio-and-visual support.</span>
          <span className={weakEvidence ? "text-warning" : "text-success"}>{weakEvidence ? `${weakEvidence} moments need a closer look.` : "All moments have usable evidence."}</span>
        </div>
      </Card>
    </section>
  );
}

function PrePostKeywords({ analysis }: { analysis: AnalysisPayload }) {
  const keywords = buildPrePostKeywords(analysis);
  const hashtags = keywords.slice(0, 5).map((keyword) => `#${keyword.keyword.replace(/[^a-z0-9]+/gi, "")}`).filter((tag) => tag.length > 1);
  return (
    <Card className="min-w-0 overflow-hidden border-white/10 bg-black">
      <div className="flex flex-col gap-4 border-b border-white/10 p-5 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap gap-2"><Badge tone="cyan">Pre-post keywords</Badge><Badge tone="cyan">Beta</Badge></div>
          <h2 className="mt-3 text-2xl font-semibold text-white">Suggested words for your title, caption, and tags</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">These suggestions come from the video title, detected topics, on-screen context, and spoken content. Keep only the words that accurately describe the final video.</p>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3"><p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">Before posting</p><p className="mt-1 text-sm font-semibold text-white">Use 3–5 relevant keywords</p></div>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="text-sm font-semibold text-white">Recommended keywords</p>
          <div className="mt-3 flex flex-wrap gap-2">{keywords.length ? keywords.map((keyword) => <span key={`${keyword.keyword}-${keyword.source}`} className="inline-flex max-w-full items-center gap-2 rounded-md border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"><span className="break-words">{keyword.keyword}</span><span className="text-xs text-zinc-500">{keyword.source}</span></span>) : <p className="text-sm text-slate-500">Add a clearer title or more spoken context to generate keyword ideas.</p>}</div>
        </div>
        <div className="rounded-lg border border-white/10 bg-zinc-950 p-4"><p className="text-sm font-semibold text-white">Ready-to-review hashtags</p><p className="mt-1 text-xs leading-5 text-slate-500">Use only hashtags that match the actual video.</p><div className="mt-3 flex flex-wrap gap-2">{hashtags.length ? hashtags.map((tag) => <Badge key={tag} tone="cyan">{tag}</Badge>) : <p className="text-sm text-slate-500">No reliable hashtags yet.</p>}</div><p className="mt-4 border-t border-white/10 pt-3 text-xs leading-5 text-slate-500">Tip: put the clearest keyword in the first half of the title and repeat it naturally in the caption.</p></div>
      </div>
    </Card>
  );
}

function buildPrePostKeywords(analysis: AnalysisPayload) {
  const suggestions = new Map<string, { keyword: string; source: string; score: number }>();
  const add = (keyword: string, source: string, score: number) => {
    const cleaned = keyword.replace(/[_-]+/g, " ").replace(/\b\d{8,}\b/g, "").replace(/\s+/g, " ").trim();
    if (cleaned.length < 3 || cleaned.length > 42) return;
    const key = cleaned.toLowerCase();
    const existing = suggestions.get(key);
    if (!existing || existing.score < score) suggestions.set(key, { keyword: cleaned, source, score });
  };

  const title = analysis.video.title.replace(/[_-]+/g, " ").replace(/\b\d{8,}\b/g, "").replace(/\s+/g, " ").trim();
  if (title) add(title, "title", 10);
  analysis.topics.forEach((topic) => add(topic.label, "topic", 8 + topic.confidence));
  analysis.objects.filter((object) => object.label.toLowerCase() !== "person").forEach((object) => add(object.label, "visual", 5 + object.confidence));
  if (analysis.summary.top_ad_category && analysis.summary.top_ad_category !== "No confident match") add(analysis.summary.top_ad_category, "context", 6);

  const stopWords = new Set(["this", "that", "with", "from", "have", "your", "video", "title", "about", "there", "where", "their", "they", "what", "when", "will", "into", "were", "been", "just", "more"]);
  const words = analysis.segments.flatMap((segment) => normalizedWhitespace(segment.transcript).toLowerCase().match(/[a-z][a-z-]{3,}/g) ?? []).filter((word) => !stopWords.has(word));
  const counts = new Map<string, number>();
  words.forEach((word) => counts.set(word, (counts.get(word) ?? 0) + 1));
  [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).forEach(([word, count]) => add(word, "speech", 2 + count));

  return [...suggestions.values()].sort((a, b) => b.score - a.score).slice(0, 8);
}

function DashboardSnapshot({ analysis }: { analysis: AnalysisPayload }) {
  const summary = analysis.summary;
  const bestSlot = summary.best_ad_slot;
  const bestWindow = summary.best_content_window;
  const tier: RecommendationTier = summary.best_recommendation_tier ?? bestSlot?.recommendation_tier ?? bestWindow?.recommendation_tier ?? "Edit before monetization";
  const chosenWindow = bestSlot ?? bestWindow;
  const representative = chosenWindow
    ? analysis.segments.find((segment) => segment.start === chosenWindow.start && segment.end === chosenWindow.end)
    : undefined;
  const transcriptScore = averageTranscriptConfidence(analysis.segments);
  const objectScore = objectEvidenceScore(analysis.segments);
  const topCategory = summary.top_ad_category || "No confident match";
  const items = [
    {
      kicker: "1. Placement",
      label: tier,
      detail: summary.recommendation_status ?? "Review recommendation quality",
      tone: tierTone(tier)
    },
    {
      kicker: "2. Best Window",
      label: chosenWindow ? formatRange(chosenWindow.start, chosenWindow.end) : "--",
      detail: bestSlot ? "Strong ad slot candidate" : "Best available content-context window",
      tone: bestSlot ? "success" : "warning"
    },
    {
      kicker: "3. Transcript",
      label: String(transcriptScore),
      detail: transcriptScore >= 70 ? "Clear transcript evidence" : transcriptScore > 0 ? "Transcript needs review" : "Visual and audio evidence used",
      tone: transcriptScore >= 70 ? "success" : transcriptScore > 0 ? "warning" : "danger"
    },
    {
      kicker: "4. Evidence",
      label: evidenceModeLabel(representative?.evidence_mode),
      detail: `${objectScore} object score - ${topCategory}`,
      tone: objectScore >= 60 ? "success" : objectScore >= 30 ? "cyan" : "warning"
    }
  ] satisfies {
    kicker: string;
    label: string;
    detail: string;
    tone: "default" | "success" | "warning" | "danger" | "cyan";
  }[];

  return (
    <section className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4" aria-label="Dashboard review order">
      {items.map((item) => (
        <Card key={item.kicker} className="p-5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-semibold uppercase tracking-[0.12em] text-slate-500">{item.kicker}</p>
            <Badge tone={item.tone}>{item.tone === "success" ? "Ready" : item.tone === "danger" ? "Review" : "Check"}</Badge>
          </div>
          <p className="mt-4 text-2xl font-semibold leading-tight text-white">{item.label}</p>
          <p className="mt-2 text-base leading-6 text-slate-400">{item.detail}</p>
        </Card>
      ))}
    </section>
  );
}

function VideoPreview({ analysis }: { analysis: AnalysisPayload }) {
  const videoUrl = absoluteMediaUrl(analysis.video.file_url);
  const thumbnailUrl = absoluteMediaUrl(analysis.video.thumbnail);
  return (
    <Card className="overflow-hidden bg-black">
      <div className="border-b border-white/10 p-6">
        <GuidedLabel label="Video Preview" guide="Preview the uploaded or ingested media while reviewing the scoring evidence." />
      </div>
      <div className="aspect-video bg-zinc-950">
        {videoUrl ? (
          <video className="h-full w-full bg-black object-contain" src={videoUrl} poster={thumbnailUrl ?? undefined} controls preload="metadata" />
        ) : analysis.video.embed_url ? (
          <iframe className="h-full w-full" src={analysis.video.embed_url} title={analysis.video.title} allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen />
        ) : thumbnailUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="h-full w-full object-contain" src={thumbnailUrl} alt={analysis.video.title} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">No preview media available.</div>
        )}
      </div>
    </Card>
  );
}

function PlacementDecision({ analysis }: { analysis: AnalysisPayload }) {
  const summary = analysis.summary;
  const bestSlot = summary.best_ad_slot;
  const bestWindow = summary.best_content_window;
  const tier = summary.best_recommendation_tier ?? bestSlot?.recommendation_tier ?? bestWindow?.recommendation_tier ?? "Edit before monetization";
  const representative = bestSlot
    ? analysis.segments.find((segment) => segment.start === bestSlot.start && segment.end === bestSlot.end)
    : bestWindow
      ? analysis.segments.find((segment) => segment.start === bestWindow.start && segment.end === bestWindow.end)
      : undefined;
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2"><GuidedLabel label="Placement recommendation" guide="A suggestion based on what the system found in the video." /><Badge tone="cyan">Beta</Badge></div>
          <h2 className="mt-3 text-3xl font-semibold text-white">{summary.recommendation_status ?? tier}</h2>
        </div>
        <Badge tone={tierTone(tier)}>{tier}</Badge>
      </div>
      <p className="mt-4 text-base leading-7 text-slate-300">
        {summary.recommendation_message ?? "Review the best content-context window before placing an ad."}
      </p>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <DecisionStat label="Best moment for an ad" value={bestSlot ? formatRange(bestSlot.start, bestSlot.end) : "None yet"} />
        <DecisionStat label="Best video moment" value={bestWindow ? formatRange(bestWindow.start, bestWindow.end) : "--"} />
        <DecisionStat label="Confidence" value={`${Math.round(bestSlot?.recommendation_confidence ?? bestWindow?.recommendation_confidence ?? representative?.recommendation_confidence ?? 0)}/100`} />
      </div>
      {representative?.ad_slot_score ? (
        <div className="mt-4 rounded-lg border border-success/25 bg-success/5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-semibold text-white">Strongest ad-slot evidence</p>
            <Badge tone="success">Slot strength {Math.round(representative.ad_slot_score)}</Badge>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            {(representative.ad_slot_reasons ?? []).join(" · ") || "This window has the strongest combined attention, context, safety, boundary, and confidence signals."}
          </p>
        </div>
      ) : null}
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <SignalList title="Strong Signals" signals={representative?.strong_signals ?? []} empty="No strong signals captured." tone="success" />
        <SignalList title="Weak Signals" signals={representative?.failed_or_weak_signals ?? []} empty="No weak signals captured." tone="warning" />
      </div>
    </Card>
  );
}

function DecisionStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
    </div>
  );
}

function SignalList({ title, signals, empty, tone }: { title: string; signals: string[]; empty: string; tone: "success" | "warning" }) {
  return (
    <div>
      <p className="text-base font-semibold text-slate-200">{title}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {signals.length ? signals.map((signal) => <Badge key={signal} tone={tone}>{signal}</Badge>) : <p className="text-base text-slate-500">{empty}</p>}
      </div>
    </div>
  );
}

function MetricGroup({ title, children, beta = false }: { title: string; children: React.ReactNode; beta?: boolean }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold uppercase tracking-[0.14em] text-slate-500">{title}</h2>{beta ? <Badge tone="cyan" className="text-xs">Beta</Badge> : null}</div>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Metric({ title, value, icon }: { title: string; value: number; icon: React.ReactNode }) {
  const guide = metricGuides[title];
  return (
    <Card className="min-w-0 p-6">
      <div className="flex min-w-0 items-center justify-between gap-3 text-slate-400">
        <GuidedLabel label={title} guide={guide ? `${guide.definition} ${guide.example}` : undefined} />
        {icon}
      </div>
      <p className="mt-4 text-5xl font-semibold">{Math.round(value)}</p>
      {guide ? <p className="mt-3 text-sm leading-6 text-slate-500">{guide.definition}</p> : null}
    </Card>
  );
}

function GuidedLabel({ label, guide }: { label: string; guide?: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-base text-slate-400" title={guide}>
      {label}
      {guide ? <CircleHelp className="h-4 w-4 text-slate-500" aria-hidden="true" /> : null}
    </span>
  );
}

function ChartHeader({ title, guide, action }: { title: string; guide: string; action: string }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <GuidedLabel label={title} guide={guide} />
        <p className="mt-2 text-sm leading-6 text-slate-500"><span className="font-medium text-slate-300">How to read it:</span> {guide}</p>
        <p className="mt-2 text-sm leading-6 text-slate-500"><span className="font-medium text-slate-300">Use it to:</span> {action}</p>
      </div>
    </div>
  );
}

function SectionTitle({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h2 className="text-2xl font-semibold text-zinc-100">{title}</h2>
      <p className="mt-2 max-w-3xl text-base leading-7 text-slate-500">{body}</p>
    </div>
  );
}

function LegendRow({ items }: { items: { label: string; color: string; description?: string; dash?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-2 text-sm">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-zinc-950 px-3 py-1.5 text-slate-300" title={item.description}>
          <span className="h-0.5 w-6 rounded" style={{ backgroundColor: item.color, borderTop: item.dash ? `2px ${item.dash} ${item.color}` : undefined }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function scoreBand(score: number, inverse = false) {
  if (inverse) {
    if (score >= 75) return "High risk";
    if (score >= 50) return "Needs review";
    if (score >= 25) return "Manageable";
    return "Low risk";
  }
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Strong";
  if (score >= 55) return "Good";
  if (score >= 40) return "Average";
  if (score >= 25) return "Weak";
  return "Critical";
}

function ChartTooltip({
  active,
  payload,
  label
}: {
  active?: boolean;
  payload?: { color?: string; name?: string; value?: number | string; payload?: Record<string, unknown> }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload ?? {};
  const title = String(point.time ?? label ?? "");
  return (
    <div className="max-w-xs rounded-lg border border-white/10 bg-black/95 p-3 text-sm text-slate-200 shadow-glow">
      {title ? <p className="mb-2 font-semibold text-white">{title}</p> : null}
      <div className="space-y-1.5">
        {payload.map((entry) => (
          <div key={`${entry.name}-${entry.value}`} className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-2 text-slate-400">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color ?? "#f8fafc" }} />
              {entry.name}
            </span>
            <span className="font-medium text-slate-100">{entry.value}</span>
          </div>
        ))}
      </div>
      {"risk" in point ? <p className="mt-2 text-slate-500">Drop risk: {String(point.risk)}. Brand safety: {String(point.safety)}.</p> : null}
    </div>
  );
}

function OverallVideoTrend({ segments }: { segments: Segment[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const width = 920;
  const height = 360;
  const padding = { top: 48, right: 52, bottom: 58, left: 54 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const safeSegments = segments.length ? segments : [];

  if (!safeSegments.length) {
    return (
      <Card className="flex min-h-[420px] items-center justify-center p-6 text-slate-500">
        No trend data available yet.
      </Card>
    );
  }

  const data = safeSegments.map((segment, index) => {
    const x = padding.left + (safeSegments.length === 1 ? chartWidth / 2 : (index / (safeSegments.length - 1)) * chartWidth);
    const attentionY = padding.top + chartHeight - (Math.max(0, Math.min(100, segment.attention_score)) / 100) * chartHeight;
    const adFitY = padding.top + chartHeight - (Math.max(0, Math.min(100, segment.ad_fit_score)) / 100) * chartHeight;
    const dropRiskY = padding.top + chartHeight - (Math.max(0, Math.min(100, segment.drop_risk_score ?? 0)) / 100) * chartHeight;
    const safetyY = padding.top + chartHeight - (Math.max(0, Math.min(100, segment.brand_safety_score ?? 100)) / 100) * chartHeight;
    return { segment, x, attentionY, adFitY, dropRiskY, safetyY };
  });
  const high = data.reduce((best, item) => (item.segment.attention_score > best.segment.attention_score ? item : best), data[0]);
  const low = data.reduce((weakest, item) => (item.segment.attention_score < weakest.segment.attention_score ? item : weakest), data[0]);
  const bestAd = data.reduce((best, item) => (item.segment.ad_fit_score > best.segment.ad_fit_score ? item : best), data[0]);
  const average = safeSegments.length
    ? Math.round(safeSegments.reduce((total, segment) => total + segment.attention_score, 0) / safeSegments.length)
    : 0;
  const averageY = padding.top + chartHeight - (average / 100) * chartHeight;
  const attentionPath = data.map((item) => `${item.x},${item.attentionY}`).join(" ");
  const adFitPath = data.map((item) => `${item.x},${item.adFitY}`).join(" ");
  const dropRiskPath = data.map((item) => `${item.x},${item.dropRiskY}`).join(" ");
  const safetyPath = data.map((item) => `${item.x},${item.safetyY}`).join(" ");
  const trendCopy = trendLabel(safeSegments);
  const hovered = hoveredIndex === null ? null : data[hoveredIndex];
  const tickCount = Math.min(6, Math.max(2, safeSegments.length));
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const dataIndex = Math.round((index / (tickCount - 1)) * Math.max(0, safeSegments.length - 1));
    return data[dataIndex];
  }).filter(Boolean);
  const handleTrendHover = (event: React.MouseEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const localX = ((event.clientX - bounds.left) / bounds.width) * width;
    const localY = ((event.clientY - bounds.top) / bounds.height) * height;
    if (localX < padding.left || localX > width - padding.right || localY < padding.top || localY > padding.top + chartHeight) {
      setHoveredIndex(null);
      return;
    }
    const ratio = (localX - padding.left) / chartWidth;
    setHoveredIndex(Math.max(0, Math.min(data.length - 1, Math.round(ratio * (data.length - 1)))));
  };

  return (
    <Card className="overflow-hidden border-white/10 bg-black">
      <div className="border-b border-white/10 p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.18em] text-slate-500">{trendCopy.kicker}</p>
            <h2 className="mt-2 text-3xl font-semibold leading-tight text-white">{trendCopy.title}</h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400"><span className="font-medium text-slate-200">How to read it:</span> Follow the white line for viewer attention. A strong ad moment usually combines high attention, high ad fit, low drop risk, and steady brand safety.</p>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500"><span className="font-medium text-slate-300">Recommended action:</span> {trendCopy.action}</p>
          </div>
          <LegendRow
            items={[
              { label: "Attention Proxy", color: "#f8fafc", description: "Higher means the segment has stronger attention signals." },
              { label: "Ad Fit", color: "#f59e0b", description: "Higher means stronger evidence for a brand/category slot." },
              { label: "Drop Risk", color: "#ef4444", description: "Higher means the segment may lose viewer interest." },
              { label: "Brand Safety", color: "#22c55e", description: "Higher means fewer detected transcript safety concerns." }
            ]}
          />
        </div>
      </div>

      <div className="p-6">
        <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-[360px] w-full"
            role="img"
            aria-label="Overall attention trend graph"
            onMouseMove={handleTrendHover}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            <defs>
              <linearGradient id="attentionTrendFill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgba(255,255,255,0.18)" />
                <stop offset="100%" stopColor="rgba(255,255,255,0)" />
              </linearGradient>
            </defs>

            {[0, 25, 50, 75, 100].map((value) => {
              const y = padding.top + chartHeight - (value / 100) * chartHeight;
              return (
                <g key={value}>
                  <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(255,255,255,0.08)" />
                  <text x={padding.left - 14} y={y + 4} textAnchor="end" fontSize="12" fill="#71717a">
                    {value}
                  </text>
                </g>
              );
            })}

            <line x1={padding.left} x2={width - padding.right} y1={averageY} y2={averageY} stroke="rgba(245,158,11,0.45)" strokeDasharray="7 7" />
            <text x={width - padding.right} y={averageY - 8} textAnchor="end" fontSize="12" fill="#f59e0b">
              Avg {average}
            </text>

            <polygon
              points={`${attentionPath} ${data[data.length - 1].x},${padding.top + chartHeight} ${data[0].x},${padding.top + chartHeight}`}
              fill="url(#attentionTrendFill)"
            />
            <polyline points={adFitPath} fill="none" stroke="#f59e0b" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" strokeDasharray="8 8" />
            <polyline points={dropRiskPath} fill="none" stroke="#ef4444" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" strokeDasharray="3 7" />
            <polyline points={safetyPath} fill="none" stroke="#22c55e" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" strokeDasharray="10 6" />
            <polyline points={attentionPath} fill="none" stroke="#f8fafc" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" />

            {data.map((item, index) => (
              <circle key={item.segment.id} cx={item.x} cy={item.attentionY} r={index === 0 || index === data.length - 1 ? 4 : 3} fill="#f8fafc" opacity="0.92" />
            ))}

            {data.map((item, index) => {
              const left = index === 0 ? padding.left : (data[index - 1].x + item.x) / 2;
              const right = index === data.length - 1 ? width - padding.right : (item.x + data[index + 1].x) / 2;
              return (
                <rect
                  key={`${item.segment.id}-hover`}
                  x={left}
                  y={padding.top}
                  width={Math.max(16, right - left)}
                  height={chartHeight}
                  fill="transparent"
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                />
              );
            })}

            {hovered ? <TimelineHover item={hovered} width={width} paddingRight={padding.right} paddingTop={padding.top} chartHeight={chartHeight} /> : null}

            <AnnotatedPoint item={high} label="High attention" tone="success" />
            <AnnotatedPoint item={low} label="Low point" tone="danger" />
            {bestAd.segment.id !== high.segment.id && bestAd.segment.id !== low.segment.id ? <AnnotatedPoint item={bestAd} label="Best ad fit" tone="warning" useAdFit /> : null}

            {ticks.map((item) => (
              <text key={`${item.segment.id}-tick`} x={item.x} y={height - 24} textAnchor="middle" fontSize="12" fill="#71717a">
                {formatRange(item.segment.start, item.segment.end)}
              </text>
            ))}
            <text x={padding.left} y={height - 6} fontSize="12" fill="#52525b">
              Video timeline
            </text>
            <text x={16} y={padding.top - 18} fontSize="12" fill="#52525b">
              Score
            </text>
          </svg>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <TrendMoment title="Peak attention" segment={high.segment} tone="success" />
          <TrendMoment title="Lowest attention" segment={low.segment} tone="danger" />
          <TrendMoment title="Best ad-fit point" segment={bestAd.segment} tone="warning" showAdFit />
        </div>
      </div>
    </Card>
  );
}

function trendLabel(segments: Segment[]) {
  const avgAttention = mean(segments.map((segment) => segment.attention_score));
  const avgAdFit = mean(segments.map((segment) => segment.ad_fit_score));
  const avgDrop = mean(segments.map((segment) => segment.drop_risk_score ?? 0));
  const avgSafety = mean(segments.map((segment) => segment.brand_safety_score ?? 100));
  const score = Math.round((avgAttention * 0.4) + (avgAdFit * 0.25) + ((100 - avgDrop) * 0.2) + (avgSafety * 0.15));
  if (avgDrop >= 75 && avgAttention < 45) {
    return { kicker: "Overall video result", title: `Low attention (${Math.round(avgAttention)}/100) and high viewer drop risk (${Math.round(avgDrop)}/100)`, action: "Tighten the opening, remove slow moments, and re-check the next edit before using an ad break." };
  }
  if (avgSafety < 70) {
    return { kicker: "Overall video result", title: `Brand safety needs review (${Math.round(avgSafety)}/100)`, action: "Review the flagged words and visuals before sharing this video with a brand." };
  }
  if (avgAdFit >= 60 && avgAttention >= 55) {
    return { kicker: "Overall video result", title: `Good candidate for an ad test (${score}/100 overall)`, action: "Open the best highlighted moment and review it before approving a placement." };
  }
  return { kicker: "Overall video result", title: `This video needs improvement before an ad test (${score}/100 overall)`, action: "Use the highlighted strong and weak moments below to plan the next edit." };
}

function mean(values: number[]) {
  if (!values.length) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function averageTranscriptConfidence(segments: Segment[]) {
  return Math.round(mean(segments.map((segment) => segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0)));
}

function objectEvidenceScore(segments: Segment[]) {
  if (!segments.length) return 0;
  return Math.round(mean(segments.map((segment) => Math.min(100, (segment.visual_evidence?.object_count ?? 0) * 24 + (segment.objects.some((object) => object.label === "person") ? 12 : 0)))));
}

function evidenceModeLabel(mode?: string) {
  if (!mode) return "Weak evidence";
  return mode
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function normalizedWhitespace(value?: string | null) {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeTranscriptChunk(value: string) {
  return value.toLowerCase().replace(/[^\w\s']/g, " ").replace(/\s+/g, " ").trim();
}

function transcriptDisplayForSegment(segment: Segment, previousSegment?: Segment) {
  const rawTranscript = normalizedWhitespace(segment.transcript);
  const previousTranscript = normalizedWhitespace(previousSegment?.transcript);
  const compacted = compactRepeatedTranscript(rawTranscript);
  const repeatedPrefixTrimmed = trimRepeatedTranscriptPrefix(compacted, compactRepeatedTranscript(previousTranscript));
  const text = compactRepeatedTranscript(repeatedPrefixTrimmed);
  return {
    text,
    compacted: Boolean(rawTranscript && text !== rawTranscript),
    repeatedOnly: Boolean(rawTranscript && !text)
  };
}

function compactRepeatedTranscript(transcript?: string | null) {
  const text = normalizedWhitespace(transcript);
  if (!text) return "";
  const sentenceChunks = text.match(/[^.!?]+[.!?]?/g)?.map((chunk) => chunk.trim()).filter(Boolean) ?? [text];
  const dedupedSentences: string[] = [];
  for (const chunk of sentenceChunks) {
    const normalized = normalizeTranscriptChunk(chunk);
    const previous = normalizeTranscriptChunk(dedupedSentences[dedupedSentences.length - 1] ?? "");
    if (normalized && normalized !== previous) {
      dedupedSentences.push(chunk);
    }
  }
  return compactRepeatedWordPhrases(dedupedSentences.join(" "));
}

function trimRepeatedTranscriptPrefix(current: string, previous: string) {
  const currentWords = normalizedWhitespace(current).split(" ").filter(Boolean);
  const previousWords = normalizedWhitespace(previous).split(" ").filter(Boolean);
  if (currentWords.length < 6 || previousWords.length < 6) return normalizedWhitespace(current);

  const maxSize = Math.min(currentWords.length, previousWords.length);
  for (let size = maxSize; size >= 6; size -= 1) {
    const currentPrefix = normalizeTranscriptChunk(currentWords.slice(0, size).join(" "));
    const previousPrefix = normalizeTranscriptChunk(previousWords.slice(0, size).join(" "));
    const previousSuffix = normalizeTranscriptChunk(previousWords.slice(previousWords.length - size).join(" "));
    if (currentPrefix && (currentPrefix === previousPrefix || currentPrefix === previousSuffix)) {
      return currentWords.slice(size).join(" ");
    }
  }

  return normalizedWhitespace(current);
}

function compactRepeatedWordPhrases(text: string) {
  const words = normalizedWhitespace(text).split(" ").filter(Boolean);
  if (words.length < 6) return normalizedWhitespace(text);

  const result: string[] = [];
  let index = 0;
  while (index < words.length) {
    let repeatedSize = 0;
    const maxPhraseSize = Math.min(18, Math.floor((words.length - index) / 2));
    for (let size = maxPhraseSize; size >= 3; size -= 1) {
      const phrase = normalizeTranscriptChunk(words.slice(index, index + size).join(" "));
      const nextPhrase = normalizeTranscriptChunk(words.slice(index + size, index + size * 2).join(" "));
      if (phrase && phrase === nextPhrase) {
        repeatedSize = size;
        break;
      }
    }

    if (!repeatedSize) {
      result.push(words[index]);
      index += 1;
      continue;
    }

    const phraseWords = words.slice(index, index + repeatedSize);
    const phrase = normalizeTranscriptChunk(phraseWords.join(" "));
    result.push(...phraseWords);
    index += repeatedSize;
    while (index + repeatedSize <= words.length && normalizeTranscriptChunk(words.slice(index, index + repeatedSize).join(" ")) === phrase) {
      index += repeatedSize;
    }
  }

  return result.join(" ");
}

function tierTone(tier: RecommendationTier): "success" | "warning" | "danger" | "cyan" {
  if (tier === "Strong ad slot") return "success";
  if (tier === "Conditional ad slot") return "cyan";
  if (tier === "Avoid") return "danger";
  return "warning";
}

function EvidenceHeatmap({ segments }: { segments: Segment[] }) {
  const rows = [
    { label: "Visual novelty", guide: "How different each segment looks from nearby frames.", value: (segment: Segment) => (segment.visual_evidence?.visual_novelty ?? 0) * 100 },
    { label: "Motion", guide: "Frame-to-frame visual movement.", value: (segment: Segment) => (segment.visual_evidence?.motion ?? 0) * 100 },
    { label: "Visual quality", guide: "Sharpness and exposure quality from sampled frames.", value: (segment: Segment) => (segment.visual_evidence?.visual_quality ?? 0) * 100 },
    { label: "Transcript confidence", guide: "Speech density, specificity, repetition, timestamp quality, hook, and CTA signals.", value: (segment: Segment) => segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0 },
    { label: "Drop risk", guide: "Risk from weak attention, silence, blur, or repetition.", value: (segment: Segment) => segment.drop_risk_score ?? 0 },
    { label: "Brand safety", guide: "Safety after claims and risky transcript flags.", value: (segment: Segment) => segment.brand_safety_score ?? 100 }
  ];
  return (
    <Card className="p-6">
      <ChartHeader title="Evidence Heatmap" guide="Rows are signals and columns are moments in the video. Brighter cells mean a stronger signal; bright red drop-risk cells need attention." action="Spot patterns quickly, then open the matching segment to see the transcript and visual evidence." />
      <div className="overflow-x-auto">
        <div className="min-w-[620px] space-y-2">
          <div className="grid gap-1" style={{ gridTemplateColumns: `150px repeat(${Math.max(1, segments.length)}, minmax(54px, 1fr))` }}>
            <div />
            {segments.map((segment) => (
              <div key={segment.id} className="truncate text-center text-xs text-slate-500" title={formatRange(segment.start, segment.end)}>
                {formatRange(segment.start, segment.end)}
              </div>
            ))}
          </div>
          {rows.map((row) => (
            <div key={row.label} className="grid gap-1" style={{ gridTemplateColumns: `150px repeat(${Math.max(1, segments.length)}, minmax(54px, 1fr))` }}>
              <div className="flex items-center">
                <GuidedLabel label={row.label} guide={row.guide} />
              </div>
              {segments.map((segment) => {
                const value = Math.max(0, Math.min(100, row.value(segment)));
                const isRisk = row.label === "Drop risk";
                const color = isRisk ? `rgba(239,68,68,${0.12 + value / 130})` : `rgba(248,250,252,${0.08 + value / 140})`;
                return (
                  <div
                    key={`${row.label}-${segment.id}`}
                    className="h-10 rounded border border-white/10 text-center text-sm leading-10 text-slate-200"
                    style={{ background: color }}
                    title={`${row.label} ${Math.round(value)} at ${formatRange(segment.start, segment.end)}`}
                  >
                    {Math.round(value)}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function BrandFitRadar({ segments }: { segments: Segment[] }) {
  const best = segments.reduce<Segment | null>((current, segment) => (!current || segment.ad_fit_score > current.ad_fit_score ? segment : current), null);
  const data = best
    ? [
        { metric: "Transcript", value: best.transcript_insights?.clarity_score ?? 0 },
        { metric: "Visual", value: Math.round((best.visual_evidence?.visual_quality ?? 0) * 100) },
        { metric: "Objects", value: Math.min(100, (best.visual_evidence?.object_count ?? 0) * 30) },
        { metric: "Attention", value: best.attention_score },
        { metric: "Slot", value: Math.max(0, 100 - (best.drop_risk_score ?? 0)) },
        { metric: "Safety", value: best.brand_safety_score ?? 100 }
      ]
    : [];
  return (
    <Card className="p-6">
      <ChartHeader title="Brand-Fit Radar" guide="The larger the shape reaches toward each label, the stronger that part of the best available moment is." action="Check the smallest side of the shape to see what needs improvement before you approve a brand placement." />
      <div className="h-72">
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={data} outerRadius="72%">
              <PolarGrid stroke="#27272a" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: "#a1a1aa", fontSize: 12 }} />
              <Radar dataKey="value" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.28} />
              <RechartsTooltip content={<ChartTooltip />} />
            </RadarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">No radar data available.</div>
        )}
      </div>
    </Card>
  );
}

function AttentionAdFitScatter({ segments }: { segments: Segment[] }) {
  const data = segments.map((segment) => ({
    time: formatRange(segment.start, segment.end),
    attention: Math.round(segment.attention_score),
    adFit: Math.round(segment.ad_fit_score),
    safety: Math.round(segment.brand_safety_score ?? 100),
    risk: Math.round(segment.drop_risk_score ?? 0)
  }));
  return (
    <Card className="p-6">
      <ChartHeader title="Attention vs Ad-Fit" guide="Each dot is a moment. Dots in the upper-right are stronger for both audience attention and ad relevance; safety and risk still need review." action="Shortlist upper-right moments, then use the tooltip to check their timing, safety, and drop risk." />
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 16, bottom: 16, left: 0 }}>
            <CartesianGrid stroke="#202020" />
            <XAxis type="number" dataKey="attention" name="Attention" domain={[0, 100]} stroke="#64748B" fontSize={12} />
            <YAxis type="number" dataKey="adFit" name="Ad Fit" domain={[0, 100]} stroke="#64748B" fontSize={12} />
            <ZAxis type="number" dataKey="safety" range={[70, 260]} />
            <RechartsTooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={<ChartTooltip />}
            />
            <Scatter data={data} fill="#f8fafc" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 grid gap-2 text-sm text-slate-500 sm:grid-cols-2">
        <p>Upper-right: high attention and strong ad evidence.</p>
        <p>Lower-left: weak for both engagement and monetization.</p>
      </div>
    </Card>
  );
}

function ScoringMethodologyTable({ catalogSize }: { catalogSize: number }) {
  const guides = [
    { title: "Viewer attention", help: "How likely people are to stay interested.", bands: [["0–24", "Very low", "danger"], ["25–39", "Low", "danger"], ["40–54", "Average", "warning"], ["55–69", "Good", "warning"], ["70–100", "Strong", "success"]] },
    { title: "Ad fit", help: "How naturally an ad may fit the moment.", bands: [["0–19", "Avoid", "danger"], ["20–39", "Weak", "danger"], ["40–59", "Maybe", "warning"], ["60–79", "Worth testing", "success"], ["80–100", "Strong fit", "success"]] },
    { title: "Viewer drop risk", help: "How likely people are to lose interest. Lower is better.", bands: [["0–24", "Low risk", "success"], ["25–49", "Manageable", "warning"], ["50–74", "Needs review", "warning"], ["75–100", "High risk", "danger"]] },
    { title: "Brand safety", help: "How suitable the content looks for brands.", bands: [["0–49", "Unsafe", "danger"], ["50–69", "Needs review", "warning"], ["70–84", "Mostly safe", "success"], ["85–100", "Safe", "success"]] }
  ] as const;
  return (
    <Card className="p-6">
      <ChartHeader title="What the scores mean" guide="This table explains the inputs behind each score and the checks that prevent generic recommendations." action="Use it when you need to explain a result to a client, creator, or campaign reviewer." />
      <div className="grid gap-4 md:grid-cols-2">
        {guides.map((guide) => <div key={guide.title} className="rounded-lg border border-white/10 bg-zinc-950 p-4"><p className="font-semibold text-white">{guide.title}</p><p className="mt-1 text-sm leading-6 text-slate-500">{guide.help}</p><div className="mt-4 flex flex-wrap gap-2">{guide.bands.map(([range, label, tone]) => <Badge key={`${range}-${label}`} tone={tone}><span className="font-mono text-xs">{range}</span><span className="ml-1">{label}</span></Badge>)}</div></div>)}
      </div>
      <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-slate-400"><span className="font-semibold text-white">How recommendations stay relevant:</span> We only show an ad category when the transcript, visuals, or topic context gives enough evidence. {catalogSize}+ categories are checked in the background.</div>
    </Card>
  );
}

function TimelineHover({
  item,
  width,
  paddingRight,
  paddingTop,
  chartHeight
}: {
  item: { segment: Segment; x: number; attentionY: number; adFitY: number; dropRiskY: number; safetyY: number };
  width: number;
  paddingRight: number;
  paddingTop: number;
  chartHeight: number;
}) {
  const boxWidth = 218;
  const boxHeight = 124;
  const x = Math.min(width - paddingRight - boxWidth, Math.max(64, item.x + 12));
  const y = Math.min(paddingTop + chartHeight - boxHeight, Math.max(paddingTop + 8, item.attentionY - 50));
  const values = [
    { label: "Attention", value: Math.round(item.segment.attention_score), color: "#f8fafc", band: scoreBand(item.segment.attention_score) },
    { label: "Ad Fit", value: Math.round(item.segment.ad_fit_score), color: "#f59e0b", band: scoreBand(item.segment.ad_fit_score) },
    { label: "Drop Risk", value: Math.round(item.segment.drop_risk_score ?? 0), color: "#ef4444", band: scoreBand(item.segment.drop_risk_score ?? 0, true) },
    { label: "Brand Safety", value: Math.round(item.segment.brand_safety_score ?? 100), color: "#22c55e", band: scoreBand(item.segment.brand_safety_score ?? 100) }
  ];
  return (
    <g pointerEvents="none">
      <line x1={item.x} x2={item.x} y1={paddingTop} y2={paddingTop + chartHeight} stroke="rgba(255,255,255,0.22)" strokeDasharray="4 6" />
      <g transform={`translate(${x} ${y})`}>
        <rect width={boxWidth} height={boxHeight} rx="8" fill="#050505" stroke="rgba(255,255,255,0.18)" />
        <text x="12" y="20" fontSize="12" fill="#f8fafc" fontWeight="600">
          {formatRange(item.segment.start, item.segment.end)}
        </text>
        {values.map((entry, index) => (
          <g key={entry.label} transform={`translate(12 ${38 + index * 20})`}>
            <circle cx="4" cy="-4" r="4" fill={entry.color} />
            <text x="16" y="0" fontSize="11" fill="#a1a1aa">
              {entry.label}
            </text>
            <text x="104" y="0" fontSize="11" fill="#f8fafc" textAnchor="end">
              {entry.value}
            </text>
            <text x="118" y="0" fontSize="10" fill="#71717a">
              {entry.band}
            </text>
          </g>
        ))}
      </g>
    </g>
  );
}

function AnnotatedPoint({
  item,
  label,
  tone,
  useAdFit = false
}: {
  item: { segment: Segment; x: number; attentionY: number; adFitY: number };
  label: string;
  tone: "success" | "danger" | "warning";
  useAdFit?: boolean;
}) {
  const color = tone === "success" ? "#22c55e" : tone === "danger" ? "#ef4444" : "#f59e0b";
  const y = useAdFit ? item.adFitY : item.attentionY;
  const score = Math.round(useAdFit ? item.segment.ad_fit_score : item.segment.attention_score);
  const labelY = y < 92 ? y + 42 : y - 22;
  return (
    <g>
      <circle cx={item.x} cy={y} r="9" fill={color} />
      <circle cx={item.x} cy={y} r="16" fill="none" stroke={color} strokeOpacity="0.28" strokeWidth="4" />
      <line x1={item.x} x2={item.x} y1={y} y2={labelY + (labelY > y ? -14 : 8)} stroke={color} strokeOpacity="0.65" />
      <g transform={`translate(${Math.max(92, Math.min(828, item.x)) - 76} ${labelY - 18})`}>
        <rect width="152" height="36" rx="8" fill="#050505" stroke={color} strokeOpacity="0.55" />
        <text x="12" y="15" fontSize="11" fill="#a1a1aa">
          {label}
        </text>
        <text x="12" y="29" fontSize="12" fill="#f8fafc">
          {formatRange(item.segment.start, item.segment.end)} · {score}
        </text>
      </g>
    </g>
  );
}

function TrendMoment({ title, segment, tone, showAdFit = false }: { title: string; segment: Segment; tone: "success" | "danger" | "warning"; showAdFit?: boolean }) {
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
      <span title="Timestamp card showing the strongest or weakest segment detected from the score timeline.">
        <Badge tone={tone}>{title}</Badge>
      </span>
      <p className="mt-3 text-xl font-semibold text-white">{formatRange(segment.start, segment.end)}</p>
      <p className="mt-2 text-base text-slate-500">
        Attention {Math.round(segment.attention_score)}
        {showAdFit ? ` · Ad fit ${Math.round(segment.ad_fit_score)}` : null}
      </p>
    </div>
  );
}

function Moment({ title, moment, danger = false }: { title: string; moment: { start: number; end: number; score: number } | null; danger?: boolean }) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between text-slate-400">
        <GuidedLabel
          label={title}
          guide={danger ? "Lowest attention moment; use it to decide where to rewrite, trim, or avoid ad placement." : "Strongest early moment; use it to understand hook pacing and opening strength."}
        />
        {danger ? <TrendingDown className="h-5 w-5 text-danger" /> : <TrendingUp className="h-5 w-5 text-success" />}
      </div>
      <p className="mt-4 text-3xl font-semibold">{moment ? formatRange(moment.start, moment.end) : "--"}</p>
      <p className="mt-2 text-base text-slate-500">Score {moment?.score ?? 0}</p>
    </Card>
  );
}

function SegmentsTab({ segments }: { segments: Segment[] }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      <Card className="h-80 p-5">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={segments.map((segment) => ({ time: formatRange(segment.start, segment.end), attention: segment.attention_score, adFit: segment.ad_fit_score, confidence: segment.recommendation_confidence ?? 0 }))}>
            <CartesianGrid stroke="#202020" />
            <XAxis dataKey="time" stroke="#64748B" fontSize={13} />
            <YAxis stroke="#64748B" fontSize={13} />
            <RechartsTooltip content={<ChartTooltip />} />
            <Bar dataKey="attention" fill="#F8FAFC" radius={[4, 4, 0, 0]} />
            <Bar dataKey="adFit" fill="#F59E0B" radius={[4, 4, 0, 0]} />
            <Bar dataKey="confidence" fill="#22C55E" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <div className="space-y-3">
        {segments.slice(0, 5).map((segment) => (
          <Card key={segment.id} className="p-5">
            <div className="flex items-center justify-between gap-3">
              <p className="text-lg font-semibold">{formatRange(segment.start, segment.end)}</p>
              <Badge tone={tierTone(segment.recommendation_tier ?? "Edit before monetization")}>{segment.recommendation_tier ?? segment.label}</Badge>
            </div>
            <p className="mt-3 text-base leading-7 text-slate-400">{segment.summary}</p>
            <p className="mt-3 text-sm text-slate-500">Confidence {Math.round(segment.recommendation_confidence ?? 0)} · {evidenceModeLabel(segment.evidence_mode)}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}

function ObjectsTab({ segments }: { segments: Segment[] }) {
  const rows = segments.flatMap((segment) => segment.objects.map((object) => ({ ...object, time: formatRange(segment.start, segment.end) })));
  return <SimpleRows rows={rows.map((row) => [row.time, row.label, `${Math.round(row.confidence * 100)}%`])} headers={["Time", "Object", "Confidence"]} />;
}

function TranscriptTab({ segments }: { segments: Segment[] }) {
  const compactedCount = segments.filter((segment, index) => transcriptDisplayForSegment(segment, segments[index - 1]).compacted).length;
  const flaggedCount = segments.filter((segment) => (segment.transcript_insights?.transcript_quality_flags ?? []).length).length;
  const noSpeechCount = segments.filter((segment) => !normalizedWhitespace(segment.transcript)).length;
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="grid gap-4 md:grid-cols-4">
          <TranscriptStat label="Average confidence" value={String(averageTranscriptConfidence(segments))} />
          <TranscriptStat label="Flagged segments" value={String(flaggedCount)} />
          <TranscriptStat label="Compacted repeats" value={String(compactedCount)} />
          <TranscriptStat label="No speech" value={String(noSpeechCount)} />
        </div>
      </Card>
      {segments.map((segment, index) => {
        const transcriptDisplay = transcriptDisplayForSegment(segment, segments[index - 1]);
        const flags = segment.transcript_insights?.transcript_quality_flags ?? [];
        return (
          <Card key={segment.id} className="p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="cyan">{formatRange(segment.start, segment.end)}</Badge>
              <Badge tone={tierTone(segment.recommendation_tier ?? "Edit before monetization")}>{segment.recommendation_tier ?? "Edit before monetization"}</Badge>
              {transcriptDisplay.compacted ? <Badge tone="warning">Repeated text compacted</Badge> : null}
              {segment.topics.map((topic) => (
                <Badge key={topic.label}>{topic.label}</Badge>
              ))}
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-500">
              Transcript confidence {Math.round(segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0)}
              {flags.length ? ` · Flags: ${flags.join(", ")}` : ""}
            </p>
            <p className="mt-4 text-base leading-8 text-slate-200 md:text-lg">
              {transcriptDisplay.text || (transcriptDisplay.repeatedOnly ? "Repeated from previous segment." : "No speech detected.")}
            </p>
          </Card>
        );
      })}
    </div>
  );
}

function TranscriptStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
    </div>
  );
}

function EvidenceTab({ segments }: { segments: Segment[] }) {
  return (
    <div className="space-y-4">
      <Card className="p-5"><p className="font-semibold text-white">What this view shows</p><p className="mt-2 text-sm leading-6 text-slate-500">Each card explains one moment in plain language. Use the coloured scores to see what is working and what needs a closer look.</p></Card>
      {segments.map((segment) => {
        const confidence = Math.round(segment.recommendation_confidence ?? 0);
        const transcript = Math.round(segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0);
        const visual = Math.round((segment.visual_evidence?.visual_quality ?? 0) * 100);
        const safety = Math.round(segment.brand_safety_score ?? 100);
        const risk = Math.round(segment.drop_risk_score ?? 0);
        return <Card key={segment.id} className="min-w-0 p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex flex-wrap gap-2"><Badge tone="cyan">{formatRange(segment.start, segment.end)}</Badge><Badge tone={tierTone(segment.recommendation_tier ?? "Edit before monetization")}>{segment.recommendation_tier ?? "Edit before monetization"}</Badge></div><p className="mt-3 text-base leading-7 text-slate-300">{segment.summary || segment.recommendation || "No summary is available for this moment."}</p></div><Badge tone={confidence >= 70 ? "success" : confidence >= 45 ? "warning" : "danger"}>Confidence {confidence}/100</Badge></div><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><EvidenceMetric label="Speech" value={transcript} /><EvidenceMetric label="Visuals" value={visual} /><EvidenceMetric label="Safety" value={safety} /><EvidenceMetric label="Drop risk" value={risk} inverse /></div><div className="mt-5 grid gap-4 lg:grid-cols-2"><SignalBlock title="What worked" signals={segment.strong_signals ?? []} empty="No strong signals were found." tone="success" /><SignalBlock title="What needs work" signals={segment.failed_or_weak_signals ?? []} empty="No weak signals were found." tone="warning" /></div>{segment.score_reasons?.length ? <p className="mt-4 border-t border-white/10 pt-4 text-sm leading-6 text-slate-500"><span className="font-medium text-slate-300">Why the score changed:</span> {segment.score_reasons.slice(0, 4).join(" · ")}</p> : null}</Card>;
      })}
    </div>
  );
}

function EvidenceMetric({ label, value, inverse = false }: { label: string; value: number; inverse?: boolean }) {
  const tone = inverse ? value <= 25 ? "success" : value <= 50 ? "warning" : "danger" : value >= 70 ? "success" : value >= 45 ? "warning" : "danger";
  const color = tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : "text-danger";
  return <div className="rounded-lg border border-white/10 bg-zinc-950 p-3"><p className="text-xs text-slate-500">{label}{inverse ? " (lower is better)" : ""}</p><p className={`mt-2 text-xl font-semibold ${color}`}>{value}/100</p></div>;
}

function SignalBlock({ title, signals, empty, tone }: { title: string; signals: string[]; empty: string; tone: "success" | "warning" }) {
  return <div><p className="text-sm font-semibold text-white">{title}</p><div className="mt-2 flex flex-wrap gap-2">{signals.length ? signals.map((signal) => <Badge key={signal} tone={tone}>{signal}</Badge>) : <p className="text-sm text-slate-500">{empty}</p>}</div></div>;
}

function AdMatchesTab({ segments }: { segments: Segment[] }) {
  const rows = segments.flatMap((segment) =>
    segment.ad_matches.map((match) => [
      formatRange(segment.start, segment.end),
      [segment.objects.map((object) => object.label).join(" + "), segment.topics.map((topic) => topic.label).join(", ")].filter(Boolean).join(" / ") || "General context",
      match.ad_category,
      String(Math.round(segment.attention_score)),
      String(Math.round(match.ad_fit_score)),
      segment.recommendation_tier ?? (match.ad_fit_score >= 75 ? "Strong ad slot" : match.ad_fit_score >= 45 ? "Conditional ad slot" : "Avoid")
    ])
  );
  return <SimpleRows rows={rows} headers={["Time", "Detected context", "Suggested Ad", "Attention", "Ad Fit", "Recommendation Tier"]} />;
}

function RecommendationsTab({ recommendations }: { recommendations: { title: string; timestamp: string; body: string }[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {recommendations.map((item) => (
        <Card key={`${item.title}-${item.timestamp}`} className="p-6">
          <Badge tone="cyan">{item.timestamp}</Badge>
          <h3 className="mt-4 text-xl font-semibold">{item.title}</h3>
          <p className="mt-3 text-base leading-7 text-slate-400">{item.body}</p>
        </Card>
      ))}
    </div>
  );
}

function SimpleRows({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[760px] border-collapse bg-card text-left text-base">
        <thead className="bg-surface text-slate-400">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-5 py-4 font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, index) => (
              <tr key={index} className="border-t border-border">
                {row.map((cell, cellIndex) => (
                  <td key={`${index}-${cellIndex}`} className="px-5 py-4 leading-7 text-slate-300">
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td className="px-5 py-8 text-center text-slate-500" colSpan={headers.length}>
                No matching rows.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
