"use client";

import { useEffect, useState } from "react";
import { ApiError, ExplainResponse, getExplainByHash } from "@/lib/api";
import { ShapWaterfall } from "./ShapWaterfall";

interface ExplanationFromHashProps {
  sha256: string;
  topN?: number;
}

/**
 * Permalink-friendly explanation panel.
 *
 * Renders one SHAP waterfall per model, *only* when the backend can
 * reconstruct the bytes from the sample registry. A 404 (e.g. when the
 * permalink points to a user upload whose bytes were never retained)
 * silently hides the component — the deep-link page already explains
 * elsewhere why explanations may be unavailable, and a redundant error
 * banner here would be noise.
 *
 * Errors *other than 404* (network failure, 5xx) still surface, because
 * those are real problems the user can act on.
 */
export function ExplanationFromHash({ sha256, topN = 12 }: ExplanationFromHashProps) {
  const [data, setData] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    setUnavailable(false);
    setData(null);

    getExplainByHash(sha256, { topN, signal: ctrl.signal })
      .then(setData)
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setUnavailable(true);
          return;
        }
        setError(err instanceof ApiError ? err.detail : "Explanation request failed.");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setBusy(false);
      });

    return () => ctrl.abort();
  }, [sha256, topN]);

  if (unavailable) return null; // expected for non-sample permalinks

  return (
    <section className="space-y-4">
      <header>
        <h3 className="text-sm uppercase tracking-wide text-muted-foreground">
          Why each model decided
        </h3>
        <p className="text-xs text-muted-foreground">
          Top {topN} features by SHAP magnitude. Red bars push the verdict toward
          malicious; green bars push it toward benign.
        </p>
      </header>

      {busy && <p className="text-sm text-muted-foreground">Computing explanations…</p>}

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
