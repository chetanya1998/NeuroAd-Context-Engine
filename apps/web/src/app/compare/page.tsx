"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, BarChart3, FileVideo, Trash2, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell } from "@/components/shell";
import { Badge, Button, Card } from "@/components/ui";
import { createComparison, startComparison, uploadComparisonVideos } from "@/lib/api";

const SUPPORTED_EXTENSIONS = ["mp4", "mov", "webm", "m4v"];

export default function CompareUploadPage() {
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: async () => {
      const comparison = await createComparison("Video comparison");
      await uploadComparisonVideos(comparison.comparison_id, files);
      await startComparison(comparison.comparison_id);
      return comparison;
    },
    onSuccess: (comparison) => router.push(`/compare/analyze/${comparison.comparison_id}`),
    onError: (cause) => setError(cause instanceof Error ? cause.message : "Could not start comparison.")
  });

  function addFiles(nextFiles: FileList | null) {
    if (!nextFiles) return;
    setError(null);
    const incoming = Array.from(nextFiles);
    const invalid = incoming.find((file) => !SUPPORTED_EXTENSIONS.includes(file.name.split(".").pop()?.toLowerCase() ?? ""));
    if (invalid) {
      setError(`${invalid.name} is not supported. Use MP4, MOV, WebM, or M4V.`);
      return;
    }
    setFiles((current) => {
      const merged = [...current, ...incoming].slice(0, 5);
      if (current.length + incoming.length > 5) setError("A comparison supports up to 5 videos.");
      return merged;
    });
  }

  return (
    <AppShell>
      <main className="mx-auto max-w-5xl px-5 py-12 lg:px-10">
        <Badge tone="cyan">V1 comparison lab</Badge>
        <h1 className="mt-5 max-w-3xl text-4xl font-semibold text-white md:text-6xl">Compare creative before you publish.</h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-400 md:text-lg">
          Upload 2–5 videos. NeuroAd analyzes every video individually, then surfaces category benchmarks, A/B deltas, keyword opportunities, and the strongest ad slot.
        </p>

        <Card className="mt-10 border-white/10 bg-black p-6 md:p-8">
          <label className="flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-white/20 bg-white/[0.02] p-6 text-center transition hover:border-white/40">
            <UploadCloud className="h-8 w-8 text-white" />
            <span className="mt-4 font-semibold text-white">Choose comparison videos</span>
            <span className="mt-2 text-sm text-zinc-500">2–5 MP4, MOV, WebM, or M4V files</span>
            <input className="sr-only" type="file" accept=".mp4,.mov,.webm,.m4v" multiple onChange={(event) => addFiles(event.target.files)} />
          </label>

          {files.length ? (
            <div className="mt-5 space-y-3">
              {files.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center justify-between gap-4 rounded-lg border border-white/10 bg-zinc-950 p-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <FileVideo className="h-5 w-5 shrink-0 text-zinc-300" />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-white">Video {index + 1}: {file.name}</p>
                      <p className="mt-1 text-sm text-zinc-500">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
                    </div>
                  </div>
                  <button type="button" className="rounded-md p-2 text-zinc-500 transition hover:bg-white/10 hover:text-white" onClick={() => setFiles((items) => items.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove ${file.name}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          {error ? <p className="mt-5 text-sm text-danger">{error}</p> : null}

          <div className="mt-7 flex flex-col gap-3 border-t border-white/10 pt-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-zinc-500">Same-category videos receive direct benchmarks. Cross-category results are labeled directional.</p>
            <Button disabled={files.length < 2 || createMutation.isPending} onClick={() => createMutation.mutate()}>
              <BarChart3 className="h-4 w-4" />
              {createMutation.isPending ? "Starting analysis…" : "Analyze comparison"}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      </main>
    </AppShell>
  );
}
