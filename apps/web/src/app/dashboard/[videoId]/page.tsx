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
import { SegmentDrawer } from "@/components/segment-drawer";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { exportUrl, formatRange, getAnalysis } from "@/lib/api";
import type { Segment } from "@/lib/types";

const tabs = ["Segments", "Objects", "Transcript", "Evidence", "Ad Matches", "Recommendations"] as const;

const metricGuides: Record<string, { definition: string; example: string }> = {
  "Overall Attention": {
    definition: "Weighted proxy score from visual movement, object clarity, speech pacing, topic clarity, and penalties.",
    example: "Example: a clear hook with motion and spoken context scores higher than a silent static scene."
  },
  Monetization: {
    definition: "Opportunity score combining top ad-fit moments, brand safety, attention, drop risk, and visual quality.",
    example: "Example: a safe productivity tutorial with visible laptop context can lift monetization."
  },
  "Creator Ready": {
    definition: "Upload-readiness score from attention, transcript clarity, visual quality, brand safety, and monetization.",
    example: "Example: low drop risk plus clear CTA indicates fewer edits before posting."
  },
  "Brand Safety": {
    definition: "Safety score after transcript risk and claim flags are checked.",
    example: "Example: risky claims like guaranteed cure reduce this score."
  },
  "Drop Risk": {
    definition: "Estimated risk that a segment loses viewer interest based on low attention, silence, repetition, and blur.",
    example: "Example: silent repetitive moments increase drop risk."
  },
  "Visual Quality": {
    definition: "Frame quality estimate from sharpness, exposure, contrast, and sampled visual evidence.",
    example: "Example: sharp, well-lit frames score higher than blurry or dark frames."
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
      <div className="mx-auto max-w-7xl px-5 py-8 lg:px-10">
        <header className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
          <div>
            <Badge tone="cyan">Attention Proxy Score</Badge>
            <h1 className="mt-4 text-3xl font-semibold md:text-5xl">{analysis.video.title}</h1>
            <p className="mt-3 max-w-3xl text-slate-400">
              Moment-level context, transcript topics, ad-fit scoring, and creator recommendations.
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

        <section className="mt-8 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <OverallVideoTrend segments={analysis.segments} />

          <div className="grid gap-4 sm:grid-cols-2">
            <Metric title="Overall Attention" value={analysis.summary.overall_attention_score} icon={<Zap className="h-5 w-5" />} />
            <Metric title="Monetization" value={analysis.summary.monetization_opportunity_score} icon={<TrendingUp className="h-5 w-5" />} />
            <Metric title="Creator Ready" value={analysis.summary.creator_readiness_score ?? 0} icon={<FileText className="h-5 w-5" />} />
            <Metric title="Brand Safety" value={analysis.summary.brand_safety_score ?? 100} icon={<ShieldCheck className="h-5 w-5" />} />
            <Metric title="Drop Risk" value={analysis.summary.overall_drop_risk_score ?? 0} icon={<AlertTriangle className="h-5 w-5" />} />
            <Metric title="Visual Quality" value={analysis.summary.visual_quality_score ?? 0} icon={<Eye className="h-5 w-5" />} />
            <Moment title="Best Hook" moment={analysis.summary.best_hook} />
            <Moment title="Weak Segment" moment={analysis.summary.weakest_segment} danger />
            <Card className="p-5 sm:col-span-2">
              <GuidedLabel label="Top Ad Category" guide="Highest-scoring category from the evidence-gated ad catalog. If no category has enough transcript, visual, or topic evidence, the report says no strong match." />
              <p className="mt-2 text-2xl font-semibold">{analysis.summary.top_ad_category}</p>
              <p className="mt-3 text-sm text-slate-500">
                Matched against {analysis.summary.ad_catalog_size ?? 0}+ generated ad categories. Reports are generated only from processed media frames, audio, transcripts, and detected visual context.
              </p>
            </Card>
          </div>
        </section>

        <section className="mt-6">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold">Attention Timeline</h2>
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter objects, topics, transcript..."
                className="h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-white/20"
              />
            </div>
          </div>
          <AttentionTimeline segments={filteredSegments} />
        </section>

        <section className="mt-8 space-y-4">
          <SectionTitle title="Diagnostic Visuals" body="Use these charts to compare evidence, brand readiness, and ad-slot quality before opening individual segment details." />
          <div className="grid gap-5 xl:grid-cols-2">
            <EvidenceHeatmap segments={filteredSegments} />
            <BrandFitRadar segments={filteredSegments} />
            <AttentionAdFitScatter segments={filteredSegments} />
            <ScoringMethodologyTable catalogSize={analysis.summary.ad_catalog_size ?? 0} />
          </div>
        </section>

        <section className="mt-8">
          <SectionTitle title="Segment Details" body="Filter and inspect the exact timestamp evidence behind objects, transcript, ad matches, and recommendations." />
          <div className="flex flex-wrap gap-2 border-b border-border">
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`border-b-2 px-3 py-3 text-sm font-semibold ${
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

function Metric({ title, value, icon }: { title: string; value: number; icon: React.ReactNode }) {
  const guide = metricGuides[title];
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-slate-400">
        <GuidedLabel label={title} guide={guide ? `${guide.definition} ${guide.example}` : undefined} />
        {icon}
      </div>
      <p className="mt-4 text-4xl font-semibold">{Math.round(value)}</p>
      {guide ? <p className="mt-2 text-xs leading-5 text-slate-500">{guide.definition}</p> : null}
    </Card>
  );
}

function GuidedLabel({ label, guide }: { label: string; guide?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-slate-400" title={guide}>
      {label}
      {guide ? <CircleHelp className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" /> : null}
    </span>
  );
}

function ChartHeader({ title, guide }: { title: string; guide: string }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <GuidedLabel label={title} guide={guide} />
        <p className="mt-1 text-xs leading-5 text-slate-500">{guide}</p>
      </div>
    </div>
  );
}

function SectionTitle({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h2 className="text-xl font-semibold text-zinc-100">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">{body}</p>
    </div>
  );
}

function LegendRow({ items }: { items: { label: string; color: string; description?: string; dash?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1 text-slate-300" title={item.description}>
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
    <div className="max-w-xs rounded-lg border border-white/10 bg-black/95 p-3 text-xs text-slate-200 shadow-glow">
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
      <div className="border-b border-white/10 p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.22em] text-slate-500">{trendCopy.kicker}</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">{trendCopy.title}</h2>
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

      <div className="p-5">
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
  if (avgDrop >= 65) {
    return { kicker: "Drop-risk trend", title: "High drop-risk moments need creator edits before ad placement" };
  }
  if (avgAdFit >= 60 && avgSafety >= 75) {
    return { kicker: "Brand-fit trend", title: "Strong ad-fit windows with acceptable brand safety" };
  }
  if (avgAttention >= 70) {
    return { kicker: "Attention trend", title: "Strong viewer-attention pattern across the timeline" };
  }
  return { kicker: "Overall video trend", title: "Attention, ad-fit, drop-risk, and safety movement" };
}

function mean(values: number[]) {
  if (!values.length) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function EvidenceHeatmap({ segments }: { segments: Segment[] }) {
  const rows = [
    { label: "Visual novelty", guide: "How different each segment looks from nearby frames.", value: (segment: Segment) => (segment.visual_evidence?.visual_novelty ?? 0) * 100 },
    { label: "Motion", guide: "Frame-to-frame visual movement.", value: (segment: Segment) => (segment.visual_evidence?.motion ?? 0) * 100 },
    { label: "Visual quality", guide: "Sharpness and exposure quality from sampled frames.", value: (segment: Segment) => (segment.visual_evidence?.visual_quality ?? 0) * 100 },
    { label: "Transcript clarity", guide: "Speech density, specificity, filler words, hook, and CTA signals.", value: (segment: Segment) => segment.transcript_insights?.clarity_score ?? 0 },
    { label: "Drop risk", guide: "Risk from weak attention, silence, blur, or repetition.", value: (segment: Segment) => segment.drop_risk_score ?? 0 },
    { label: "Brand safety", guide: "Safety after claims and risky transcript flags.", value: (segment: Segment) => segment.brand_safety_score ?? 100 }
  ];
  return (
    <Card className="p-5">
      <ChartHeader title="Evidence Heatmap" guide="Rows are scoring signals; columns are video segments. Brighter cells mean stronger signal or higher risk for that timestamp." />
      <div className="overflow-x-auto">
        <div className="min-w-[620px] space-y-2">
          <div className="grid gap-1" style={{ gridTemplateColumns: `150px repeat(${Math.max(1, segments.length)}, minmax(54px, 1fr))` }}>
            <div />
            {segments.map((segment) => (
              <div key={segment.id} className="truncate text-center text-[11px] text-slate-500" title={formatRange(segment.start, segment.end)}>
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
                    className="h-9 rounded border border-white/10 text-center text-[11px] leading-9 text-slate-200"
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
    <Card className="p-5">
      <ChartHeader title="Brand-Fit Radar" guide="Shows why the best available segment is or is not sponsor-ready across transcript, visual, object, attention, slot, and safety dimensions." />
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
    <Card className="p-5">
      <ChartHeader title="Attention vs Ad-Fit" guide="Each dot is a segment. Upper-right means the timestamp is both attention-worthy and brand-relevant; low safety or high risk should still be reviewed." />
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
      <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
        <p>Upper-right: high attention and strong ad evidence.</p>
        <p>Lower-left: weak for both engagement and monetization.</p>
      </div>
    </Card>
  );
}

function ScoringMethodologyTable({ catalogSize }: { catalogSize: number }) {
  const rows = [
    ["Attention Proxy", "0-24 Critical, 25-39 Weak, 40-54 Average, 55-69 Good, 70-84 Strong, 85-100 Excellent", "Visual novelty, motion, object clarity, visual quality, scene change, speech pacing, hook/CTA, audio, topic clarity", "Silence, repetition, blur"],
    ["Ad-Fit", "0-19 Avoid, 20-39 Weak, 40-59 Maybe, 60-79 Strong test, 80-100 Use", "Transcript/category keywords, visual objects, topic match, audience cue, attention, slot quality, safety", "Requires evidence; no evidence means no match"],
    ["Drop Risk", "0-24 Low risk, 25-49 Manageable, 50-74 Needs review, 75-100 High risk", "Inverse attention plus silence, repetition, blur, and missing context", "High score means avoid ad placement or edit"],
    ["Brand Safety", "0-49 Unsafe, 50-69 Needs review, 70-84 Mostly safe, 85-100 Safe", "Transcript risk terms and claim flags", "Claims and sensitive terms reduce score"],
    ["Ad Catalog", `${catalogSize}+ generated categories considered in backend`, "Vertical x intent candidates such as Productivity - Tutorial or Travel - Review", "The catalog is not shown as recommendations unless detected evidence matches"]
  ];
  return (
    <Card className="p-5">
      <ChartHeader title="Scoring Methodology" guide="Transparent method table showing what contributes to each score and how the system avoids generic ad recommendations." />
      <SimpleRows rows={rows} headers={["Score", "Score Labels", "Inputs", "Guardrail"]} />
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
      <p className="mt-2 text-sm text-slate-500">
        Attention {Math.round(segment.attention_score)}
        {showAdFit ? ` · Ad fit ${Math.round(segment.ad_fit_score)}` : null}
      </p>
    </div>
  );
}

function Moment({ title, moment, danger = false }: { title: string; moment: { start: number; end: number; score: number } | null; danger?: boolean }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-slate-400">
        <GuidedLabel
          label={title}
          guide={danger ? "Lowest attention moment; use it to decide where to rewrite, trim, or avoid ad placement." : "Strongest early moment; use it to understand hook pacing and opening strength."}
        />
        {danger ? <TrendingDown className="h-5 w-5 text-danger" /> : <TrendingUp className="h-5 w-5 text-success" />}
      </div>
      <p className="mt-4 text-2xl font-semibold">{moment ? formatRange(moment.start, moment.end) : "--"}</p>
      <p className="mt-2 text-sm text-slate-500">Score {moment?.score ?? 0}</p>
    </Card>
  );
}

function SegmentsTab({ segments }: { segments: Segment[] }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      <Card className="h-80 p-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={segments.map((segment) => ({ time: formatRange(segment.start, segment.end), attention: segment.attention_score, adFit: segment.ad_fit_score }))}>
            <CartesianGrid stroke="#202020" />
            <XAxis dataKey="time" stroke="#64748B" fontSize={12} />
            <YAxis stroke="#64748B" fontSize={12} />
            <RechartsTooltip content={<ChartTooltip />} />
            <Bar dataKey="attention" fill="#F8FAFC" radius={[4, 4, 0, 0]} />
            <Bar dataKey="adFit" fill="#F59E0B" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <div className="space-y-3">
        {segments.slice(0, 5).map((segment) => (
          <Card key={segment.id} className="p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold">{formatRange(segment.start, segment.end)}</p>
              <Badge tone={segment.attention_score >= 60 ? "success" : "warning"}>{segment.label}</Badge>
            </div>
            <p className="mt-2 text-sm text-slate-400">{segment.summary}</p>
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
  return (
    <div className="space-y-3">
      {segments.map((segment) => (
        <Card key={segment.id} className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="cyan">{formatRange(segment.start, segment.end)}</Badge>
            {segment.topics.map((topic) => (
              <Badge key={topic.label}>{topic.label}</Badge>
            ))}
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">{segment.transcript || "No speech detected."}</p>
        </Card>
      ))}
    </div>
  );
}

function EvidenceTab({ segments }: { segments: Segment[] }) {
  const rows = segments.map((segment) => [
    formatRange(segment.start, segment.end),
    String(Math.round(segment.drop_risk_score ?? 0)),
    String(Math.round(segment.brand_safety_score ?? 100)),
    String(Math.round(segment.transcript_insights?.clarity_score ?? 0)),
    `${Math.round((segment.visual_evidence?.visual_quality ?? 0) * 100)}`,
    segment.score_reasons?.join(" | ") || "No score reasons captured"
  ]);
  return <SimpleRows rows={rows} headers={["Time", "Drop Risk", "Brand Safety", "Transcript", "Visual", "Evidence Reasons"]} />;
}

function AdMatchesTab({ segments }: { segments: Segment[] }) {
  const rows = segments.flatMap((segment) =>
    segment.ad_matches.map((match) => [
      formatRange(segment.start, segment.end),
      [segment.objects.map((object) => object.label).join(" + "), segment.topics.map((topic) => topic.label).join(", ")].filter(Boolean).join(" / ") || "General context",
      match.ad_category,
      String(Math.round(segment.attention_score)),
      String(Math.round(match.ad_fit_score)),
      match.ad_fit_score >= 75 ? "Use" : match.ad_fit_score >= 45 ? "Test" : "Avoid"
    ])
  );
  return <SimpleRows rows={rows} headers={["Time", "Detected context", "Suggested Ad", "Attention", "Ad Fit", "Action"]} />;
}

function RecommendationsTab({ recommendations }: { recommendations: { title: string; timestamp: string; body: string }[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {recommendations.map((item) => (
        <Card key={`${item.title}-${item.timestamp}`} className="p-5">
          <Badge tone="cyan">{item.timestamp}</Badge>
          <h3 className="mt-4 text-lg font-semibold">{item.title}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">{item.body}</p>
        </Card>
      ))}
    </div>
  );
}

function SimpleRows({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[760px] border-collapse bg-card text-left text-sm">
        <thead className="bg-surface text-slate-400">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-4 py-3 font-medium">
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
                  <td key={`${index}-${cellIndex}`} className="px-4 py-3 text-slate-300">
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td className="px-4 py-8 text-center text-slate-500" colSpan={headers.length}>
                No matching rows.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
