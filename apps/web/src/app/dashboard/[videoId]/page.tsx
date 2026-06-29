"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FileJson, Search, TrendingDown, TrendingUp, Zap } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AttentionTimeline } from "@/components/attention-timeline";
import { SegmentDrawer } from "@/components/segment-drawer";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { exportUrl, formatRange, getAnalysis } from "@/lib/api";
import type { Segment } from "@/lib/types";

const tabs = ["Segments", "Objects", "Transcript", "Ad Matches", "Recommendations"] as const;

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

  const isMetadataOnlyYouTube = analysis.video.source_type === "youtube_ingest" && !analysis.video.file_url;

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

        {isMetadataOnlyYouTube ? (
          <Card className="mt-6 border-amber-400/20 bg-amber-400/10 p-4">
            <p className="text-sm font-semibold text-amber-100">Limited YouTube analysis</p>
            <p className="mt-2 text-sm leading-6 text-amber-50/75">
              YouTube blocked direct media access for this link, so this report uses available metadata, thumbnail context, and topic matching. Upload the video file to unlock frame,
              audio, transcript, and object-level scoring.
            </p>
          </Card>
        ) : null}

        <section className="mt-8 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <OverallVideoTrend segments={analysis.segments} />

          <div className="grid gap-4 sm:grid-cols-2">
            <Metric title="Overall Attention" value={analysis.summary.overall_attention_score} icon={<Zap className="h-5 w-5" />} />
            <Metric title="Monetization" value={analysis.summary.monetization_opportunity_score} icon={<TrendingUp className="h-5 w-5" />} />
            <Moment title="Best Hook" moment={analysis.summary.best_hook} />
            <Moment title="Weak Segment" moment={analysis.summary.weakest_segment} danger />
            <Card className="p-5 sm:col-span-2">
              <p className="text-sm text-slate-400">Top Ad Category</p>
              <p className="mt-2 text-2xl font-semibold">{analysis.summary.top_ad_category}</p>
              <p className="mt-3 text-sm text-slate-500">Research Mode is disabled in this build; reports come only from analyzed media files.</p>
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

        <section className="mt-6">
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
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-slate-400">
        <p className="text-sm">{title}</p>
        {icon}
      </div>
      <p className="mt-4 text-4xl font-semibold">{Math.round(value)}</p>
    </Card>
  );
}

function OverallVideoTrend({ segments }: { segments: Segment[] }) {
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
    return { segment, x, attentionY, adFitY };
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
  const tickCount = Math.min(6, Math.max(2, safeSegments.length));
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const dataIndex = Math.round((index / (tickCount - 1)) * Math.max(0, safeSegments.length - 1));
    return data[dataIndex];
  }).filter(Boolean);

  return (
    <Card className="overflow-hidden border-white/10 bg-black">
      <div className="border-b border-white/10 p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.22em] text-slate-500">Overall video trend</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">Attention highs, lows, and ad-fit movement</h2>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-white/10 px-3 py-1 text-slate-300">Attention Proxy</span>
            <span className="rounded-full border border-warning/30 px-3 py-1 text-warning">Ad Fit</span>
            <span className="rounded-full border border-success/30 px-3 py-1 text-success">High</span>
            <span className="rounded-full border border-danger/30 px-3 py-1 text-danger">Low</span>
          </div>
        </div>
      </div>

      <div className="p-5">
        <div className="rounded-lg border border-white/10 bg-zinc-950 p-4">
          <svg viewBox={`0 0 ${width} ${height}`} className="h-[360px] w-full" role="img" aria-label="Overall attention trend graph">
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
            <polyline points={attentionPath} fill="none" stroke="#f8fafc" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" />

            {data.map((item, index) => (
              <circle key={item.segment.id} cx={item.x} cy={item.attentionY} r={index === 0 || index === data.length - 1 ? 4 : 3} fill="#f8fafc" opacity="0.92" />
            ))}

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
      <Badge tone={tone}>{title}</Badge>
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
        <p className="text-sm">{title}</p>
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
            <Tooltip contentStyle={{ background: "#050505", border: "1px solid #202020" }} />
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
