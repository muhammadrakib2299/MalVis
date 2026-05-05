"use client";

import { useEffect, useState } from "react";
import { ApiError, ExplainResponse, postExplain } from "@/lib/api";
import { ShapWaterfall } from "./ShapWaterfall";

interface ExplanationPanelProps {
  /**
   * The PE file the user just uploaded. We re-POST it to /explain
   * because explanations don't (today) live behind a SHA-256 lookup.
   * That's a deliberate trade-off: the cache layer is for predictions,
   * not for SHAP — keeps the cache key surface small and avoids racing
   * with a model swap between scan and explain.
   */
  file: File;
  /** From /scan — used to confirm the explain response matches the same file. */
  expectedSha256: string;
  /** Top-N contributions to render per model. */
  topN?: number;
}

export function ExplanationPanel({ file, expectedSha256, topN = 12 }: ExplanationPanelProps) {
  const [data, setData] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    setData(null);

    postExplain(file, { topN, signal: ctrl.signal })
      .then((response) => {
        if (response.sha256 !== expectedSha256) {
          // Should not happen — the same file produces the same SHA — but
          // catching this surfaces any future backend bug loudly.
          setError(
            `SHA-256 mismatch between scan (${expectedSha256.slice(0, 12)}…) and explain (${response.sha256.slice(0, 12)}…).`,
          );
          return;
        }
        setData(response);
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setError(err instanceof ApiError ? err.detail : "Explanation request failed.");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setBusy(false);
      });

    return () => ctrl.abort();
  }, [file, expectedSha256, topN]);

  return (
    <section className="space-y-4">
      <header>
        <h3 className="text-sm uppercase tracking-wide text-zinc-400">
          Why each model decided
        </h3>
        <p className="text-xs text-zinc-500">
          Top {topN} features by SHAP magnitude. Red bars push the verdict toward
          malicious; green bars push it toward benign.
        </p>
      </header>

      {busy && <p className="text-sm text-zinc-400">Computing explanations…</p>}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {data?.explanations.map((exp) => (
        <article
          key={exp.model_name}
          className="rounded-xl border border-border bg-surface p-4"
        >
          <header className="mb-3 flex items-center justify-between">
            <h4 className="font-mono text-sm">{exp.model_name}</h4>
            {exp.is_mock && (
              <span className="rounded bg-warn/20 px-1.5 py-0.5 text-xs text-warn">
                mock
              </span>
            )}
          </header>
          <ShapWaterfall
            contributions={exp.contributions}
            baseValue={exp.base_value}
            label={exp.label}
            confidence={exp.confidence}
          />
        </article>
      ))}
    </section>
  );
}
