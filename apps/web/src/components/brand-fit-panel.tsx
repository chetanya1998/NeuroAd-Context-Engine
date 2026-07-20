"use client";
/* eslint-disable @next/next/no-img-element -- remote product pages and API thumbnails are not configured Next image domains */

import {
  ChevronRight,
  Clock3,
  ExternalLink,
  ImageIcon,
  Link2,
  LoaderCircle,
  Plus,
  RotateCcw,
  Sparkles,
  X
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  absoluteMediaUrl,
  createProduct,
  formatRange,
  getRecentProducts,
  resolveProduct,
  runVideoProductFit
} from "@/lib/api";
import type { ProductFitPayload, ProductPlacement, ProductProfile } from "@/lib/types";
import { Badge, Button, Card } from "./ui";

type ListField = "keywords" | "features" | "use_cases" | "audience" | "prohibited_contexts";

const emptyProfile = (url: string): ProductProfile => ({
  source_url: url,
  canonical_url: url,
  name: "",
  brand_name: "",
  description: "",
  category: "",
  keywords: [],
  features: [],
  use_cases: [],
  audience: [],
  prohibited_contexts: [],
  field_sources: {},
  field_confidence: {},
  warnings: ["This profile was entered manually. Verify every field before analysis."],
  profile_version: "2.0",
  status: "needs_review"
});

function tierTone(tier: string): "success" | "warning" | "danger" | "cyan" {
  if (tier === "Strong fit") return "success";
  if (tier === "Conditional fit" || tier === "Weak fit") return "warning";
  if (tier === "Not suitable") return "danger";
  return "cyan";
}

function fieldLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function ScoreCard({ label, value, help }: { label: string; value: number; help: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/40 p-4">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-white">{value}<span className="text-base text-slate-500">/100</span></p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{help}</p>
    </div>
  );
}

function ChipEditor({
  id,
  label,
  values,
  placeholder,
  onChange
}: {
  id: string;
  label: string;
  values: string[];
  placeholder: string;
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim().replace(/,$/, "");
    if (value && !values.some((item) => item.toLowerCase() === value.toLowerCase())) onChange([...values, value]);
    setDraft("");
  };

  return (
    <div>
      <label htmlFor={id} className="text-sm text-slate-400">{label}</label>
      <div className="mt-1 rounded-md border border-border bg-surface p-2 focus-within:ring-2 focus-within:ring-white/20">
        <div className="flex flex-wrap gap-2">
          {values.map((value) => (
            <span key={value} className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-black px-2 py-1 text-sm text-zinc-200">
              {value}
              <button type="button" onClick={() => onChange(values.filter((item) => item !== value))} aria-label={`Remove ${value}`} className="rounded p-0.5 text-slate-500 hover:text-white">
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <input
            id={id}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                add();
              }
            }}
            placeholder={placeholder}
            className="h-9 min-w-0 flex-1 bg-transparent px-1 text-base text-white outline-none placeholder:text-slate-600"
          />
          <button type="button" onClick={add} disabled={!draft.trim()} aria-label={`Add ${label.toLowerCase()}`} className="rounded-md border border-white/10 px-2 text-slate-400 hover:text-white disabled:opacity-40">
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function EvidenceList({ title, items, tone = "default" }: { title: string; items: string[]; tone?: "default" | "warning" | "danger" }) {
  const colors = tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-slate-300";
  return (
    <div>
      <p className="text-sm font-semibold text-white">{title}</p>
      {items.length ? (
        <ul className={`mt-2 space-y-2 text-sm leading-6 ${colors}`}>
          {items.map((item) => <li key={item} className="flex gap-2"><ChevronRight className="mt-1.5 h-3.5 w-3.5 shrink-0" /> <span>{item}</span></li>)}
        </ul>
      ) : <p className="mt-2 text-sm text-slate-500">No items to report.</p>}
    </div>
  );
}

function PlacementCard({ placement, rank }: { placement: ProductPlacement; rank: number }) {
  const jumpToMoment = () => {
    const player = document.getElementById("video-preview-player") as HTMLVideoElement | null;
    if (player) {
      player.currentTime = placement.start;
      player.scrollIntoView({ behavior: "smooth", block: "center" });
      void player.play().catch(() => undefined);
    }
  };
  const coverage = placement.evidence_coverage ?? {};
  return (
    <article className="overflow-hidden rounded-lg border border-white/10 bg-black/40">
      <div className="grid md:grid-cols-[150px_1fr]">
        <div className="flex min-h-32 items-center justify-center bg-zinc-950">
          {placement.thumbnail_url ? <img src={absoluteMediaUrl(placement.thumbnail_url) ?? undefined} alt={`Video frame at ${formatRange(placement.start, placement.end)}`} className="h-full w-full object-cover" /> : <ImageIcon className="h-8 w-8 text-slate-700" />}
        </div>
        <div className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">{rank === 1 ? "Best placement" : `Alternative ${rank - 1}`}</p>
              <h4 className="mt-1 text-lg font-semibold text-white">{formatRange(placement.start, placement.end)} · {placement.placement_type}</h4>
            </div>
            <Badge tone={placement.is_best_placement ? "success" : "cyan"}>{placement.placement_score}/100</Badge>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">{placement.recommendation}</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
            <span className="rounded border border-white/10 px-2 py-1">Relevance {placement.product_relevance_score}</span>
            <span className="rounded border border-white/10 px-2 py-1">Readiness {placement.placement_readiness_score}</span>
            <span className="rounded border border-white/10 px-2 py-1">Suggested duration {placement.suggested_duration ?? "Review manually"}</span>
          </div>
          <p className="mt-3 text-xs text-slate-500">Evidence: {coverage.transcript_matches ?? 0} transcript · {coverage.topic_matches ?? 0} topic · {coverage.visual_matches ?? 0} visual matches</p>
          {placement.transcript_excerpt ? <blockquote className="mt-3 border-l-2 border-white/20 pl-3 text-sm italic leading-6 text-slate-400">“{placement.transcript_excerpt}”</blockquote> : null}
          <div className="mt-4 flex flex-wrap gap-3">
            <Button type="button" variant="secondary" onClick={jumpToMoment}><Clock3 className="h-4 w-4" /> Jump to moment</Button>
            <details className="min-w-full rounded-md border border-white/10 bg-zinc-950 p-3 text-sm text-slate-400">
              <summary className="cursor-pointer font-semibold text-zinc-200">How this placement was calculated</summary>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <EvidenceList title="Supporting evidence" items={placement.positive_evidence ?? placement.reasons} />
                <EvidenceList title="Weak or conflicting evidence" items={[...(placement.conflicting_evidence ?? []), ...(placement.limitations ?? [])]} tone="warning" />
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(placement.component_breakdown ?? {}).map(([label, value]) => (
                  <div key={label} className="flex justify-between rounded border border-white/10 px-3 py-2"><span>{fieldLabel(label)}</span><span className="font-semibold text-white">{value}</span></div>
                ))}
              </div>
            </details>
          </div>
        </div>
      </div>
    </article>
  );
}

export function BrandFitPanel({ videoId }: { videoId: string }) {
  const [url, setUrl] = useState("");
  const [profile, setProfile] = useState<ProductProfile | null>(null);
  const [recentProducts, setRecentProducts] = useState<ProductProfile[]>([]);
  const [loading, setLoading] = useState<"resolve" | "fit" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fit, setFit] = useState<ProductFitPayload | null>(null);

  useEffect(() => {
    getRecentProducts().then((result) => setRecentProducts(result.products)).catch(() => undefined);
  }, []);

  const markEdited = (field: string) => ({
    ...(profile?.field_sources ?? {}),
    [field]: "User edited"
  });

  const updateText = (field: "name" | "brand_name" | "category" | "description", value: string) => {
    if (!profile) return;
    setProfile({ ...profile, [field]: value, field_sources: markEdited(field), field_confidence: { ...(profile.field_confidence ?? {}), [field]: 100 } });
    setFit(null);
  };

  const updateList = (field: ListField, values: string[]) => {
    if (!profile) return;
    setProfile({ ...profile, [field]: values, field_sources: markEdited(field), field_confidence: { ...(profile.field_confidence ?? {}), [field]: 100 } });
    setFit(null);
  };

  async function readLink() {
    setLoading("resolve");
    setError(null);
    setFit(null);
    try {
      const extracted = await resolveProduct(url);
      setProfile({ ...emptyProfile(url), ...extracted, features: extracted.features ?? [], use_cases: extracted.use_cases ?? [] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read product information from that link.");
    } finally {
      setLoading(null);
    }
  }

  function enterManually() {
    setProfile(emptyProfile(url.trim()));
    setError(null);
    setFit(null);
  }

  async function analyzeFit() {
    if (!profile) return;
    setLoading("fit");
    setError(null);
    try {
      const saved = await createProduct({ ...profile, source_url: profile.source_url || url, canonical_url: profile.canonical_url || profile.source_url || url });
      setProfile(saved);
      const result = await runVideoProductFit(videoId, saved.id!);
      setFit(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not run product fit.");
    } finally {
      setLoading(null);
    }
  }

  const processingLabel = loading === "resolve" ? "Reading public product metadata…" : loading === "fit" ? "Comparing the reviewed profile with video moments…" : null;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 p-6">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-slate-400"><Link2 className="h-4 w-4" /> Brand and product fit <Badge tone="cyan">Beta</Badge></div>
          <h2 className="mt-3 text-2xl font-semibold text-white">Check a product against this video</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">We read public page metadata, ask you to verify it, and then compare the reviewed profile with transcript, topic, visual, safety, and placement evidence.</p>
        </div>
        <Badge tone="cyan">Human review required</Badge>
      </div>

      <div className="p-6">
        {recentProducts.length ? (
          <div className="mb-5">
            <label htmlFor="recent-product" className="text-sm font-medium text-slate-300">Use a recently reviewed product</label>
            <select id="recent-product" defaultValue="" onChange={(event) => {
              const selected = recentProducts.find((item) => item.id === event.target.value);
              if (selected) { setProfile(selected); setUrl(selected.source_url); setFit(null); setError(null); }
            }} className="mt-2 h-11 w-full max-w-xl rounded-lg border border-border bg-surface px-3 text-base text-white">
              <option value="">Choose a product…</option>
              {recentProducts.map((item) => <option key={item.id} value={item.id}>{item.brand_name ? `${item.brand_name} · ` : ""}{item.name}</option>)}
            </select>
          </div>
        ) : null}

        <label htmlFor="product-url" className="text-sm font-medium text-slate-300">Public product or brand URL</label>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row">
          <input id="product-url" value={url} onChange={(event) => setUrl(event.target.value)} type="url" placeholder="https://brand.com/product" className="h-11 min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 text-base text-white outline-none placeholder:text-slate-600 focus:ring-2 focus:ring-white/20" />
          <Button onClick={readLink} disabled={!url.trim() || loading !== null} variant="secondary">
            {loading === "resolve" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Read link
          </Button>
          <Button onClick={enterManually} disabled={!url.trim() || loading !== null} variant="ghost">Enter manually</Button>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">Only public metadata is read. NeuroAd does not verify legal claims, pricing, availability, or campaign suitability.</p>

        {processingLabel ? <div role="status" className="mt-4 flex items-center gap-3 rounded-md border border-white/10 bg-white/[0.03] p-3 text-sm text-slate-300"><LoaderCircle className="h-4 w-4 animate-spin" /> {processingLabel}</div> : null}
        {error ? <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger"><span>{error}</span><Button type="button" variant="ghost" onClick={enterManually}><RotateCcw className="h-4 w-4" /> Enter details manually</Button></div> : null}

        {profile ? (
          <section aria-labelledby="reviewed-product-heading" className="mt-6 rounded-lg border border-white/10 bg-zinc-950/70 p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex gap-4">
                {profile.image_url ? <img src={profile.image_url} alt="" className="h-20 w-20 rounded-lg border border-white/10 object-cover" /> : <div className="flex h-20 w-20 items-center justify-center rounded-lg border border-white/10 bg-black"><ImageIcon className="h-6 w-6 text-slate-700" /></div>}
                <div>
                  <h3 id="reviewed-product-heading" className="text-xl font-semibold text-white">Review what we found</h3>
                  <p className="mt-1 text-sm text-slate-400">Extraction confidence {profile.extraction_confidence ?? 0}/100 {profile.cache_status === "hit" ? "· loaded from recent metadata" : ""}</p>
                  {profile.source_url ? <a href={profile.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-white">Open source page <ExternalLink className="h-3 w-3" /></a> : null}
                </div>
              </div>
              <Badge tone="warning">Verify before analysis</Badge>
            </div>

            {(profile.warnings ?? []).length ? <div className="mt-4 rounded-md border border-warning/20 bg-warning/5 p-3"><EvidenceList title="Information to check" items={profile.warnings ?? []} tone="warning" /></div> : null}

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              {(["name", "brand_name", "category"] as const).map((field) => (
                <div key={field} className="text-sm text-slate-400">
                  <label htmlFor={`product-${field}`}>{field === "name" ? "Product name" : fieldLabel(field)}</label>
                  <input id={`product-${field}`} value={profile[field] ?? ""} onChange={(event) => updateText(field, event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
                  <span className="mt-1 flex justify-between text-xs text-slate-600"><span>{profile.field_sources?.[field] ?? "Not provided"}</span><span>{profile.field_confidence?.[field] ?? 0}%</span></span>
                </div>
              ))}
              <div className="md:col-span-2"><ChipEditor id="product-features" label="Features and ingredients" values={profile.features ?? []} placeholder="Add a feature or ingredient" onChange={(values) => updateList("features", values)} /></div>
              <ChipEditor id="product-use-cases" label="Use cases" values={profile.use_cases ?? []} placeholder="Add a use case" onChange={(values) => updateList("use_cases", values)} />
              <ChipEditor id="product-audience" label="Target audience" values={profile.audience ?? []} placeholder="Add an audience" onChange={(values) => updateList("audience", values)} />
              <div className="md:col-span-2"><ChipEditor id="product-keywords" label="Additional matching terms" values={profile.keywords ?? []} placeholder="Add a specific product term" onChange={(values) => updateList("keywords", values)} /></div>
              <div className="md:col-span-2"><ChipEditor id="product-exclusions" label="Prohibited or unsuitable contexts" values={profile.prohibited_contexts ?? []} placeholder="Add a context to avoid" onChange={(values) => updateList("prohibited_contexts", values)} /></div>
              <div className="text-sm text-slate-400 md:col-span-2">
                <label htmlFor="product-description">Description</label>
                <textarea id="product-description" value={profile.description ?? ""} onChange={(event) => updateText("description", event.target.value)} rows={3} className="mt-1 w-full rounded-md border border-border bg-surface p-3 text-white" />
                <span className="mt-1 flex justify-between text-xs text-slate-600"><span>{profile.field_sources?.description ?? "Not provided"}</span><span>{profile.field_confidence?.description ?? 0}%</span></span>
              </div>
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
              <p className="max-w-2xl text-xs leading-5 text-slate-500">Your reviewed values are authoritative. Editing them creates a new profile fingerprint and refreshes only the product-fit calculation.</p>
              <Button onClick={analyzeFit} disabled={!profile.name.trim() || loading !== null}>{loading === "fit" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null} Analyze fit</Button>
            </div>
          </section>
        ) : null}

        {fit ? (
          <section aria-labelledby="product-fit-result" className="mt-6 space-y-5">
            <div className="rounded-lg border border-white/10 bg-zinc-950/70 p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><p className="text-sm text-slate-400">Product fit result</p><h3 id="product-fit-result" className="mt-1 text-3xl font-semibold text-white">{fit.suitability_tier}</h3></div>
                <div className="flex flex-wrap gap-2"><Badge tone={tierTone(fit.suitability_tier)}>{fit.overall_fit_score}/100 opportunity</Badge><Badge tone="cyan">Scoring v{fit.scoring_version}</Badge>{fit.cache_status === "hit" ? <Badge tone="success">Reused result</Badge> : null}</div>
              </div>
              <p className="mt-4 max-w-4xl text-base leading-7 text-slate-300">{fit.summary}</p>
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                <ScoreCard label="Product relevance" value={fit.product_relevance_score} help="Whether the reviewed product belongs in this content." />
                <ScoreCard label="Placement readiness" value={fit.placement_readiness_score} help="Whether the strongest moment can support an integration." />
                <ScoreCard label="Evidence confidence" value={fit.fit_confidence} help="Coverage and quality of transcript, topic, and visual evidence." />
              </div>
              <div className="mt-5 rounded-md border border-white/10 bg-black/40 p-4"><p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">Recommended next action</p><p className="mt-2 font-semibold leading-6 text-white">{fit.recommended_action}</p></div>
            </div>

            <div className="grid gap-5 lg:grid-cols-[1fr_0.9fr]">
              <div className="rounded-lg border border-white/10 bg-zinc-950/70 p-5">
                <h4 className="text-lg font-semibold text-white">Why this result</h4>
                <div className="mt-4 grid gap-4 md:grid-cols-2"><EvidenceList title="Supporting evidence" items={fit.positive_evidence ?? []} /><EvidenceList title="What weakens it" items={[...(fit.conflicting_evidence ?? []), ...(fit.limitations ?? [])]} tone="warning" /></div>
                <p className="mt-4 border-t border-white/10 pt-4 text-sm text-slate-400">Coverage: {fit.evidence_coverage?.transcript_matches ?? 0} transcript matches, {fit.evidence_coverage?.topic_matches ?? 0} topic matches, and {fit.evidence_coverage?.visual_matches ?? 0} product-specific visual matches.</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-zinc-950/70 p-5">
                <h4 className="text-lg font-semibold text-white">Score breakdown</h4>
                <div className="mt-4 space-y-3">{Object.entries(fit.component_scores ?? {}).map(([label, value]) => <div key={label}><div className="flex justify-between text-sm"><span className="text-slate-400">{fieldLabel(label)}</span><span className="font-semibold text-white">{value}</span></div><div className="mt-1 h-1.5 rounded-full bg-white/10"><div className="h-full rounded-full bg-zinc-200" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>)}</div>
              </div>
            </div>

            {(fit.missing_input_warnings ?? []).length ? <div className="rounded-lg border border-warning/20 bg-warning/5 p-4"><EvidenceList title="How to improve confidence" items={fit.missing_input_warnings} tone="warning" /></div> : null}
            <div><h4 className="text-xl font-semibold text-white">Recommended placements</h4><p className="mt-1 text-sm text-slate-400">The first result is the strongest available moment; alternatives explain the trade-offs.</p><div className="mt-4 space-y-4">{fit.placements.slice(0, 3).map((placement, index) => <PlacementCard key={placement.id} placement={placement} rank={index + 1} />)}</div></div>
          </section>
        ) : null}
      </div>
    </Card>
  );
}
