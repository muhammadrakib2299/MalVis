"use client";

import type { FeatureContribution } from "@/lib/api";

interface ShapWaterfallProps {
  contributions: FeatureContribution[];
  /**
   * SHAP base value (model's expected output before the feature contributions).
   * Surfaced in the header so the chart is honest about the *reference point*
   * the contributions are measured against.
   */
  baseValue: number;
  /** Final prediction label, used to colour the heading */
  label: "malicious" | "benign";
  /** Confidence in [0,1], from the same model. Surfaced in the heading */
  confidence: number;
}

/**
 * Pure-SVG, dependency-free SHAP waterfall.
 *
 * Layout: one row per feature, sorted by |shap_value| (already sorted by
 * the backend, but we don't depend on that here — we re-sort client-side
 * so a future backend change can't silently scramble the chart).
 *
 * Bar width = |shap_value| / max(|shap_value|). Sign decides the colour:
 * positive contributions push the prediction *toward* malicious (red),
 * negative push it *toward* benign (green). This convention matches how
 * tree-SHAP reports for binary classification with class 1 = malicious.
 *
 * Accessibility: each bar carries an `aria-label` summarizing the row,
 * and an `sr-only` table mirrors the data for screen readers and the
 * "tabular fallback" requirement from TODO.md Phase 3.
 */
export function ShapWaterfall({
  contributions,
  baseValue,
  label,
  confidence,
}: ShapWaterfallProps) {
  if (contributions.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No SHAP contributions available for this model.
      </p>
    );
  }

  const sorted = [...contributions].sort(
    (a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value),
  );

  const maxAbs = Math.max(...sorted.map((c) => Math.abs(c.shap_value))) || 1;

  return (
    <div>
      <header className="mb-3 flex items-baseline justify-between text-xs">
        <span className="text-zinc-500">
          Base value: <span className="font-mono text-zinc-300">{baseValue.toFixed(4)}</span>
        </span>
        <span className={label === "malicious" ? "text-danger" : "text-ok"}>
          {label} · {(confidence * 100).toFixed(1)}%
        </span>
      </header>

      <ul className="space-y-1.5" role="list">
        {sorted.map((c) => {
          const fraction = Math.abs(c.shap_value) / maxAbs; // 0..1
          const widthPct = (fraction * 100).toFixed(1);
          const positive = c.shap_value > 0; // pushes toward malicious
          return (
            <li
              key={c.feature}
              className="grid grid-cols-12 items-center gap-2 text-xs"
              aria-label={`${c.feature}: value ${c.value}, SHAP ${c.shap_value.toFixed(4)}`}
            >
              <span className="col-span-4 truncate font-mono text-zinc-300" title={c.feature}>
                {c.feature}
              </span>
              <span className="col-span-2 truncate text-right font-mono text-zinc-500" title={String(c.value)}>
                {Number.isFinite(c.value) ? c.value.toFixed(2) : "—"}
              </span>
              <div className="col-span-5 h-2 rounded bg-ink/60">
                <div
                  className={[
                    "h-full rounded",
                    positive ? "bg-danger/80" : "bg-ok/80",
                  ].join(" ")}
                  style={{ width: `${widthPct}%` }}
                />
              </div>
              <span
                className={[
                  "col-span-1 text-right font-mono tabular-nums",
                  positive ? "text-danger" : "text-ok",
                ].join(" ")}
              >
                {c.shap_value > 0 ? "+" : ""}
                {c.shap_value.toFixed(3)}
              </span>
            </li>
          );
        })}
      </ul>

      {/* Tabular fallback for screen readers and the accessibility pass. */}
      <table className="sr-only">
        <caption>SHAP feature contributions for {label} prediction</caption>
        <thead>
          <tr>
            <th>Feature</th>
            <th>Value</th>
            <th>SHAP value</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => (
            <tr key={c.feature}>
              <td>{c.feature}</td>
              <td>{c.value}</td>
              <td>{c.shap_value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
