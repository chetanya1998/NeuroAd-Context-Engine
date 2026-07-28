"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Download, Plug, Sparkles, WandSparkles } from "lucide-react";
import { useState } from "react";
import { getMcpHandoffPackage, mcpHandoffExportUrl } from "@/lib/api";
import type { McpTarget } from "@/lib/types";
import { Badge, Button, Card } from "./ui";

const targets: Array<{ id: McpTarget; label: string; detail: string }> = [
  { id: "mcp", label: "Universal MCP", detail: "Structured context for any MCP-capable agent or editor" },
  { id: "canva", label: "Canva", detail: "Creative brief, cut plan, captions, and storyboard context" },
  { id: "heygen", label: "HeyGen", detail: "Scene beats for avatar, voiceover, and localization workflows" },
  { id: "prompt_video", label: "Prompt-to-video", detail: "Grounded scene prompts for generative video tools" }
];

export function McpIntegrationPanel({ videoId }: { videoId: string }) {
  const [target, setTarget] = useState<McpTarget>("mcp");
  const [copied, setCopied] = useState(false);
  const packageQuery = useQuery({
    queryKey: ["mcp-handoff", videoId, target],
    queryFn: () => getMcpHandoffPackage(videoId, target)
  });
  const handoff = packageQuery.data;

  async function copyPrompt() {
    if (!handoff) return;
    await navigator.clipboard.writeText(handoff.handoff_prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <Card className="overflow-hidden border-white/10 bg-black">
      <div className="border-b border-white/10 p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="cyan"><Plug className="mr-1.5 h-3.5 w-3.5" /> MCP integration</Badge>
              <Badge tone="cyan">Beta</Badge>
            </div>
            <h2 className="mt-3 text-2xl font-semibold text-white">Continue this video in your AI creative tool</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Turn the full timestamped analysis into an edit-ready brief, scene prompts, and a portable evidence package.
              Source media and account access stay under your control.
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">Deep handoff</p>
            <p className="mt-1 text-sm font-semibold text-white">{handoff?.provenance.segment_count ?? "—"} evidence-linked moments</p>
          </div>
        </div>
      </div>

      <div className="grid gap-5 p-5 sm:p-6 xl:grid-cols-[0.85fr_1.15fr]">
        <div>
          <p className="text-sm font-semibold text-white">Choose a destination</p>
          <div className="mt-3 grid gap-2">
            {targets.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTarget(item.id)}
                className={`rounded-lg border p-3 text-left transition ${
                  target === item.id ? "border-white/30 bg-white/[0.08]" : "border-white/10 bg-zinc-950 hover:bg-white/[0.04]"
                }`}
              >
                <span className="flex items-center justify-between gap-3">
                  <span className="font-semibold text-white">{item.label}</span>
                  {target === item.id ? <Check className="h-4 w-4 text-success" /> : null}
                </span>
                <span className="mt-1 block text-xs leading-5 text-zinc-500">{item.detail}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-zinc-950 p-4 sm:p-5">
          {packageQuery.isLoading ? <p className="text-sm text-zinc-500">Preparing the handoff package…</p> : null}
          {packageQuery.isError ? <p className="text-sm text-danger">{packageQuery.error.message}</p> : null}
          {handoff ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <Sparkles className="h-4 w-4 text-cyan" /> {handoff.target_profile.label} brief
                  </div>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">{handoff.target_profile.recommended_action}</p>
                </div>
                <Badge tone="success">Evidence linked</Badge>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <BriefItem label="Opening direction" value={handoff.creative_brief.opening_direction} />
                <BriefItem label="Pacing direction" value={handoff.creative_brief.pacing_direction} />
              </div>

              <div className="mt-4 rounded-lg border border-white/10 bg-black p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Package contents</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge>{handoff.timeline.length} timeline decisions</Badge>
                  <Badge>{handoff.scene_prompts.length} generation prompts</Badge>
                  <Badge>{handoff.creative_brief.core_topics.length} grounded topics</Badge>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button type="button" onClick={copyPrompt} variant="primary">
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copied ? "Copied" : "Copy tool prompt"}
                </Button>
                <a href={mcpHandoffExportUrl(videoId, target, "json")}>
                  <Button type="button" variant="secondary"><Download className="h-4 w-4" /> MCP JSON</Button>
                </a>
                <a href={mcpHandoffExportUrl(videoId, target, "prompt")}>
                  <Button type="button" variant="ghost"><WandSparkles className="h-4 w-4" /> Prompt file</Button>
                </a>
              </div>
              <p className="mt-4 text-xs leading-5 text-zinc-500">
                This creates a portable handoff; it does not publish or spend credits in the selected service. Review generated scenes, claims, licensing, and brand assets before use.
              </p>
            </>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function BriefItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.025] p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-2 text-sm leading-6 text-zinc-200">{value}</p>
    </div>
  );
}
