"use client";

import { useEffect, useState } from "react";
import { ApiError, ModelsResponse, ScanResponse, getModels } from "@/lib/api";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { ModelCardPanel } from "@/components/ModelCardPanel";
import { PerturbationSimulator } from "@/components/PerturbationSimulator";
import { ResultsPanel } from "@/components/ResultsPanel";
import { SampleGallery } from "@/components/SampleGallery";
import { UploadZone } from "@/components/UploadZone";

interface ScanState {
  result: ScanResponse;
  /**
   * Set when the scan came from a user upload (we still have the bytes).
   * Null when the scan came from the sample gallery — the bytes live on
   * the backend and we deliberately don't ship them client-side, so
   * /explain (which re-uploads) is unavailable for sample-driven scans.
   */
  file: File | null;
}

export default function Home() {
  const [scan, setScan] = useState<ScanState | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getModels(ctrl.signal)
      .then(setModels)
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setModelsError(
          err instanceof ApiError ? err.detail : "Could not reach the backend.",
        );
      });
    return () => ctrl.abort();
  }, []);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <header className="mb-10">
        <h1 className="text-3xl font-semibold tracking-tight">MalVis</h1>
        <p className="mt-2 text-zinc-400">
          Explainable malware detection for Windows PE files. Scan a binary,
          compare per-model predictions, and inspect the features that drove
          each verdict.
        </p>
        <p className="mt-2 text-xs text-warn">
          Research and educational tool — not a substitute for production
          triage or endpoint protection. See the model card below.
        </p>
        {models && (
          <p className="mt-3 text-xs text-zinc-500">
            Schema {models.feature_schema_version} · {models.feature_count} features ·{" "}
            {models.models.length} models loaded
            {models.mock_mode && (
              <span className="ml-2 rounded bg-warn/20 px-1.5 py-0.5 text-warn">
                mock mode
              </span>
            )}
          </p>
        )}
        {modelsError && (
          <p className="mt-3 text-xs text-danger">Backend unreachable: {modelsError}</p>
        )}
      </header>

      <UploadZone onResult={(result, file) => setScan({ result, file })} />

      <div className="mt-6">
        <SampleGallery onSelect={(result) => setScan({ result, file: null })} />
      </div>

      {scan && (
        <div className="mt-10 space-y-10">
          <ResultsPanel result={scan.result} mockMode={models?.mock_mode ?? null} />
          {scan.file && (
            <ExplanationPanel
              file={scan.file}
              expectedSha256={scan.result.sha256}
            />
          )}
          <PerturbationSimulator baseline={scan.result.features} />
        </div>
      )}

      {models && (
        <div className="mt-12 border-t border-border pt-10">
          <ModelCardPanel models={models} />
        </div>
      )}
    </main>
  );
}
