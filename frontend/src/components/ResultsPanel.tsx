"use client";

import { useState } from "react";
import { ModelPrediction, ScanResponse } from "@/lib/api";

interface ResultsPanelProps {
  result: ScanResponse;
  /**
   * `mock_mode` from /models. Surfaced here so the panel can show a
   * top-banner instead of relying on each per-prediction `is_mock` flag,
   * which the /scan response doesn't currently carry. (Future: stamp
   * `is_mock` into ModelPrediction itself; for now `/models` is the
   * source of truth.)
   */
  mockMode: boolean | null;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatConfidence(c: number): string {
  return `${(c * 100).toFixed(1)}%`;
}

function ShareButton({ sha256 }: { sha256: string }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  const handleShare = async () => {
    if (typeof window === "undefined") return;
    const url = `${window.location.origin}/scan/${sha256}`;
    try {
      await navigator.clipboard.writeText(url);
      setState("copied");
      setTimeout(() => setState("idle"), 1500);
    } catch {
      // Clipboard API can fail in non-secure contexts (HTTP) or when the
      // tab isn't focused; surface that rather than silently swallowing.
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
  };

  return (
    <button
      type="button"
      onClick={handleShare}
      className="rounded-md border border-border px-2 py-1 text-xs text-zinc-300 hover:border-accent hover:text-accent"
      title="Copy permalink to this scan"
    >
      {state === "copied" ? "Copied!" : state === "error" ? "Copy failed" : "Share"}
    </button>
  );
}

function labelClass(label: ModelPrediction["label"]): string {
  return label === "malicious"
    ? "text-danger"
    : label === "benign"
      ? "text-ok"
      : "text-zinc-300";
}

export function ResultsPanel({ result, mockMode }: ResultsPanelProps) {
  const { sha256, features, predictions } = result;

  // "Disagreement view" — the most demo-able piece of the dashboard, per
  // TODO.md Phase 3. We highlight the row whenever any two models return
  // different labels for the same file.
  const labels = new Set(predictions.map((p) => p.label));
  const modelsDisagree = predictions.length > 1 && labels.size > 1;

  return (
    <section className="space-y-4">
      {mockMode && (
        <div
          className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn"
          role="status"
        >
          <strong>Demo mode.</strong> Predictions are produced by deterministic
          mock predictors; the real artifacts from the paper aren&apos;t
          loaded. Models still react to feature changes — see{" "}
          <code className="font-mono">is_mock</code> on{" "}
          <code className="font-mono">/models</code>.
        </div>
      )}

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm uppercase tracking-wide text-zinc-400">
            File summary
          </h3>
          <ShareButton sha256={sha256} />
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          <div>
            <dt className="text-zinc-500">Size</dt>
            <dd className="font-mono">{formatBytes(features.size_bytes)}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">Sections</dt>
            <dd className="font-mono">{features.number_of_sections}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">Imports</dt>
            <dd className="font-mono">
              {features.imported_dll_count} DLL · {features.imported_function_count} fn
            </dd>
          </div>
          <div className="col-span-2 md:col-span-3">
            <dt className="text-zinc-500">SHA-256</dt>
            <dd className="break-all font-mono text-xs text-zinc-300">{sha256}</dd>
          </div>
        </dl>
      </div>

      <div
        className={[
          "rounded-xl border bg-surface",
          modelsDisagree ? "border-warn" : "border-border",
        ].join(" ")}
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm uppercase tracking-wide text-zinc-400">
            Model predictions
          </h3>
          {modelsDisagree && (
            <span className="text-xs font-medium text-warn">Models disagree</span>
          )}
        </header>
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-zinc-500">
            <tr>
              <th className="px-4 py-2">Model</th>
              <th className="px-4 py-2">Verdict</th>
              <th className="px-4 py-2">Confidence</th>
              <th className="px-4 py-2 text-right">Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {predictions.map((pred) => (
              <tr key={pred.model_name} className="hover:bg-ink/40">
                <td className="px-4 py-3 font-mono">{pred.model_name}</td>
                <td className={["px-4 py-3 font-medium", labelClass(pred.label)].join(" ")}>
                  {pred.label}
                </td>
                <td className="px-4 py-3 font-mono">{formatConfidence(pred.confidence)}</td>
                <td className="px-4 py-3 text-right font-mono text-zinc-400">
                  {pred.latency_ms.toFixed(2)} ms
                </td>
              </tr>
            ))}
            {predictions.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-4 text-center text-zinc-500">
                  No predictions returned.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
