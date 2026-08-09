"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { absoluteMediaUrl, formatRange, getSegmentEvidence } from "@/lib/api";
import { useExplorerStore } from "@/lib/store";
import { Badge, Button } from "./ui";

export function SegmentDrawer({ videoId }: { videoId: string }) {
  const segment = useExplorerStore((state) => state.selectedSegment);
  const setSelectedSegment = useExplorerStore((state) => state.setSelectedSegment);
  const evidenceQuery = useQuery({
    queryKey: ["segment-evidence", videoId, segment?.id],
    queryFn: () => getSegmentEvidence(videoId, segment?.id ?? ""),
    enabled: Boolean(videoId && segment?.id),
    staleTime: Number.POSITIVE_INFINITY
  });
  if (!segment) return null;
  const evidence = evidenceQuery.data;
  const frameUrl = absoluteMediaUrl(evidence?.frame.thumbnail_url ?? segment.thumbnail_url);
  const waveform = evidence?.audio?.waveform_energy ?? [];
  const ocrTexts = (evidence?.ocr?.texts ?? []).map((item) => String(item.text ?? "")).filter(Boolean);
  const findings = (["visual", "audio", "narrative", "social"] as const).flatMap((family) => {
    const values = segment.signal_summary?.[family]?.findings;
    return Array.isArray(values) ? values : [];
  });
  const reliability = segment.signal_summary?.reliability?.band ?? "Low";

  return (
    <div className="fixed inset-0 z-40 bg-black/60" onClick={() => setSelectedSegment(undefined)}>
      <aside
        className="ph-no-capture absolute right-0 top-0 h-full w-full max-w-xl overflow-y-auto border-l border-border bg-black p-6 shadow-glow"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm uppercase tracking-[0.24em] text-zinc-400">Segment</p>
            <h2 className="mt-2 text-2xl font-semibold">{formatRange(segment.start, segment.end)}</h2>
          </div>
          <Button variant="ghost" className="h-10 w-10 px-0" onClick={() => setSelectedSegment(undefined)}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <section className="mt-8 rounded-lg border border-warning/25 bg-warning/5 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold text-white">What this moment needs</h3>
            <Badge tone={reliability === "High" ? "success" : reliability === "Medium" ? "warning" : "danger"}>Evidence reliability: {reliability}</Badge>
          </div>
          <p className="mt-4 text-sm font-semibold uppercase tracking-[0.12em] text-slate-500">Why</p>
          <ul className="mt-2 space-y-1.5 text-sm leading-6 text-slate-300">
            {(findings.length ? findings : segment.failed_or_weak_signals ?? []).slice(0, 4).map((finding) => <li key={finding}>• {finding}</li>)}
            {!findings.length && !(segment.failed_or_weak_signals ?? []).length ? <li>• No urgent issue is supported by the current evidence.</li> : null}
          </ul>
          <p className="mt-4 border-t border-white/10 pt-4 text-sm leading-6 text-white"><span className="font-semibold">Suggested action:</span> {segment.recommendation}</p>
        </section>

        <details className="mt-6 rounded-lg border border-border bg-surface p-4">
          <summary className="cursor-pointer font-semibold text-slate-200">Current 0–100 scores</summary>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <ScoreBox label="Attention Proxy Score" value={segment.attention_score} />
            <ScoreBox label="Ad-Fit Score" value={segment.ad_fit_score} />
            <ScoreBox label="Recommendation Confidence" value={segment.recommendation_confidence ?? 0} />
            <ScoreBox label="Drop Risk" value={segment.drop_risk_score ?? 0} />
            <ScoreBox label="Brand Safety" value={segment.brand_safety_score ?? 100} />
          </div>
        </details>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Placement tier</h3>
          <div className="flex flex-wrap gap-2">
            <Badge tone={tierTone(segment.recommendation_tier ?? "Edit before monetization")}>{segment.recommendation_tier ?? "Edit before monetization"}</Badge>
            <Badge tone="cyan">{segment.evidence_mode ?? "weak_evidence"}</Badge>
          </div>
        </section>

        <details className="mt-8 rounded-lg border border-border bg-surface p-4">
          <summary className="cursor-pointer font-semibold text-slate-200">Advanced evidence details</summary>
          <div className="mt-4 space-y-4 text-sm leading-6 text-slate-400">
            {evidenceQuery.isLoading ? <p>Loading timestamp evidence…</p> : null}
            {evidenceQuery.isError ? <p className="text-danger">Could not load the lazy evidence layer: {evidenceQuery.error.message}</p> : null}
            {frameUrl ? (
              <div className="overflow-hidden rounded-lg border border-white/10 bg-black">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={frameUrl} alt={`Evidence frame at ${formatRange(segment.start, segment.end)}`} className="max-h-72 w-full object-contain" />
              </div>
            ) : null}
            <p><span className="text-slate-200">Detector:</span> {segment.detector_provenance?.active_detector ?? "unavailable"}{segment.detector_provenance?.fallback_reason ? ` — ${segment.detector_provenance.fallback_reason}` : ""}</p>
            <p><span className="text-slate-200">Tracked objects:</span> {evidence?.frame.objects?.length ?? segment.detector_provenance?.tracked_instances ?? segment.objects.length}</p>
            <p><span className="text-slate-200">Face/subject boxes:</span> {(evidence?.frame.face_landmark_boxes?.reduce((total, sample) => total + (sample.boxes?.length ?? 0), 0) ?? 0) + (evidence?.frame.face_subject_boxes?.length ?? 0)}</p>
            <p><span className="text-slate-200">OCR:</span> {ocrTexts.length ? ocrTexts.join(" · ") : segment.ocr_evidence?.available ? `${segment.ocr_evidence.texts?.length ?? 0} text observations` : "unavailable"}</p>
            <p><span className="text-slate-200">Audio extractor:</span> {String(segment.audio_evidence?.extractor ?? "unavailable")}</p>
            {waveform.length ? (
              <div>
                <p className="text-slate-200">Audio waveform / energy</p>
                <div className="mt-2 flex h-16 items-center gap-px rounded-md border border-white/10 bg-black/30 px-2" aria-label="Audio energy waveform">
                  {waveform.map((value, index) => <span key={`${index}-${value}`} className="min-w-px flex-1 rounded-sm bg-cyan-400/70" style={{ height: `${Math.max(4, Math.min(100, value * 100))}%` }} />)}
                </div>
              </div>
            ) : null}
            <p><span className="text-slate-200">Scene boundaries:</span> {evidence?.scenes?.boundaries?.length ? evidence.scenes.boundaries.map((value) => `${value.toFixed(2)}s`).join(", ") : "none detected in this segment"}</p>
            <p><span className="text-slate-200">Word evidence:</span> {evidence?.transcript?.words?.length ? `${evidence.transcript.words.length} timestamped words · ${evidence.transcript.language ?? "language unknown"}` : "unavailable"}</p>
            <p><span className="text-slate-200">Human review:</span> {evidence?.human_review?.state ?? segment.review_state ?? "unreviewed"}</p>
            {evidence?.model_manifests?.length ? (
              <div>
                <p className="text-slate-200">Extractor/model versions</p>
                <ul className="mt-2 space-y-1 font-mono text-xs text-slate-500">
                  {evidence.model_manifests.map((manifest) => (
                    <li key={manifest.extractor}>{manifest.extractor}: {manifest.model_version ?? "model unavailable"}{manifest.library_version ? ` · ${manifest.library_version}` : ""}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </details>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Score evidence</h3>
          <div className="flex flex-wrap gap-2">
            {(segment.score_reasons ?? []).length ? (
              segment.score_reasons.map((reason) => <Badge key={reason}>{reason}</Badge>)
            ) : (
              <p className="text-sm text-slate-400">No score evidence captured.</p>
            )}
          </div>
        </section>

        <section className="mt-8 grid gap-3 sm:grid-cols-2">
          <EvidenceBox label="Transcript clarity" value={segment.transcript_insights?.clarity_score ?? 0} />
          <EvidenceBox label="Transcript confidence" value={segment.transcript_insights?.transcript_confidence ?? segment.transcript_insights?.clarity_score ?? 0} />
          <EvidenceBox label="Words/sec" value={segment.transcript_insights?.words_per_second ?? 0} />
          <EvidenceBox label="Visual quality" value={Math.round((segment.visual_evidence?.visual_quality ?? 0) * 100)} />
          <EvidenceBox label="Sampled frames" value={segment.visual_evidence?.sampled_frames ?? 0} />
        </section>

        <section className="mt-8 grid gap-4 sm:grid-cols-2">
          <SignalBox title="Strong signals" signals={segment.strong_signals ?? []} empty="No strong signals captured." />
          <SignalBox title="Weak signals" signals={segment.failed_or_weak_signals ?? []} empty="No weak signals captured." />
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Transcript flags</h3>
          <div className="flex flex-wrap gap-2">
            {(segment.transcript_insights?.hook_terms ?? []).map((term) => (
              <Badge key={`hook-${term}`} tone="success">Hook: {term}</Badge>
            ))}
            {(segment.transcript_insights?.cta_terms ?? []).map((term) => (
              <Badge key={`cta-${term}`} tone="cyan">CTA: {term}</Badge>
            ))}
            {(segment.transcript_insights?.claim_terms ?? []).map((term) => (
              <Badge key={`claim-${term}`} tone="warning">Claim: {term}</Badge>
            ))}
            {(segment.transcript_insights?.transcript_quality_flags ?? []).map((term) => (
              <Badge key={`quality-${term}`} tone="warning">Quality: {term}</Badge>
            ))}
            {Object.entries(segment.transcript_insights?.risk_flags ?? {}).map(([label, terms]) => (
              <Badge key={label} tone="danger">{label}: {terms.join(", ")}</Badge>
            ))}
            {!(segment.transcript_insights?.hook_terms?.length || segment.transcript_insights?.cta_terms?.length || segment.transcript_insights?.claim_terms?.length || segment.transcript_insights?.transcript_quality_flags?.length || Object.keys(segment.transcript_insights?.risk_flags ?? {}).length) ? (
              <p className="text-sm text-slate-400">No transcript flags in this segment.</p>
            ) : null}
          </div>
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Detected objects</h3>
          <div className="flex flex-wrap gap-2">
            {segment.objects.length ? (
              segment.objects.map((object) => (
                <Badge key={`${object.label}-${object.confidence}`}>
                  {object.label} {Math.round(object.confidence * 100)}%
                </Badge>
              ))
            ) : (
              <p className="text-sm text-slate-400">No strong object detections in this segment.</p>
            )}
          </div>
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Transcript</h3>
          <p className="rounded-lg border border-border bg-surface p-4 text-sm leading-6 text-slate-300">
            {segment.transcript || "No speech detected."}
          </p>
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Suggested ads</h3>
          <div className="space-y-3">
            {segment.ad_matches.length ? (
              segment.ad_matches.map((match) => (
                <div key={match.ad_category} className="rounded-lg border border-border bg-surface p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{match.ad_category}</p>
                    <Badge tone={match.ad_fit_score >= 75 ? "success" : "warning"}>{match.ad_fit_score}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-slate-400">{match.reason}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-400">No reliable ad category match.</p>
            )}
          </div>
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="font-semibold">Recommendation</h3>
          <p className="rounded-lg border border-zinc-700 bg-white/5 p-4 text-sm leading-6 text-slate-200">
            {segment.recommendation}
          </p>
        </section>
      </aside>
    </div>
  );
}

function ScoreBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{Math.round(value)}</p>
    </div>
  );
}

function EvidenceBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-2 text-xl font-semibold">{Math.round(value * 10) / 10}</p>
    </div>
  );
}

function SignalBox({ title, signals, empty }: { title: string; signals: string[]; empty: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-sm font-semibold">{title}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {signals.length ? signals.map((signal) => <Badge key={signal}>{signal}</Badge>) : <p className="text-sm text-slate-400">{empty}</p>}
      </div>
    </div>
  );
}

function tierTone(tier: string): "success" | "warning" | "danger" | "cyan" {
  if (tier === "Strong ad slot") return "success";
  if (tier === "Conditional ad slot") return "cyan";
  if (tier === "Avoid") return "danger";
  return "warning";
}
