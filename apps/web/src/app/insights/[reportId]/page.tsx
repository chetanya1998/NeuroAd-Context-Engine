"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Clock3, Layers3, ShieldCheck, Sparkles, Target, TrendingUp } from "lucide-react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell";
import { Badge, Card } from "@/components/ui";
import { getInsightReport } from "@/lib/api";
import type { InsightReport } from "@/lib/types";

export default function InsightReportPage() {
  const params = useParams<{ reportId: string }>();
  const query = useQuery({ queryKey: ["insight-report", params.reportId], queryFn: () => getInsightReport(params.reportId) });
  if (query.isLoading) return <AppShell><main className="p-8 text-zinc-400">Building your GPT-OSS report dashboard…</main></AppShell>;
  if (!query.data) return <AppShell><main className="p-8 text-danger">{query.error instanceof Error ? query.error.message : "Report not found."}</main></AppShell>;
  return <InsightDashboard report={query.data} />;
}

function InsightDashboard({ report }: { report: InsightReport }) {
  const topCategory = report.ad_categories[0];
  const topBrand = report.brand_prospects[0];
  const placements = report.report_type === "video" ? report.placement_opportunities ?? [] : report.comparative_placements ?? [];
  return <AppShell><main className="mx-auto max-w-7xl px-5 py-10 lg:px-10">
    <header className="relative overflow-hidden rounded-2xl border border-cyan/20 bg-gradient-to-br from-cyan/10 via-zinc-950 to-violet-500/10 p-7 md:p-10">
      <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-cyan/15 blur-3xl" />
      <div className="relative"><div className="flex flex-wrap items-center gap-2"><Badge tone="cyan">GPT-OSS insight</Badge><Badge tone="default">Evidence grounded</Badge>{report.metadata?.model ? <span className="text-xs text-zinc-500">{report.metadata.model}</span> : null}</div><h1 className="mt-5 max-w-4xl text-3xl font-semibold tracking-tight text-white md:text-5xl">Campaign intelligence, ready to act on.</h1><p className="mt-5 max-w-4xl text-base leading-8 text-zinc-300">{report.executive_summary || "GPT-OSS did not return an executive summary for this report."}</p><div className="mt-6 flex flex-wrap gap-2">{report.content_profile.themes.map(theme => <span key={theme} className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1.5 text-sm text-zinc-200">{theme}</span>)}</div></div>
    </header>

    <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <SignalCard icon={<Target className="h-5 w-5" />} label="Best category" value={topCategory?.category ?? "No category yet"} detail={topCategory ? `${topCategory.contextual_fit_score}/100 contextual fit` : "More evidence is needed"} tone="cyan" />
      <SignalCard icon={<TrendingUp className="h-5 w-5" />} label="Top prospect" value={topBrand?.brand ?? "No prospect yet"} detail={topBrand ? `${topBrand.contextual_fit_score}/100 contextual fit` : "No verified evidence"} tone="violet" />
      <SignalCard icon={<Clock3 className="h-5 w-5" />} label="Placement windows" value={`${placements.length}`} detail={placements.length ? "Evidence-linked moments" : "No placement returned"} tone="green" />
      <SignalCard icon={<ShieldCheck className="h-5 w-5" />} label="Brand safety" value={safetyLabel(report)} detail={report.brand_safety.summary || "Review findings below"} tone="amber" />
    </section>

    <section className="mt-6 grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
      <Card className="p-6"><SectionTitle icon={<TrendingUp className="h-5 w-5 text-cyan" />} title="Where advertisers fit" subtitle="Ranked by GPT-OSS from your grounded content evidence." />
        <div className="mt-6 space-y-5">{report.ad_categories.length ? report.ad_categories.map(category => <div key={category.category}><div className="flex items-start justify-between gap-4"><div><p className="font-semibold text-white">{category.category}</p><p className="mt-1 text-sm leading-6 text-zinc-400">{category.rationale}</p></div><Score score={category.contextual_fit_score} /></div><ScoreBar score={category.contextual_fit_score} /><EvidenceRefs refs={category.evidence_refs} /></div>) : <Empty body="No evidence-backed advertising categories were returned." />}</div>
      </Card>
      <Card className="p-6"><SectionTitle icon={<Layers3 className="h-5 w-5 text-violet-300" />} title="Audience & content profile" subtitle="The signals shaping the creative opportunity." />
        <ProfileGroup title="Audience signals" values={report.content_profile.audience_signals} /><ProfileGroup title="Tone" values={report.content_profile.tone} /><ProfileGroup title="Campaign intent" values={report.content_profile.campaign_intents} />
      </Card>
    </section>

    <section className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <Card className="p-6"><SectionTitle icon={<Sparkles className="h-5 w-5 text-warning" />} title="Keyword explorer" subtitle="Terms GPT-OSS linked to video evidence." />
        <div className="mt-6 flex flex-wrap gap-2">{report.keywords.length ? report.keywords.map(keyword => <span key={keyword.term} className="rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm"><span className="font-medium text-white">{keyword.term}</span><span className="ml-2 text-xs text-zinc-500">{keyword.type} · {keyword.confidence}</span></span>) : <Empty body="No evidence-backed keywords were returned." />}</div>
      </Card>
      <Card className="p-6"><SectionTitle icon={<Target className="h-5 w-5 text-cyan" />} title="Brand opportunity board" subtitle="Exploratory prospects—not sponsored recommendations." />
        <div className="mt-6 grid gap-3 md:grid-cols-2">{report.brand_prospects.length ? report.brand_prospects.map(brand => <div key={brand.brand} className="rounded-xl border border-white/10 bg-zinc-950 p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-white">{brand.brand}</p><p className="mt-1 text-xs text-zinc-500">{brand.category || "Category to verify"}</p></div><Score score={brand.contextual_fit_score} /></div><p className="mt-4 text-sm leading-6 text-zinc-300">{brand.why_fit}</p><div className="mt-4 rounded-md border border-cyan/20 bg-cyan/5 p-3 text-sm text-cyan"><span className="font-medium">Activation idea: </span>{brand.activation_idea}</div><EvidenceRefs refs={brand.evidence_refs} /></div>) : <Empty body="No brand prospects were returned." />}</div>
        <p className="mt-5 text-xs leading-5 text-zinc-500">{report.brand_prospect_disclaimer}</p>
      </Card>
    </section>

    <section className="mt-6 grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <Card className="p-6"><SectionTitle icon={<Clock3 className="h-5 w-5 text-success" />} title="Evidence-led moments" subtitle="Use these as review points before final placement approval." />
        <div className="mt-6 space-y-3">{placements.length ? placements.map((placement, index) => <div key={`${placement.segment_id}-${index}`} className="flex gap-4 rounded-xl border border-white/10 bg-zinc-950 p-4"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-success/10 text-sm font-semibold text-success">{index + 1}</div><div className="min-w-0"><p className="font-medium text-white">{placement.start.toFixed(1)}s – {placement.end.toFixed(1)}s <span className="ml-2 text-sm text-zinc-500">{placement.score}/100</span></p><p className="mt-1 text-sm leading-6 text-zinc-400">{"messaging_angle" in placement ? placement.messaging_angle || placement.rationale : placement.rationale}</p></div></div>) : <Empty body="GPT-OSS did not return a confident placement moment." />}</div>
      </Card>
      <Card className="p-6"><SectionTitle icon={<CheckCircle2 className="h-5 w-5 text-success" />} title="Creative action plan" subtitle="The next most useful changes for the campaign." /><ActionList items={report.creative_recommendations} /><div className="mt-6 border-t border-white/10 pt-6"><SectionTitle icon={<CircleAlert className="h-5 w-5 text-warning" />} title="Safety & limitations" subtitle={report.brand_safety.summary || "Review before activating a campaign."} /><ActionList items={[...report.brand_safety.findings, ...report.limitations]} muted /></div></Card>
    </section>
  </main></AppShell>;
}

function SignalCard({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: "cyan" | "violet" | "green" | "amber" }) { const color = { cyan: "text-cyan bg-cyan/10", violet: "text-violet-300 bg-violet-500/10", green: "text-success bg-success/10", amber: "text-warning bg-warning/10" }[tone]; return <Card className="p-5"><span className={`grid h-10 w-10 place-items-center rounded-xl ${color}`}>{icon}</span><p className="mt-5 text-sm text-zinc-500">{label}</p><p className="mt-1 truncate text-xl font-semibold text-white" title={value}>{value}</p><p className="mt-2 line-clamp-2 text-sm leading-5 text-zinc-400">{detail}</p></Card>; }
function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) { return <div><div className="flex items-center gap-2"><span>{icon}</span><h2 className="text-xl font-semibold text-white">{title}</h2></div><p className="mt-2 text-sm leading-6 text-zinc-500">{subtitle}</p></div>; }
function Score({ score }: { score: number }) { return <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-xs font-semibold text-white">{score}/100</span>; }
function ScoreBar({ score }: { score: number }) { return <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-gradient-to-r from-cyan to-violet-400" style={{ width: `${Math.max(3, Math.min(100, score))}%` }} /></div>; }
function EvidenceRefs({ refs }: { refs?: string[] }) { return refs?.length ? <p className="mt-3 text-xs text-zinc-500">Evidence: {refs.map(ref => ref.replace(/^seg_/, "segment ")).join(", ")}</p> : null; }
function ProfileGroup({ title, values }: { title: string; values: string[] }) { return <div className="mt-6"><p className="text-sm font-medium text-zinc-300">{title}</p><div className="mt-3 flex flex-wrap gap-2">{values.length ? values.map(value => <Badge key={value} tone="cyan">{value}</Badge>) : <span className="text-sm text-zinc-500">No strong signal returned.</span>}</div></div>; }
function ActionList({ items, muted = false }: { items: string[]; muted?: boolean }) { return <div className="mt-5 space-y-3">{items.length ? items.map((item, index) => <div key={item} className="flex gap-3 rounded-lg border border-white/10 bg-zinc-950 p-3"><span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${muted ? "bg-warning/10 text-warning" : "bg-success/10 text-success"}`}>{index + 1}</span><p className="text-sm leading-6 text-zinc-300">{item}</p></div>) : <Empty body="No additional action returned." />}</div>; }
function Empty({ body }: { body: string }) { return <p className="rounded-lg border border-dashed border-white/10 p-4 text-sm leading-6 text-zinc-500">{body}</p>; }
function safetyLabel(report: InsightReport) { return report.brand_safety.findings.length ? "Review findings" : "No major flags"; }
