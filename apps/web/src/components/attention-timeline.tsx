"use client";

import { AlertTriangle, BadgeDollarSign, Circle } from "lucide-react";
import { capture } from "@/lib/analytics";
import { absoluteMediaUrl, formatRange } from "@/lib/api";
import { useExplorerStore } from "@/lib/store";
import type { Segment } from "@/lib/types";
import { Badge } from "./ui";

function scoreColor(score: number) {
  if (score >= 80) return "bg-success";
  if (score >= 60) return "bg-zinc-100";
  if (score >= 40) return "bg-warning";
  return "bg-danger";
}

export function AttentionTimeline({ segments }: { segments: Segment[] }) {
  const setSelectedSegment = useExplorerStore((state) => state.setSelectedSegment);
  if (!segments.length) {
    return <div className="rounded-lg border border-dashed border-border p-8 text-center text-base text-slate-400">No timeline data yet.</div>;
  }
  return (
    <div className="dashboard-attention-timeline timeline-grid overflow-x-auto rounded-lg border border-border bg-black p-4 sm:p-5">
      <div className="flex min-w-[980px] items-end gap-2.5">
        {segments.map((segment, index) => (
          <button
            key={segment.id}
            type="button"
            onClick={() => {
              setSelectedSegment(segment);
              capture("segment_opened", { segment_id: segment.id, segment_index: index });
            }}
            className="group flex min-w-28 flex-1 flex-col items-stretch gap-2 text-left"
            title={`Attention Proxy Score ${segment.attention_score}`}
          >
            <div className="dashboard-attention-frame relative h-20 overflow-hidden rounded-md bg-[#0d0c16] ring-1 ring-border transition group-hover:ring-cyan/70">
              {segment.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={absoluteMediaUrl(segment.thumbnail_url) ?? undefined} alt="" className="h-full w-full object-cover opacity-75 transition group-hover:scale-105" />
              ) : (
                <div className="h-full w-full bg-[radial-gradient(circle_at_28%_22%,rgba(28,201,190,.32),transparent_34%),linear-gradient(135deg,#242039,#0b0a13_70%)]" />
              )}
              <span className={`${scoreColor(segment.attention_score)} absolute bottom-0 left-0 h-1.5`} style={{ width: `${Math.max(8, segment.attention_score)}%` }} />
              <span className="absolute right-1.5 top-1.5 rounded bg-black/75 px-1.5 py-0.5 text-[10px] font-bold text-white">{segment.attention_score}</span>
            </div>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-slate-200">{formatRange(segment.start, segment.end)}</p>
              <div className="flex items-center gap-1 text-sm text-slate-400">
                {segment.ad_fit_score >= 75 ? <BadgeDollarSign className="h-3.5 w-3.5 text-success" /> : null}
                {segment.attention_score < 40 ? <AlertTriangle className="h-3.5 w-3.5 text-danger" /> : null}
                <span>{segment.attention_score}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {segment.topics.slice(0, 1).map((topic) => (
                  <Badge key={topic.label} tone="cyan">
                    {topic.label}
                  </Badge>
                ))}
                {!segment.topics.length ? <Circle className="h-3 w-3 text-slate-600" /> : null}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
