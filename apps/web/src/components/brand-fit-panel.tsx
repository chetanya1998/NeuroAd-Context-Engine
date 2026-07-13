"use client";

import { Link2, LoaderCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import { createProduct, formatRange, resolveProduct, runVideoProductFit } from "@/lib/api";
import type { ProductFitPayload, ProductProfile } from "@/lib/types";
import { Badge, Button, Card } from "./ui";

const commaList = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

function tierTone(tier: string): "success" | "warning" | "danger" | "cyan" {
  if (tier === "Strong fit") return "success";
  if (tier === "Conditional fit") return "warning";
  if (tier === "Not suitable") return "danger";
  return "cyan";
}

export function BrandFitPanel({ videoId }: { videoId: string }) {
  const [url, setUrl] = useState("");
  const [profile, setProfile] = useState<ProductProfile | null>(null);
  const [keywords, setKeywords] = useState("");
  const [audience, setAudience] = useState("");
  const [blocked, setBlocked] = useState("");
  const [loading, setLoading] = useState<"resolve" | "fit" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fit, setFit] = useState<ProductFitPayload | null>(null);

  async function resolve() {
    setLoading("resolve");
    setError(null);
    setFit(null);
    try {
      const extracted = await resolveProduct(url);
      setProfile(extracted);
      setKeywords(extracted.keywords.join(", "));
      setAudience(extracted.audience.join(", "));
      setBlocked(extracted.prohibited_contexts.join(", "));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read product information from that link.");
    } finally {
      setLoading(null);
    }
  }

  async function analyzeFit() {
    if (!profile) return;
    setLoading("fit");
    setError(null);
    try {
      const saved = profile.id
        ? profile
        : await createProduct({
            ...profile,
            source_url: profile.source_url || url,
            keywords: commaList(keywords),
            audience: commaList(audience),
            prohibited_contexts: commaList(blocked)
          });
      setProfile(saved);
      setFit(await runVideoProductFit(videoId, saved.id!));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not run product fit.");
    } finally {
      setLoading(null);
    }
  }

  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-slate-400"><Link2 className="h-4 w-4" /> Brand and product fit</div>
          <h2 className="mt-3 text-2xl font-semibold text-white">Check a product against this video</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">Paste a public product or brand URL. Review the extracted profile, then get timestamp-level placement recommendations with explicit evidence.</p>
        </div>
        <Badge tone="cyan">Human review required</Badge>
      </div>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          type="url"
          placeholder="https://brand.com/product"
          className="h-11 min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 text-base text-white outline-none placeholder:text-slate-600 focus:ring-2 focus:ring-white/20"
        />
        <Button onClick={resolve} disabled={!url.trim() || loading !== null} variant="secondary">
          {loading === "resolve" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Read link
        </Button>
      </div>

      {profile ? (
        <div className="mt-5 grid gap-4 rounded-lg border border-white/10 bg-zinc-950/70 p-4 md:grid-cols-2">
          <label className="text-sm text-slate-400">Product name
            <input value={profile.name} onChange={(event) => setProfile({ ...profile, name: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400">Brand
            <input value={profile.brand_name ?? ""} onChange={(event) => setProfile({ ...profile, brand_name: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400">Category
            <input value={profile.category ?? ""} onChange={(event) => setProfile({ ...profile, category: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400">Keywords (comma-separated)
            <input value={keywords} onChange={(event) => setKeywords(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400">Audience cues (optional)
            <input value={audience} onChange={(event) => setAudience(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400">Avoid these contexts (optional)
            <input value={blocked} onChange={(event) => setBlocked(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-white" />
          </label>
          <label className="text-sm text-slate-400 md:col-span-2">Description
            <textarea value={profile.description ?? ""} onChange={(event) => setProfile({ ...profile, description: event.target.value })} rows={3} className="mt-1 w-full rounded-md border border-border bg-surface p-3 text-white" />
          </label>
          <div className="flex items-end justify-between gap-3 md:col-span-2">
            <p className="text-sm text-slate-500">Link extraction confidence: {profile.extraction_confidence ?? 0}. Adjust fields before continuing.</p>
            <Button onClick={analyzeFit} disabled={!profile.name.trim() || loading !== null}>
              {loading === "fit" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              Analyze fit
            </Button>
          </div>
        </div>
      ) : null}

      {error ? <p className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">{error}</p> : null}

      {fit ? (
        <div className="mt-5 rounded-lg border border-white/10 bg-zinc-950/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-400">Product fit result</p>
              <h3 className="mt-1 text-2xl font-semibold text-white">{fit.overall_fit_score}/100 placement opportunity</h3>
            </div>
            <Badge tone={tierTone(fit.suitability_tier)}>{fit.suitability_tier} · confidence {fit.fit_confidence}</Badge>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">{fit.summary}</p>
          <div className="mt-4 space-y-3">
            {fit.placements.slice(0, 3).map((placement) => (
              <div key={placement.id} className="rounded-md border border-white/10 bg-black/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold text-white">{formatRange(placement.start, placement.end)} · {placement.placement_type}</p>
                  <Badge tone={placement.is_best_placement ? "success" : "cyan"}>{placement.placement_score}</Badge>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-300">{placement.recommendation}</p>
                <p className="mt-2 text-xs leading-5 text-slate-500">{placement.reasons.join(" · ")}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
