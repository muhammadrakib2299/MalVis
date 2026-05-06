"use client";

import type { ModelInfo, ModelsResponse } from "@/lib/api";

interface ModelCardPanelProps {
  models: ModelsResponse;
}

/**
 * Project-level model documentation.
 *
 * The split between *per-model* content (id, family, training dataset,
 * metrics, paper citation, notes) and *project-level* content (intended
 * use, out-of-scope uses, known limitations) is deliberate:
 *
 *   - Per-model fields are wire data — they come from the backend's
 *     manifest and may differ between RF and XGBoost (or future models).
 *   - Project-level fields apply to MalVis as a whole; they're hard-coded
 *     here because no manifest field captures them and they should not
 *     drift when the model registry changes.
 *
 * Rationale aligns with the EU AI Act + NIST AI Risk Management Framework
 * expectation that a deployed model expose its limits and intended use
 * directly to the consumer of its predictions — not in a separate doc
 * the user has to find.
 */
export function ModelCardPanel({ models }: ModelCardPanelProps) {
  return (
    <section className="space-y-4">
      <header>
        <h3 className="text-sm uppercase tracking-wide text-muted-foreground">Model card</h3>
        <p className="text-xs text-muted-foreground">
          What these models are for, what they aren&apos;t for, and how to read
          their numbers.
        </p>
      </header>

      <article className="rounded-xl border border-danger/40 bg-danger/5 p-4">
        <h4 className="text-sm font-semibold text-danger">Out of scope</h4>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-foreground">
          <li>
            <strong>Do not use this dashboard as the sole basis for production
              triage decisions.</strong> It is a research and educational tool;
            an EDR or sandbox is the load-bearing control.
          </li>
          <li>
            Scope is static analysis of Windows PE files only. macOS, Linux ELF,
            Android, scripts, and document-borne malware are not covered.
          </li>
          <li>
            Models trained on a fixed dataset and time window. Concept drift
            against current threat actor TTPs is not measured here.
          </li>
        </ul>
      </article>

      <article className="rounded-xl border border-border bg-surface p-4">
        <h4 className="text-sm font-semibold">Intended use</h4>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-foreground">
          <li>
            Reproducing the published paper&apos;s findings on arbitrary
            user-supplied PE samples.
          </li>
          <li>
            Teaching how feature-level explanations (SHAP) and adversarial
            perturbation interact with tree-based malware classifiers.
          </li>
          <li>
            Comparative evaluation of multiple model families on the same
            input — the disagreement view is the explicit demo.
          </li>
        </ul>
      </article>

      <article className="rounded-xl border border-border bg-surface p-4">
        <h4 className="text-sm font-semibold">Known limitations</h4>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-foreground">
          <li>
            Header-only feature set — packed binaries that obscure the PE
            header will degrade prediction quality.
          </li>
          <li>
            Tree-SHAP attributions are <em>local explanations</em>, not causal
            statements. They tell you what shifted the model&apos;s output, not
            why a feature is malicious in absolute terms.
          </li>
          <li>
            Calibration: the manifest does not yet ship reliability bins, so
            the confidence numbers are model-reported and not externally
            recalibrated. A reliability diagram is a planned addition.
          </li>
          {models.mock_mode && (
            <li className="text-warn">
              <strong>Mock mode is on.</strong> Predictions and SHAP values are
              produced by deterministic placeholder predictors so the dashboard
              demos before the trained pickles are loaded. The numbers below
              are not measured performance.
            </li>
          )}
        </ul>
      </article>

      <div className="grid gap-3 md:grid-cols-2">
        {models.models.map((m) => (
          <ModelCardItem key={m.id} model={m} />
        ))}
      </div>
    </section>
  );
}

function ModelCardItem({ model }: { model: ModelInfo }) {
  const metricEntries = Object.entries(model.metrics ?? {});
  return (
    <article className="rounded-xl border border-border bg-surface p-4">
      <header className="mb-2 flex items-center justify-between">
        <div>
          <h4 className="font-mono text-sm">{model.id}</h4>
          <p className="text-xs text-muted-foreground">{model.family}</p>
        </div>
        {model.is_mock && (
          <span className="rounded bg-warn/20 px-1.5 py-0.5 text-xs text-warn">mock</span>
        )}
      </header>

      <dl className="space-y-1 text-xs">
        {model.trained_at && (
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Trained</dt>
            <dd className="font-mono">{model.trained_at}</dd>
          </div>
        )}
        {model.training_dataset && (
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Dataset</dt>
            <dd className="font-mono">{model.training_dataset}</dd>
          </div>
        )}
        {metricEntries.length > 0 && (
          <div className="pt-1">
            <dt className="text-muted-foreground">Metrics</dt>
            <dd className="mt-1 grid grid-cols-3 gap-2">
              {metricEntries.map(([k, v]) => (
                <div key={k} className="rounded bg-ink/40 px-2 py-1">
                  <div className="text-[10px] uppercase text-muted-foreground">{k}</div>
                  <div className="font-mono text-sm">
                    {Number.isFinite(v) ? v.toFixed(3) : "—"}
                  </div>
                </div>
              ))}
            </dd>
          </div>
        )}
      </dl>

      {model.paper_citation && (
        <p className="mt-3 text-xs text-muted-foreground">
          <span className="text-muted-foreground">Citation:</span> {model.paper_citation}
        </p>
      )}
      {model.notes && (
        <p className="mt-2 text-xs italic text-muted-foreground">{model.notes}</p>
      )}
    </article>
  );
}
