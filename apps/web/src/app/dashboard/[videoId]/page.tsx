"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleHelp, Download, FileJson, Search } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
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
import { InsightReportLauncher } from "@/components/insight-report-launcher";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { capture } from "@/lib/analytics";
import { absoluteMediaUrl, exportUrl, formatRange, getAnalysis } from "@/lib/api";
import { useExplorerStore } from "@/lib/store";
import type { AnalysisPayload, RecommendationTier, Segment } from "@/lib/types";

const tabs = ["Segments", "Objects", "Transcript", "Evidence", "Ad Matches", "Recommendations"] as const;

export default function DashboardPage() {
  const params = useParams<{ videoId: string }>();
  const videoId = params.videoId;
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("Segments");
  const [query, setQuery] = useState("");
  const [seekTarget, setSeekTarget] = useState<{ time: number; requestId: number } | null>(null);
  const setSelectedSegment = useExplorerStore((state) => state.setSelectedSegment);

  const analysisQuery = useQuery({
    queryKey: ["analysis", videoId],
    queryFn: () => getAnalysis(videoId)
  });

  const analysis = analysisQuery.data;
  const analyzedVideoId = analysis?.video.id;
  const analyzedSourceType = analysis?.video.source_type;
  useEffect(() => {
    if (!analyzedVideoId || !analyzedSourceType) return;
    capture("dashboard_viewed", { video_id: analyzedVideoId, source_type: analyzedSourceType });
  }, [analyzedSourceType, analyzedVideoId]);

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

  const handleSignalSeek = (time: number) => {
    setSeekTarget({ time, requestId: Date.now() });
    const segment = analysis?.segments.find((item) => time >= item.start && time < item.end);
    if (segment) setSelectedSegment(segment);
    window.setTimeout(() => document.getElementById("video-preview")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };

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
      <div className="dashboard-ui mx-auto max-w-[1440px] px-4 py-6 lg:px-6 lg:py-8">
        <header className="dashboard-report-header flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div>
            <Badge tone="cyan">Video report</Badge>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight md:text-4xl">{analysis.video.title}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400 md:text-base">
              Clear video findings, the best ad moment, and simple next steps for your review.
            </p>
          </div>
          <div className="dashboard-export-actions flex flex-wrap gap-2">
            <a
              href={exportUrl(videoId, "csv")}
              onClick={() => capture("report_exported", { target_type: "video", video_id: videoId, export_format: "csv" })}
            >
              <Button variant="secondary">
                <Download className="h-4 w-4" /> CSV
              </Button>
            </a>
            <a
              href={exportUrl(videoId, "json")}
              onClick={() => capture("report_exported", { target_type: "video", video_id: videoId, export_format: "json" })}
            >
              <Button variant="secondary">
                <FileJson className="h-4 w-4" /> JSON
              </Button>
            </a>
          </div>
        </header>

        <DashboardHeroMetrics analysis={analysis} />

        <DashboardReadinessRail analysis={analysis} />

        <section className="dashboard-section mt-5">
          <SectionTitle title="Decision signals" body="The few signals that matter most for a placement decision, with a direct next step for each." />
          <DashboardDecisionSignals analysis={analysis} onSeek={handleSignalSeek} />
        </section>

        <EvidenceReadiness analysis={analysis} />

        <section className="dashboard-video-layout mt-6 grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
          <VideoPreview analysis={analysis} seekTarget={seekTarget} />
          <PlacementDecision analysis={analysis} />
        </section>

        <InsightReportLauncher targetType="video" targetId={analysis.video.id} initial={analysis.detailed_insight_report} />

        <section className="mt-6">
          <BrandFitPanel videoId={videoId} />
        </section>

        <section className="mt-6">
          <PrePostKeywords analysis={analysis} />
        </section>

        <section className="mt-6">
          <OverallVideoTrend segments={analysis.segments} />
        </section>

        <section className="mt-5">
          <DashboardViewerResponse analysis={analysis} />
        </section>

        <DashboardSignalTimeline analysis={analysis} onSeek={handleSignalSeek} />

        <section className="mt-6">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 className="text-2xl font-semibold">Viewer attention over time</h2>
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-500" />
              <label htmlFor="segment-evidence-filter" className="sr-only">Filter segment evidence</label>
              <input
                id="segment-evidence-filter"
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

        <section id="segment-evidence" className="dashboard-evidence-console mt-8">
          <Card className="overflow-hidden p-0">
            <div className="dashboard-evidence-console__nav">
              <div className="dashboard-evidence-console__tabs" role="tablist" aria-label="Segment evidence views">
                {tabs.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab}
                    onClick={() => {
                      setActiveTab(tab);
                      if (tab === "Evidence" || tab === "Recommendations") {
                        capture("recommendation_evidence_opened", { video_id: videoId, tab: tab.toLowerCase() });
                      }
                    }}
                    className={activeTab === tab ? "is-active" : undefined}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <Badge tone="cyan">Evidence verified</Badge>
            </div>
            <div className="dashboard-evidence-console__body">
            {activeTab === "Segments" ? <SegmentsTab segments={filteredSegments} /> : null}
            {activeTab === "Objects" ? <ObjectsTab segments={filteredSegments} /> : null}
            {activeTab === "Transcript" ? <TranscriptTab segments={filteredSegments} /> : null}
            {activeTab === "Evidence" ? <EvidenceTab segments={filteredSegments} /> : null}
            {activeTab === "Ad Matches" ? <AdMatchesTab segments={filteredSegments} /> : null}
            {activeTab === "Recommendations" ? <RecommendationsTab analysis={analysis} /> : null}
            </div>
          </Card>
        </section>
      </div>
      <SegmentDrawer videoId={videoId} />
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

function DashboardHeroMetrics({ analysis }: { analysis: AnalysisPayload }) {
  const summary = analysis.summary;
  const metrics = [
    {
      label: "Overall attention",
      value: summary.overall_attention_score,
      detail: "Likelihood viewers stay engaged",
      tone: summary.overall_attention_score >= 70 ? "success" : summary.overall_attention_score >= 40 ? "warning" : "danger"
    },
    {
      label: "Drop risk",
      value: summary.overall_drop_risk_score ?? 0,
      detail: "Risk of viewers losing interest",
      tone: (summary.overall_drop_risk_score ?? 0) <= 30 ? "success" : (summary.overall_drop_risk_score ?? 0) <= 60 ? "warning" : "danger"
    },
    {
      label: "Monetization opportunity",
      value: summary.monetization_opportunity_score,
      detail: "Potential revenue from ad placements",
      tone: summary.monetization_opportunity_score >= 70 ? "success" : summary.monetization_opportunity_score >= 40 ? "warning" : "danger"
    },
    {
      label: "Creator readiness",
      value: summary.creator_readiness_score ?? 0,
      detail: "How prepared the content is for review",
      tone: (summary.creator_readiness_score ?? 0) >= 70 ? "success" : (summary.creator_readiness_score ?? 0) >= 40 ? "warning" : "danger"
    },
    {
      label: "Brand safety",
      value: summary.brand_safety_score ?? 100,
      detail: "Suitability for advertiser association",
      tone: (summary.brand_safety_score ?? 100) >= 70 ? "success" : (summary.brand_safety_score ?? 100) >= 40 ? "warning" : "danger"
    },
    {
      label: "Visual quality",
      value: summary.visual_quality_score ?? 0,
      detail: "Clarity and usability of sampled frames",
      tone: (summary.visual_quality_score ?? 0) >= 70 ? "success" : (summary.visual_quality_score ?? 0) >= 40 ? "warning" : "danger"
    }
  ] satisfies { label: string; value: number; detail: string; tone: "success" | "warning" | "danger" }[];

  return (
    <section className="dashboard-hero-metrics mt-6" aria-label="Headline report scores">
      {metrics.map((metric) => (
        <Card key={metric.label} className={`dashboard-score-card dashboard-score-card--${metric.tone} p-4`}>
          <p className="dashboard-kicker">{metric.label}</p>
          <div className="mt-2 flex items-end justify-between gap-3">
            <p className="dashboard-score-value">{Math.round(metric.value)}</p>
            <Badge tone={metric.tone}>{metric.tone === "success" ? "Strong" : metric.tone === "warning" ? "Review" : "Needs work"}</Badge>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">{metric.detail}</p>
        </Card>
      ))}
    </section>
  );
}

function DashboardReadinessRail({ analysis }: { analysis: AnalysisPayload }) {
  const summary = analysis.summary;
  const bestWindow = summary.best_ad_slot ?? summary.best_content_window;
  const confidence = Math.round(
    averageTranscriptConfidence(analysis.segments) * 0.35
      + (summary.visual_quality_score ?? 0) * 0.25
      + objectEvidenceScore(analysis.segments) * 0.2
      + (summary.brand_safety_score ?? 100) * 0.2
  );
  const items = [
    { label: "Top category", value: summary.top_ad_category ?? "No confident match", tone: "danger" },
    { label: "Placement window", value: bestWindow ? formatRange(bestWindow.start, bestWindow.end) : "Not available", tone: bestWindow ? "warning" : "danger" },
    { label: "Best ad slot", value: summary.best_ad_slot ? "Candidate found" : "Review needed", tone: summary.best_ad_slot ? "success" : "warning" },
    { label: "Evidence confidence", value: `${confidence}/100`, tone: confidence >= 70 ? "success" : confidence >= 45 ? "warning" : "danger" }
  ];

  return (
    <section className="dashboard-readiness-rail mt-3" aria-label="Placement readiness summary">
      {items.map((item) => (
        <div key={item.label} className={`dashboard-readiness-item dashboard-readiness-item--${item.tone}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
      <div className="dashboard-readiness-recommendation">
        <span>Recommendation confidence</span>
        <div><i><b style={{ width: `${Math.max(4, Math.min(100, confidence))}%` }} /></i><strong>{summary.recommendation_status ?? summary.best_recommendation_tier ?? "Review before placement"}</strong></div>
      </div>
    </section>
  );
}

function DashboardDecisionSignals({ analysis, onSeek }: { analysis: AnalysisPayload; onSeek: (time: number) => void }) {
  const fallback = [
    {
      key: "attention",
      name: "Content momentum",
      label: analysis.summary.overall_attention_score >= 50 ? "Holding" : "Needs work",
      confidence: "Medium",
      confidence_score: analysis.summary.overall_attention_score,
      timestamp: analysis.summary.best_hook ? { start: analysis.summary.best_hook.start, label: formatRange(analysis.summary.best_hook.start, analysis.summary.best_hook.end) } : { start: 0, label: "00:00" },
      reasons: ["Attention, pacing, and visual change are combined."],
      next_action: "Use the strongest moment as the model for the opening."
    },
    {
      key: "placement",
      name: "Placement readiness",
      label: analysis.summary.recommendation_status ?? "Review",
      confidence: "Medium",
      confidence_score: analysis.summary.best_ad_slot?.recommendation_confidence ?? 0,
      timestamp: analysis.summary.best_content_window ? { start: analysis.summary.best_content_window.start, label: formatRange(analysis.summary.best_content_window.start, analysis.summary.best_content_window.end) } : { start: 0, label: "00:00" },
      reasons: ["Attention, fit, safety, and contextual evidence are checked together."],
      next_action: "Review the recommended window before approving a placement."
    }
  ];
  const metrics = analysis.decision_metrics?.length ? analysis.decision_metrics.slice(0, 6) : fallback;

  return (
    <div className="dashboard-decision-grid mt-3">
      {metrics.map((metric) => {
        const score = Math.round(metric.confidence_score ?? 0);
        const tone = score >= 70 ? "success" : score >= 45 ? "warning" : "danger";
        return (
          <button key={metric.key} type="button" className={`dashboard-decision-card dashboard-decision-card--${tone}`} onClick={() => onSeek(metric.timestamp.start)}>
            <div><span>{metric.name}</span><Badge tone={tone}>{metric.confidence} confidence</Badge></div>
            <strong>{metric.label}</strong>
            <p>{metric.reasons[0] ?? "Evidence is being combined for this signal."}</p>
            <footer><b>{metric.timestamp.label}</b><em>{metric.next_action}</em></footer>
          </button>
        );
      })}
    </div>
  );
}

function DashboardViewerResponse({ analysis }: { analysis: AnalysisPayload }) {
  const summary = analysis.summary;
  const rows = [
    { label: "Overall attention", value: summary.overall_attention_score, inverse: false },
    { label: "Campaign opportunity", value: summary.monetization_opportunity_score, inverse: false },
    { label: "Viewer drop risk", value: summary.overall_drop_risk_score ?? 0, inverse: true },
    { label: "Brand safety", value: summary.brand_safety_score ?? 100, inverse: false },
    { label: "Visual clarity", value: summary.visual_quality_score ?? 0, inverse: false },
    { label: "Speech clarity", value: averageTranscriptConfidence(analysis.segments), inverse: false }
  ];
  return (
    <Card className="dashboard-response-panel p-5">
      <div className="dashboard-panel-heading"><div><span>Viewer response</span><h2>What the signals say</h2></div><Badge tone="cyan">Live analysis</Badge></div>
      <div className="dashboard-response-rows">
        {rows.map((row) => {
          const strength = row.inverse ? 100 - row.value : row.value;
          const tone = strength >= 70 ? "success" : strength >= 40 ? "warning" : "danger";
          return <div key={row.label} className={`dashboard-response-row dashboard-response-row--${tone}`}><span>{row.label}</span><i><b style={{ width: `${Math.max(2, Math.min(100, row.value))}%` }} /></i><strong>{Math.round(row.value)}/100</strong></div>;
        })}
      </div>
      <div className="dashboard-response-moments">
        <div><span>Best hook</span><strong>{summary.best_hook ? formatRange(summary.best_hook.start, summary.best_hook.end) : "Not found"}</strong></div>
        <div><span>Weakest point</span><strong>{summary.weakest_segment ? formatRange(summary.weakest_segment.start, summary.weakest_segment.end) : "Not found"}</strong></div>
      </div>
    </Card>
  );
}

function DashboardSignalTimeline({ analysis, onSeek }: { analysis: AnalysisPayload; onSeek: (time: number) => void }) {
  const points = analysis.timeline_summary?.points ?? [];
  if (!points.length) return null;
  const lanes = [
    { key: "visual" as const, label: "Visual movement", accent: "#1cc9be" },
    { key: "audio" as const, label: "Audio energy", accent: "#1cc9be" },
    { key: "narrative" as const, label: "Narrative novelty", accent: "#b66cff" },
    { key: "social" as const, label: "Social variety", accent: "#f2aa10" }
  ];
  const valueFor = (point: NonNullable<AnalysisPayload["timeline_summary"]>["points"][number], key: "visual" | "audio" | "narrative" | "social") => {
    const family = point[key];
    const raw = typeof family?.confidence === "number"
      ? family.confidence
      : Object.values(family ?? {}).find((value) => typeof value === "number");
    return typeof raw === "number" ? Math.max(0, Math.min(100, Math.round(raw <= 1 ? raw * 100 : raw))) : 0;
  };
  return (
    <Card className="dashboard-signal-timeline mt-6 p-5">
      <div className="dashboard-panel-heading"><div><span>Signal timeline</span><h2>What changes across the video</h2></div><p>Tap any marker to inspect that moment.</p></div>
      <div className="dashboard-signal-lanes">
        {lanes.map((lane) => <div key={lane.key} className="dashboard-signal-lane"><span>{lane.label}</span><div>{points.map((point) => {
          const strength = valueFor(point, lane.key);
          return <button key={`${lane.key}-${point.start}`} type="button" onClick={() => onSeek(point.start)} title={`${lane.label} · ${point.label}`} style={{ "--signal-accent": lane.accent, "--signal-opacity": `${0.12 + strength / 115}` } as React.CSSProperties} />;
        })}</div></div>)}
      </div>
    </Card>
  );
}

function VideoPreview({ analysis, seekTarget }: { analysis: AnalysisPayload; seekTarget: { time: number; requestId: number } | null }) {
  const videoUrl = absoluteMediaUrl(analysis.video.file_url);
  const thumbnailUrl = absoluteMediaUrl(analysis.video.thumbnail);
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!seekTarget || !videoRef.current) return;
    videoRef.current.currentTime = seekTarget.time;
  }, [seekTarget]);
  return (
    <div id="video-preview">
      <Card className="overflow-hidden bg-black">
      <div className="border-b border-white/10 p-6">
        <GuidedLabel label="Video Preview" guide="Preview the uploaded or ingested media while reviewing the scoring evidence." />
      </div>
      <div className="ph-no-capture aspect-video bg-zinc-950">
        {videoUrl ? (
          <video id="video-preview-player" ref={videoRef} className="h-full w-full bg-black object-contain" src={videoUrl} poster={thumbnailUrl ?? undefined} controls preload="metadata" />
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
    </div>
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
  const attentionPath = data.map((item) => `${item.x},${item.attentionY}`).join(" ");
  const dropRiskPath = data.map((item) => `${item.x},${item.dropRiskY}`).join(" ");
  const trendCopy = trendLabel(safeSegments);
  const hovered = hoveredIndex === null ? null : data[hoveredIndex];
  const tickCount = Math.min(5, Math.max(2, safeSegments.length));
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
    <Card className="dashboard-overall-trend overflow-hidden border-white/10 bg-black">
      <div className="dashboard-trend-header border-b border-white/10">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="dashboard-kicker">{trendCopy.kicker}</p>
            <h2>{trendCopy.title}</h2>
            <p>{trendCopy.action}</p>
          </div>
          <div className="dashboard-trend-summary" aria-label="Trend summary">
            <div><span>Avg attention</span><strong>{average}</strong></div>
            <div><span>Avg drop risk</span><strong>{Math.round(mean(safeSegments.map((segment) => segment.drop_risk_score ?? 0)))}</strong></div>
            <div><span>Brand safety</span><strong>{Math.round(mean(safeSegments.map((segment) => segment.brand_safety_score ?? 100)))}</strong></div>
          </div>
        </div>
      </div>

      <div className="dashboard-trend-body">
        <div className="dashboard-trend-legend" aria-label="Graph legend">
          <span><i className="dashboard-trend-legend__attention" />Attention</span>
          <span><i className="dashboard-trend-legend__risk" />Viewer drop risk</span>
          <p>Hover any point for the complete score breakdown.</p>
        </div>
        <div className="dashboard-trend-canvas">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-[340px] w-full"
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

            {[0, 50, 100].map((value) => {
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

            <polygon
              points={`${attentionPath} ${data[data.length - 1].x},${padding.top + chartHeight} ${data[0].x},${padding.top + chartHeight}`}
              fill="url(#attentionTrendFill)"
            />
            <polyline points={dropRiskPath} fill="none" stroke="#f43f6b" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" strokeDasharray="6 8" opacity="0.72" />
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

            {ticks.map((item) => (
              <text key={`${item.segment.id}-tick`} x={item.x} y={height - 24} textAnchor="middle" fontSize="12" fill="#71717a">
                {formatRange(item.segment.start, item.segment.end)}
              </text>
            ))}
          </svg>
        </div>

        <div className="dashboard-trend-moments">
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
  const grouped = new Map<string, { count: number; total: number }>();
  segments.flatMap((segment) => segment.objects).forEach((object) => {
    const current = grouped.get(object.label) ?? { count: 0, total: 0 };
    grouped.set(object.label, { count: current.count + 1, total: current.total + object.confidence });
  });
  const summary = [...grouped.entries()]
    .map(([label, value]) => ({ label, count: value.count, confidence: Math.round((value.total / value.count) * 100) }))
    .sort((left, right) => right.confidence - left.confidence || right.count - left.count)
    .slice(0, 6);
  const events = segments.filter((segment) => segment.objects.length).slice(0, 6);

  return (
    <div className="dashboard-evidence-split">
      <div className="dashboard-evidence-summary">
        <EvidencePaneTitle title="Object detection summary" body="The strongest visual objects found across the selected timestamps." />
        <div className="dashboard-evidence-bars">
          {summary.length ? summary.map((item) => <EvidenceBar key={item.label} label={item.label} value={item.confidence} detail={`${item.count} moment${item.count === 1 ? "" : "s"}`} />) : <EvidenceEmpty body="No reliable objects were found in these timestamps." />}
        </div>
        <div className="dashboard-evidence-stats mt-6">
          <EvidenceStat label="Object events" value={String(segments.reduce((total, segment) => total + segment.objects.length, 0))} />
          <EvidenceStat label="Unique objects" value={String(grouped.size)} />
          <EvidenceStat label="Strongest" value={summary[0]?.label ?? "None"} />
        </div>
      </div>
      <div className="dashboard-evidence-events">
        {events.length ? events.map((segment) => {
          const confidence = Math.round(Math.max(...segment.objects.map((object) => object.confidence), 0) * 100);
          const labels = segment.objects.slice(0, 4).map((object) => object.label);
          return <EvidenceEventCard key={segment.id} time={formatRange(segment.start, segment.end)} title={`${labels[0] ?? "Visual object"} detected`} confidence={confidence} body={segment.summary || "Visual context was detected in this moment."} tags={labels} />;
        }) : <EvidenceEmpty body="No object evidence is available for the selected segments." />}
      </div>
    </div>
  );
}

function TranscriptTab({ segments }: { segments: Segment[] }) {
  const compactedCount = segments.filter((segment, index) => transcriptDisplayForSegment(segment, segments[index - 1]).compacted).length;
  const flaggedCount = segments.filter((segment) => (segment.transcript_insights?.transcript_quality_flags ?? []).length).length;
  const noSpeechCount = segments.filter((segment) => !normalizedWhitespace(segment.transcript)).length;
  const totalWords = segments.reduce((total, segment) => total + (segment.transcript_insights?.word_count ?? normalizedWhitespace(segment.transcript).split(" ").filter(Boolean).length), 0);
  const totalDuration = segments.reduce((total, segment) => total + Math.max(0, segment.end - segment.start), 0);
  const coverage = segments.length ? Math.round(((segments.length - noSpeechCount) / segments.length) * 100) : 0;
  return (
    <div className="dashboard-evidence-split">
      <div className="dashboard-evidence-summary">
        <EvidencePaneTitle title="Speech analysis" body="Transcript coverage, clarity, and the moments that need a closer review." />
        <div className="dashboard-transcript-rail">
          {segments.slice(0, 7).map((segment, index) => {
            const display = transcriptDisplayForSegment(segment, segments[index - 1]);
            return <div key={segment.id}><span>{formatRange(segment.start, segment.end)}</span><strong>{display.text || "Silence"}</strong></div>;
          })}
        </div>
        <div className="dashboard-evidence-stats mt-5">
          <EvidenceStat label="Total words" value={String(totalWords)} />
          <EvidenceStat label="Words/sec" value={totalDuration ? (totalWords / totalDuration).toFixed(1) : "0"} />
          <EvidenceStat label="Coverage" value={`${coverage}%`} />
          <EvidenceStat label="Flagged" value={String(flaggedCount + compactedCount)} />
        </div>
      </div>
      <div className="dashboard-evidence-events">
        {segments.slice(0, 6).map((segment, index) => {
          const display = transcriptDisplayForSegment(segment, segments[index - 1]);
          const confidence = Math.round(segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0);
          const flags = segment.transcript_insights?.transcript_quality_flags ?? [];
          return <EvidenceEventCard key={segment.id} time={formatRange(segment.start, segment.end)} title={`Transcript confidence: ${confidence}%`} confidence={confidence} body={display.text || (display.repeatedOnly ? "Repeated from previous segment." : "No spoken words detected in this segment.")} tags={flags.length ? flags : display.text ? ["speech"] : ["silence", "no-caption"]} />;
        })}
      </div>
    </div>
  );
}

function EvidenceTab({ segments }: { segments: Segment[] }) {
  const selected = segments.slice(0, 7);
  const rows = [
    { label: "Visual", value: (segment: Segment) => Math.round((segment.visual_evidence?.visual_quality ?? 0) * 100) },
    { label: "Audio", value: (segment: Segment) => Math.round((segment.audio_evidence?.confidence ?? 0) * 100) },
    { label: "Context", value: (segment: Segment) => Math.round(segment.recommendation_confidence ?? 0) },
    { label: "Objects", value: (segment: Segment) => Math.min(100, segment.objects.length * 20) },
    { label: "Transcript", value: (segment: Segment) => Math.round(segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0) }
  ];
  return (
    <div className="dashboard-evidence-split">
      <div className="dashboard-evidence-summary">
        <EvidencePaneTitle title="Evidence strength map" body="Each cell shows how much support a timestamp has from a specific modality." />
        <div className="dashboard-strength-map" style={{ gridTemplateColumns: `5rem repeat(${Math.max(1, selected.length)}, minmax(2.2rem, 1fr))` }}>
          <div />
          {selected.map((segment) => <span key={segment.id}>{formatRange(segment.start, segment.end)}</span>)}
          {rows.flatMap((row) => [
            <strong key={`${row.label}-label`}>{row.label}</strong>,
            ...selected.map((segment) => {
              const value = row.value(segment);
              return <i key={`${row.label}-${segment.id}`} style={{ "--evidence-strength": `${0.12 + value / 120}` } as React.CSSProperties}>{value}</i>;
            })
          ])}
        </div>
      </div>
      <div className="dashboard-evidence-events">
        {selected.map((segment) => {
          const visual = Math.round((segment.visual_evidence?.visual_quality ?? 0) * 100);
          const transcript = Math.round(segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0);
          const score = Math.round((visual + transcript + Math.round(segment.recommendation_confidence ?? 0)) / 3);
          return <EvidenceEventCard key={segment.id} time={formatRange(segment.start, segment.end)} title={`Multi-modal score: ${score}/100`} confidence={score} body={segment.summary || segment.recommendation || "Review the raw evidence for this timestamp."} tags={[`visual ${visual}`, `speech ${transcript}`, `safety ${Math.round(segment.brand_safety_score ?? 100)}`]} />;
        })}
      </div>
    </div>
  );
}

function AdMatchesTab({ segments }: { segments: Segment[] }) {
  const grouped = new Map<string, { total: number; count: number; segments: Segment[] }>();
  segments.forEach((segment) => segment.ad_matches.forEach((match) => {
    const current = grouped.get(match.ad_category) ?? { total: 0, count: 0, segments: [] };
    grouped.set(match.ad_category, { total: current.total + match.ad_fit_score, count: current.count + 1, segments: [...current.segments, segment] });
  }));
  const matches = [...grouped.entries()]
    .map(([category, value]) => ({ category, score: Math.round(value.total / value.count), count: value.count, segment: value.segments[0] }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 4);
  return (
    <div className="dashboard-evidence-split">
      <div className="dashboard-evidence-summary">
        <EvidencePaneTitle title="Ad category matching" body="Category fit is based on visual, topic, speech, and timing evidence." />
        <div className="dashboard-evidence-bars">
          {matches.length ? matches.map((match) => <EvidenceBar key={match.category} label={match.category} value={match.score} detail={match.score >= 60 ? "Primary match" : "Needs review"} />) : <EvidenceEmpty body="No confident ad categories were generated from the selected evidence." />}
        </div>
        <div className="dashboard-evidence-stats mt-6">
          <EvidenceStat label="Categories" value={String(matches.length)} />
          <EvidenceStat label="Strong matches" value={String(matches.filter((match) => match.score >= 60).length)} />
          <EvidenceStat label="Best fit" value={matches[0] ? `${matches[0].score}/100` : "--"} />
        </div>
      </div>
      <div className="dashboard-evidence-events">
        {matches.length ? matches.map((match) => <EvidenceEventCard key={match.category} time={formatRange(match.segment.start, match.segment.end)} title={`${match.category} — Match: ${match.score}%`} confidence={match.score} body={match.segment.ad_matches.find((item) => item.ad_category === match.category)?.reason || "Contextual fit needs a closer review before approval."} tags={[`${match.count} evidence point${match.count === 1 ? "" : "s"}`, match.score >= 60 ? "recommended" : "needs review"]} />) : <EvidenceEmpty body="No matching categories are available." />}
      </div>
    </div>
  );
}

function RecommendationsTab({ analysis }: { analysis: AnalysisPayload }) {
  const fallback = (analysis.decision_metrics ?? []).slice(0, 5).map((metric) => ({ title: metric.name, timestamp: metric.timestamp.label, body: metric.next_action }));
  const recommendations = analysis.recommendations.length ? analysis.recommendations : fallback;
  const summary = analysis.summary;
  const forecast = [
    { label: "Attention score", current: summary.overall_attention_score, target: Math.min(100, (summary.overall_attention_score ?? 0) + 25) },
    { label: "Contextual ad fit", current: summary.monetization_opportunity_score, target: Math.min(100, (summary.monetization_opportunity_score ?? 0) + 30) },
    { label: "Drop risk", current: summary.overall_drop_risk_score ?? 0, target: Math.max(0, (summary.overall_drop_risk_score ?? 0) - 30), inverse: true }
  ];
  return (
    <div className="dashboard-recommendations-layout">
      <div>
        <EvidencePaneTitle title="Actionable insights" body="Start with the highest-impact edit, then re-run analysis to confirm the improvement." />
        <div className="dashboard-recommendation-list">
          {recommendations.slice(0, 5).map((item, index) => (
            <article key={`${item.title}-${item.timestamp}`}>
              <b>{index + 1}</b>
              <div><h3>{item.title}</h3><p>{item.body}</p><span>{item.timestamp}</span></div>
              <Badge tone={index < 2 ? "danger" : index < 4 ? "warning" : "cyan"}>{index < 2 ? "High impact" : index < 4 ? "Medium impact" : "Review"}</Badge>
            </article>
          ))}
        </div>
      </div>
      <aside className="dashboard-improvement-forecast">
        <EvidencePaneTitle title="Improvement forecast" body="Estimated direction after the highest-priority edits are implemented." />
        {forecast.map((item) => <ForecastRow key={item.label} {...item} />)}
        <div><span>Estimated monetization uplift</span><strong>+{Math.max(20, Math.round((forecast[0].target - forecast[0].current) * 2.6))}%</strong></div>
      </aside>
    </div>
  );
}

function EvidencePaneTitle({ title, body }: { title: string; body: string }) {
  return <header className="dashboard-evidence-pane-title"><h2>{title}</h2><p>{body}</p></header>;
}

function EvidenceBar({ label, value, detail }: { label: string; value: number; detail: string }) {
  const tone = value >= 70 ? "success" : value >= 40 ? "warning" : "danger";
  return <div className={`dashboard-evidence-bar dashboard-evidence-bar--${tone}`}><div><span>{label}</span><strong>{value}/100</strong></div><i><b style={{ width: `${Math.max(2, Math.min(100, value))}%` }} /></i><small>{detail}</small></div>;
}

function EvidenceStat({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function EvidenceEventCard({ time, title, confidence, body, tags }: { time: string; title: string; confidence: number; body: string; tags: string[] }) {
  const tone = confidence >= 70 ? "success" : confidence >= 40 ? "warning" : "danger";
  return <article className="dashboard-evidence-event"><header><strong>{time}</strong><span>{title}</span><Badge tone={tone}>{confidence >= 60 ? "Evidence verified" : "Needs review"}</Badge></header><p>{body}</p><footer>{tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}</footer></article>;
}

function EvidenceEmpty({ body }: { body: string }) {
  return <div className="dashboard-evidence-empty">{body}</div>;
}

function ForecastRow({ label, current, target, inverse = false }: { label: string; current: number; target: number; inverse?: boolean }) {
  const displayTarget = Math.round(target);
  const width = inverse ? 100 - displayTarget : displayTarget;
  return <div className="dashboard-forecast-row"><div><span>{label}</span><strong>{Math.round(current)} <i>→</i> {displayTarget}</strong></div><b style={{ width: `${Math.max(3, Math.min(100, width))}%` }} /></div>;
}
