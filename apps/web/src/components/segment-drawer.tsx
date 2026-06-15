"use client";

import { X } from "lucide-react";
import { formatRange } from "@/lib/api";
import { useExplorerStore } from "@/lib/store";
import { Badge, Button } from "./ui";

export function SegmentDrawer() {
  const segment = useExplorerStore((state) => state.selectedSegment);
  const setSelectedSegment = useExplorerStore((state) => state.setSelectedSegment);
  if (!segment) return null;

  return (
    <div className="fixed inset-0 z-40 bg-black/60" onClick={() => setSelectedSegment(undefined)}>
      <aside
        className="absolute right-0 top-0 h-full w-full max-w-xl overflow-y-auto border-l border-border bg-black p-6 shadow-glow"
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

        <div className="mt-8 grid grid-cols-2 gap-3">
          <ScoreBox label="Attention Proxy Score" value={segment.attention_score} />
          <ScoreBox label="Ad-Fit Score" value={segment.ad_fit_score} />
        </div>

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
