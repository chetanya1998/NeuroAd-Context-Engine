"use client";

import { Activity, ArrowRight, CheckCircle2, Clock3, Sparkles, Wrench } from "lucide-react";
import type { AnalysisPayload, DecisionMetric, PriorityRecommendation, SignalFamily, TimelinePoint } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";

type Props = {
  analysis: AnalysisPayload;
  onSeek: (time: number) => void;
};

const familyConfig = [
  { key: "visual", label: "Visual movement", metric: "visual_change_intensity", fallback: "motion_level" },
  { key: "audio", label: "Audio energy", metric: "audio_energy", fallback: "voice_clarity" },
  { key: "narrative", label: "Narrative novelty", metric: "semantic_novelty", fallback: "topic_clarity" },
  { key: "social", label: "Social variety", metric: "social_interaction_density", fallback: "face_persistence" }
] as const;

function reliabilityTone(value?: string) {
  if (value === "High") return "success" as const;
  if (value === "Medium") return "warning" as const;
  return "danger" as const;
}

function labelTone(metric: DecisionMetric) {
  if (["Strong", "Clear", "Low", "Ready", "High"].includes(metric.label)) return "success" as const;
  if (["Uneven", "Mixed", "Medium", "Review"].includes(metric.label)) return "warning" as const;
  return "danger" as const;
}

function numericSignal(point: TimelinePoint, family: (typeof familyConfig)[number]) {
  const values = point[family.key] as SignalFamily | undefined;
  const primary = values?.[family.metric];
  const fallback = values?.[family.fallback];
  const value = typeof primary === "number" ? primary : typeof fallback === "number" ? fallback : null;
  return value === null ? null : Math.max(0, Math.min(1, value > 1 ? value / 100 : value));
}

function strongestCard(card: PriorityRecommendation, onSeek: (time: number) => void) {
  return (
    <Card className="border-success/25 bg-success/[0.04] p-6 lg:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-success">
            <Sparkles className="h-5 w-5" />
            <p className="text-sm font-semibold uppercase tracking-[0.14em]">What is strongest?</p>
          </div>
          <h2 className="mt-3 text-3xl font-semibold text-white">{card.status}</h2>
        </div>
        <button type="button" onClick={() => onSeek(card.timestamp.start)} className="rounded-md border border-success/30 bg-black/20 px-3 py-2 font-mono text-sm text-success hover:bg-success/10">
          {card.timestamp.label}
        </button>
      </div>
      <div className="mt-5 grid gap-5 md:grid-cols-[1fr_1.15fr]">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.12em] text-slate-500">Why</p>
          <ul className="mt-3 space-y-2 text-base leading-6 text-slate-300">
            {card.why.map((reason) => <li key={reason} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />{reason}</li>)}
          </ul>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/25 p-4">
          <p className="text-sm font-semibold uppercase tracking-[0.12em] text-slate-500">What to do next</p>
          <p className="mt-2 text-base leading-7 text-white">{card.suggested_action}</p>
          <Badge className="mt-4" tone={reliabilityTone(card.evidence_reliability)}>Evidence reliability: {card.evidence_reliability}</Badge>
        </div>
      </div>
    </Card>
  );
}

function FixCard({ card, onSeek }: { card: PriorityRecommendation; onSeek: (time: number) => void }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-warning">{card.status}</p>
          <button type="button" onClick={() => onSeek(card.timestamp.start)} className="mt-2 font-mono text-sm text-white underline decoration-white/20 underline-offset-4 hover:decoration-white">
            {card.timestamp.label}
          </button>
        </div>
        <Badge tone={reliabilityTone(card.evidence_reliability)}>{card.evidence_reliability} evidence</Badge>
      </div>
      <ul className="mt-4 space-y-1.5 text-sm leading-6 text-slate-400">
        {card.why.slice(0, 3).map((reason) => <li key={reason}>• {reason}</li>)}
      </ul>
      <p className="mt-4 border-t border-white/10 pt-4 text-sm leading-6 text-slate-200"><span className="font-semibold">Next:</span> {card.suggested_action}</p>
    </Card>
  );
}

function DecisionCard({ metric, onSeek }: { metric: DecisionMetric; onSeek: (time: number) => void }) {
  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-slate-500">{metric.name}</p>
          <p className="mt-2 text-2xl font-semibold text-white">{metric.label}</p>
        </div>
        <Badge tone={labelTone(metric)}>{metric.confidence} confidence</Badge>
      </div>
      <button type="button" onClick={() => onSeek(metric.timestamp.start)} className="mt-4 flex items-center gap-2 text-left font-mono text-sm text-slate-300 hover:text-white">
        <Clock3 className="h-4 w-4" /> {metric.timestamp.label}
      </button>
      <p className="mt-4 text-sm leading-6 text-slate-400">{metric.reasons[0]}</p>
      <div className="mt-auto pt-4">
        <p className="rounded-lg border border-white/10 bg-black/20 p-3 text-sm leading-6 text-slate-200"><span className="font-semibold">Next:</span> {metric.next_action}</p>
      </div>
    </Card>
  );
}

function SignalTimeline({ points, onSeek }: { points: TimelinePoint[]; onSeek: (time: number) => void }) {
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-slate-300"><Activity className="h-5 w-5" /><p className="font-semibold">Where do signals change?</p></div>
          <p className="mt-2 text-sm leading-6 text-slate-500">Four grouped lanes replace dozens of disconnected charts. Select a marker to jump to that timestamp.</p>
        </div>
        <p className="text-xs text-slate-500">Darker = weaker · brighter = stronger · striped = unavailable</p>
      </div>
      <div className="mt-6 space-y-5">
        {familyConfig.map((family) => (
          <div key={family.key} className="grid gap-2 lg:grid-cols-[150px_1fr] lg:items-center">
            <p className="text-sm font-medium text-slate-300">{family.label}</p>
            <div className="flex min-h-11 gap-1 overflow-hidden rounded-lg bg-black/30 p-1">
              {points.map((point) => {
                const value = numericSignal(point, family);
                const findings = ((point[family.key] as SignalFamily | undefined)?.findings ?? []).join(" ");
                return (
                  <button
                    key={`${family.key}-${point.segment_id ?? point.start}`}
                    type="button"
                    onClick={() => onSeek(point.start)}
                    title={`${point.label}${findings ? ` — ${findings}` : ""}`}
                    className="min-w-2 flex-1 rounded-sm border border-white/10 transition hover:-translate-y-0.5 hover:border-white/40 focus:outline-none focus:ring-2 focus:ring-white/50"
                    style={value === null
                      ? { backgroundImage: "repeating-linear-gradient(135deg, rgba(148,163,184,.08), rgba(148,163,184,.08) 4px, rgba(148,163,184,.18) 4px, rgba(148,163,184,.18) 8px)" }
                      : { backgroundColor: `rgba(34, 211, 238, ${0.12 + value * 0.78})` }}
                    aria-label={`${family.label} at ${point.label}`}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function ContentSignalOverview({ analysis, onSeek }: Props) {
  const priorities = analysis.priority_recommendations ?? [];
  const strongest = priorities[0];
  const fixes = priorities.slice(1, 5);
  const metrics = analysis.decision_metrics ?? [];
  const points = analysis.timeline_summary?.points ?? [];

  if (!strongest && !metrics.length) return null;

  return (
    <section className="mt-8 space-y-8" aria-label="Actionable content signals">
      {strongest ? strongestCard(strongest, onSeek) : null}

      <div>
        <div className="flex items-center gap-2"><Wrench className="h-5 w-5 text-warning" /><h2 className="text-2xl font-semibold text-white">What needs fixing first?</h2></div>
        <p className="mt-2 text-base text-slate-500">Highest-impact fixes, ordered by drop risk and evidence—not by an arbitrary score.</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {fixes.length ? fixes.map((card) => <FixCard key={`${card.segment_id}-${card.timestamp.start}`} card={card} onSeek={onSeek} />) : (
            <Card className="p-5 text-slate-400">No urgent fix is supported by the current evidence.</Card>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-2xl font-semibold text-white">Decision signals</h2>
        <p className="mt-2 text-base text-slate-500">Plain-language labels with independent confidence, timestamp, evidence, and a next action.</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {metrics.map((metric) => <DecisionCard key={metric.key} metric={metric} onSeek={onSeek} />)}
        </div>
      </div>

      {points.length ? <SignalTimeline points={points} onSeek={onSeek} /> : null}

      <details className="rounded-lg border border-border bg-card p-5">
        <summary className="cursor-pointer list-none font-semibold text-slate-200">Evidence details <span className="ml-2 text-sm font-normal text-slate-500">Extractor availability, version, and review state</span></summary>
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Object.entries(analysis.signal_availability ?? {}).map(([family, availability]) => (
            <div key={family} className="rounded-lg border border-white/10 bg-black/20 p-4">
              <div className="flex items-center justify-between gap-2"><p className="capitalize text-slate-200">{family}</p><Badge tone={availability.status === "available" ? "success" : availability.status === "degraded" || availability.status === "partial" ? "warning" : "danger"}>{availability.status}</Badge></div>
              <p className="mt-2 text-xs leading-5 text-slate-500">{availability.extractors?.join(" · ") || `Missing: ${availability.missing?.join(", ") || "extractor"}`}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-500">
          <span>Analysis version: {analysis.analysis_version ?? "legacy"}</span>
          <span>·</span>
          <span>Human review: {analysis.review_summary?.state ?? "unreviewed"}</span>
          <Button variant="ghost" className="ml-auto" onClick={() => document.getElementById("segment-evidence")?.scrollIntoView({ behavior: "smooth" })}>Open segment evidence <ArrowRight className="h-4 w-4" /></Button>
        </div>
      </details>
    </section>
  );
}
