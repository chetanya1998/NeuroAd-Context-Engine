"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Download,
  FileJson,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  UsersRound,
  WandSparkles
} from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/shell";
import { Badge, Card } from "@/components/ui";
import { capture } from "@/lib/analytics";
import { getInsightReport, insightExportUrl } from "@/lib/api";
import type { InsightReport } from "@/lib/types";

export default function InsightReportPage() {
  const params = useParams<{ reportId: string }>();
  const query = useQuery({ queryKey: ["insight-report", params.reportId], queryFn: () => getInsightReport(params.reportId) });
  const reportType = query.data?.report_type;
  useEffect(() => {
    if (!reportType) return;
    capture("insight_report_viewed", { report_id: params.reportId, target_type: reportType });
  }, [params.reportId, reportType]);

  if (query.isLoading) return <AppShell><main className="p-8 text-zinc-400">Building your GPT-OSS report dashboard…</main></AppShell>;
  if (!query.data) return <AppShell><main className="p-8 text-danger">{query.error instanceof Error ? query.error.message : "Report not found."}</main></AppShell>;
  return <InsightDashboard report={query.data} />;
}

function InsightDashboard({ report }: { report: InsightReport }) {
  const topCategory = report.ad_categories[0];
  const topBrand = report.brand_prospects[0];
  const placements = report.report_type === "video" ? report.placement_opportunities ?? [] : report.comparative_placements ?? [];
  const returnHref = report.report_type === "comparison" ? `/compare/${report.target_id}` : `/dashboard/${report.target_id}`;

  return (
    <AppShell>
      <main className="ph-no-capture mx-auto max-w-7xl px-5 py-7 sm:py-9 lg:px-10">
        <header className="relative overflow-hidden rounded-2xl border border-cyan/20 bg-gradient-to-br from-cyan/10 via-zinc-950 to-violet-500/10 p-5 sm:p-7">
          <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-cyan/15 blur-3xl" />
          <div className="relative">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="cyan">GPT-OSS insight</Badge>
                  <Badge tone="default">Evidence grounded</Badge>
                  {report.metadata?.model ? <span className="text-xs text-zinc-500">{report.metadata.model}</span> : null}
                </div>
                <h1 className="mt-4 max-w-4xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">Campaign intelligence, ready to act on.</h1>
              </div>
              <div className="flex flex-wrap gap-2 lg:shrink-0">
                <Link href={returnHref} className="inline-flex min-h-10 items-center gap-2 rounded-full border border-white/15 bg-black/20 px-3.5 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/10 hover:text-white">
                  <ArrowLeft className="h-4 w-4" /> Back to analysis
                </Link>
                <a href={insightExportUrl(report.report_id, "pdf")} onClick={() => capture("report_exported", { target_type: "insight", report_id: report.report_id, export_format: "pdf" })} className="inline-flex min-h-10 items-center gap-2 rounded-full border border-white/15 bg-black/20 px-3.5 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/10 hover:text-white">
                  <Download className="h-4 w-4" /> PDF
                </a>
                <a href={insightExportUrl(report.report_id, "json")} onClick={() => capture("report_exported", { target_type: "insight", report_id: report.report_id, export_format: "json" })} className="inline-flex min-h-10 items-center gap-2 rounded-full border border-white/15 bg-black/20 px-3.5 py-2 text-sm font-semibold text-zinc-200 transition hover:bg-white/10 hover:text-white">
                  <FileJson className="h-4 w-4" /> JSON
                </a>
              </div>
            </div>
            <p className="mt-5 max-w-4xl text-sm leading-7 text-zinc-300 sm:text-base">{report.executive_summary || "GPT-OSS did not return an executive summary for this report."}</p>
            <div className="mt-5 flex flex-wrap gap-2">{report.content_profile.themes.map(theme => <span key={theme} className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1.5 text-sm text-zinc-200">{theme}</span>)}</div>
          </div>
        </header>

        <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SignalCard icon={<Target className="h-5 w-5" />} label="Best category" value={topCategory?.category ?? "No category yet"} detail={topCategory ? `${topCategory.contextual_fit_score}/100 contextual fit` : "More evidence is needed"} tone="cyan" />
          <SignalCard icon={<TrendingUp className="h-5 w-5" />} label="Top prospect" value={topBrand?.brand ?? "No prospect yet"} detail={topBrand ? `${topBrand.contextual_fit_score}/100 contextual fit` : "No verified evidence"} tone="violet" />
          <SignalCard icon={<Clock3 className="h-5 w-5" />} label="Placement windows" value={`${placements.length}`} detail={placements.length ? "Evidence-linked moments" : "No placement returned"} tone="green" />
          <SignalCard icon={<ShieldCheck className="h-5 w-5" />} label="Brand safety" value={safetyLabel(report)} detail={report.brand_safety.summary || "Review findings below"} tone="amber" />
        </section>

        <section className="mt-5 grid items-start gap-5 xl:grid-cols-[1.15fr_0.85fr]">
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<TrendingUp className="h-5 w-5 text-cyan" />} title="Where advertisers fit" subtitle="Ranked by GPT-OSS from grounded content evidence." />
            <div className="mt-5 space-y-5">{report.ad_categories.length ? report.ad_categories.map(category => <div key={category.category}><div className="flex items-start justify-between gap-4"><div className="min-w-0"><p className="font-semibold text-white">{category.category}</p><p className="mt-1 text-sm leading-6 text-zinc-400">{category.rationale}</p></div><Score score={category.contextual_fit_score} /></div><ScoreBar score={category.contextual_fit_score} /><EvidenceRefs refs={category.evidence_refs} /></div>) : <Empty body="No evidence-backed advertising categories were returned." />}</div>
          </Card>
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<UsersRound className="h-5 w-5 text-violet-300" />} title="Audience & persona map" subtitle="Who this video is likely to reach, what matters to them, and what to add next." />
            <PersonaMap report={report} />
          </Card>
        </section>

        <section className="mt-5 grid items-start gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<Sparkles className="h-5 w-5 text-warning" />} title="Keyword explorer" subtitle="Terms GPT-OSS tied to specific evidence." />
            <div className="mt-5 flex flex-wrap gap-2">{report.keywords.length ? report.keywords.map(keyword => <span key={keyword.term} className="rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm"><span className="font-medium text-white">{keyword.term}</span><span className="ml-2 text-xs text-zinc-500">{keyword.type} · {keyword.confidence}</span></span>) : <Empty body="No evidence-backed keywords were returned." />}</div>
            <div className="mt-6 border-t border-white/10 pt-5"><ProfileGroup title="Tone" values={report.content_profile.tone} /><ProfileGroup title="Campaign intent" values={report.content_profile.campaign_intents} /></div>
          </Card>
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<Target className="h-5 w-5 text-cyan" />} title="Brand opportunity board" subtitle="Exploratory prospects—not sponsored recommendations." />
            <div className="mt-5 grid gap-3 md:grid-cols-2">{report.brand_prospects.length ? report.brand_prospects.map(brand => <div key={brand.brand} className="rounded-xl border border-white/10 bg-zinc-950 p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-semibold text-white">{brand.brand}</p><p className="mt-1 text-xs text-zinc-500">{brand.category || "Category to verify"}</p></div><Score score={brand.contextual_fit_score} /></div><p className="mt-3 text-sm leading-6 text-zinc-300">{brand.why_fit}</p><div className="mt-3 rounded-md border border-cyan/20 bg-cyan/5 p-3 text-sm leading-6 text-cyan"><span className="font-medium">Activation idea: </span>{brand.activation_idea}</div><EvidenceRefs refs={brand.evidence_refs} /></div>) : <Empty body="No brand prospects were returned." />}</div>
            <p className="mt-4 text-xs leading-5 text-zinc-500">{report.brand_prospect_disclaimer}</p>
          </Card>
        </section>

        <section className="mt-5 grid items-start gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<WandSparkles className="h-5 w-5 text-cyan" />} title="Attention uplift blueprint" subtitle="Specific additions GPT-OSS recommends to make the next edit more engaging." />
            <AttentionPlan improvements={report.attention_improvements ?? []} />
          </Card>
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<Clock3 className="h-5 w-5 text-success" />} title="Evidence-led moments" subtitle="Review these windows before approving a placement." />
            <div className="mt-5 space-y-3">{placements.length ? placements.map((placement, index) => <div key={`${placement.segment_id}-${index}`} className="flex gap-3 rounded-xl border border-white/10 bg-zinc-950 p-4"><div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-success/10 text-sm font-semibold text-success">{index + 1}</div><div className="min-w-0"><p className="font-medium text-white">{placement.start.toFixed(1)}s – {placement.end.toFixed(1)}s <span className="ml-2 text-sm text-zinc-500">Verified placement score {placementScore(report, placement)}/100</span></p><p className="mt-1 text-sm leading-6 text-zinc-400">{"messaging_angle" in placement ? placement.messaging_angle || placement.rationale : placement.rationale}</p></div></div>) : <Empty body="GPT-OSS did not return a confident placement moment." />}</div>
          </Card>
        </section>

        <section className="mt-5 grid items-start gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<CheckCircle2 className="h-5 w-5 text-success" />} title="Creative action plan" subtitle="Practical changes for the next edit or reshoot." /><ActionList items={report.creative_recommendations} /></Card>
          <Card className="h-fit p-5 sm:p-6"><SectionTitle icon={<CircleAlert className="h-5 w-5 text-warning" />} title="Safety & limitations" subtitle={report.brand_safety.summary || "Review before activating a campaign."} /><ActionList items={[...report.brand_safety.findings, ...report.limitations]} muted /></Card>
        </section>
      </main>
    </AppShell>
  );
}

function SignalCard({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: "cyan" | "violet" | "green" | "amber" }) {
  const color = { cyan: "text-cyan bg-cyan/10", violet: "text-violet-300 bg-violet-500/10", green: "text-success bg-success/10", amber: "text-warning bg-warning/10" }[tone];
  return <Card className="p-5"><span className={`grid h-10 w-10 place-items-center rounded-xl ${color}`}>{icon}</span><p className="mt-4 text-sm text-zinc-500">{label}</p><p className="mt-1 truncate text-xl font-semibold text-white" title={value}>{value}</p><p className="mt-1.5 line-clamp-2 text-sm leading-5 text-zinc-400">{detail}</p></Card>;
}

function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return <div><div className="flex items-center gap-2"><span>{icon}</span><h2 className="text-xl font-semibold text-white">{title}</h2></div><p className="mt-1.5 text-sm leading-6 text-zinc-500">{subtitle}</p></div>;
}

function Score({ score }: { score: number }) { return <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-xs font-semibold text-white">{score}/100</span>; }
function ScoreBar({ score }: { score: number }) { return <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-cyan to-violet-400" style={{ width: `${Math.max(3, Math.min(100, score))}%` }} /></div>; }
function EvidenceRefs({ refs }: { refs?: string[] }) { return refs?.length ? <p className="mt-3 text-xs text-zinc-500">Evidence: {refs.map(ref => ref.replace(/^seg_/, "segment ")).join(", ")}</p> : null; }

function PersonaMap({ report }: { report: InsightReport }) {
  const personas = report.audience_personas ?? [];
  if (personas.length) return <div className="mt-5 grid gap-3">{personas.map(persona => <div key={persona.persona} className="rounded-xl border border-white/10 bg-zinc-950 p-4"><p className="font-semibold text-white">{persona.persona}</p><p className="mt-1 text-sm leading-6 text-zinc-400">{persona.motivation}</p><FocusList label="Attention triggers" items={persona.attention_triggers} tone="text-cyan" /><FocusList label="What to add" items={persona.recommended_additions} tone="text-success" /><FocusList label="Potential gaps" items={persona.content_gaps} tone="text-warning" /><EvidenceRefs refs={persona.evidence_refs} /></div>)}</div>;
  return <div className="mt-5"><ProfileGroup title="Audience signals" values={report.content_profile.audience_signals} /><ProfileGroup title="Tone" values={report.content_profile.tone} /><Empty body="Generate a fresh GPT-OSS report to include persona motivations, attention triggers, and recommended additions." /></div>;
}

function FocusList({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return <div className="mt-3"><p className={`text-xs font-semibold uppercase tracking-wide ${tone}`}>{label}</p><ul className="mt-1.5 space-y-1 text-sm leading-5 text-zinc-300">{items.map(item => <li key={item}>• {item}</li>)}</ul></div>;
}

function ProfileGroup({ title, values }: { title: string; values: string[] }) {
  return <div className="mt-4"><p className="text-sm font-medium text-zinc-300">{title}</p><div className="mt-2 flex flex-wrap gap-2">{values.length ? values.map(value => <Badge key={value} tone="cyan">{value}</Badge>) : <span className="text-sm text-zinc-500">No strong signal returned.</span>}</div></div>;
}

function placementScore(report: InsightReport, placement: { segment_id: string; score: number }) {
  return report.evidence_index?.[placement.segment_id]?.scores?.ad_slot_score ?? placement.score;
}

function AttentionPlan({ improvements }: { improvements: NonNullable<InsightReport["attention_improvements"]> }) {
  if (!improvements.length) return <div className="mt-5"><Empty body="Generate a fresh GPT-OSS report to receive timestamped attention-improvement recommendations." /></div>;
  return <div className="mt-5 space-y-3">{improvements.map((item, index) => <div key={`${item.segment_id}-${index}`} className="rounded-xl border border-white/10 bg-zinc-950 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-white">{item.start.toFixed(1)}s – {item.end.toFixed(1)}s</p><span className="rounded-full bg-cyan/10 px-2.5 py-1 text-xs font-semibold text-cyan">Priority #{item.priority_rank ?? (item.priority <= 6 ? item.priority : index + 1)}</span></div><p className="mt-3 text-sm font-medium text-warning">Why attention may fall: <span className="font-normal text-zinc-300">{item.issue}</span></p><p className="mt-2 text-sm leading-6 text-zinc-100"><span className="font-medium text-success">Add or change: </span>{item.recommended_change}</p>{item.execution_tip ? <p className="mt-2 text-sm leading-6 text-zinc-400"><span className="font-medium text-zinc-200">Execution: </span>{item.execution_tip}</p> : null}{item.expected_attention_impact ? <p className="mt-2 text-sm leading-6 text-cyan"><span className="font-medium">Expected effect: </span>{item.expected_attention_impact}</p> : null}<EvidenceRefs refs={item.evidence_refs} /></div>)}</div>;
}

function ActionList({ items, muted = false }: { items: string[]; muted?: boolean }) {
  const actions = splitActions(items);
  return <div className="mt-5 space-y-3">{actions.length ? actions.map((item, index) => <div key={`${item}-${index}`} className="flex gap-3 rounded-lg border border-white/10 bg-zinc-950 p-3"><span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${muted ? "bg-warning/10 text-warning" : "bg-success/10 text-success"}`}>{index + 1}</span><p className="text-sm leading-6 text-zinc-300">{item}</p></div>) : <Empty body="No additional action returned." />}</div>;
}

function splitActions(items: string[]) {
  return items.flatMap(item => {
    const numbered = item.match(/(?:^|\s)\d+[.)]\s+.*?(?=(?:\s+\d+[.)]\s)|$)/g);
    return numbered?.length ? numbered.map(action => action.replace(/^\s*\d+[.)]\s*/, "").trim()) : [item];
  }).filter(Boolean);
}

function Empty({ body }: { body: string }) { return <p className="rounded-lg border border-dashed border-white/10 p-4 text-sm leading-6 text-zinc-500">{body}</p>; }
function safetyLabel(report: InsightReport) { return report.brand_safety.findings.length ? "Review findings" : "No major flags"; }
