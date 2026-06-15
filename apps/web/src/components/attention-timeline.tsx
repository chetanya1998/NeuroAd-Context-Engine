"use client";

import { AlertTriangle, BadgeDollarSign, Circle } from "lucide-react";
import { formatRange } from "@/lib/api";
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
    return <div className="rounded-lg border border-dashed border-border p-8 text-center text-slate-400">No timeline data yet.</div>;
  }
  return (
    <div className="timeline-grid overflow-x-auto rounded-lg border border-border bg-black p-4">
      <div className="flex min-w-[860px] items-end gap-2">
        {segments.map((segment) => (
          <button
            key={segment.id}
            type="button"
            onClick={() => setSelectedSegment(segment)}
            className="group flex min-w-24 flex-1 flex-col items-stretch gap-2 text-left"
            title={`Attention Proxy Score ${segment.attention_score}`}
          >
            <div className="flex h-40 items-end rounded-md bg-[#080808] p-1 ring-1 ring-border transition group-hover:ring-zinc-400">
              <div
                className={`${scoreColor(segment.attention_score)} w-full rounded opacity-90`}
                style={{ height: `${Math.max(12, segment.attention_score)}%` }}
              />
            </div>
            <div className="space-y-1">
              <p className="text-xs font-semibold text-slate-200">{formatRange(segment.start, segment.end)}</p>
              <div className="flex items-center gap-1 text-xs text-slate-400">
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
