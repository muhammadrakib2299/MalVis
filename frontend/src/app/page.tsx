"use client";

import { useEffect, useState } from "react";
import { ApiError, ModelsResponse, ScanResponse, getModels } from "@/lib/api";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { ResultsPanel } from "@/components/ResultsPanel";
import { UploadZone } from "@/components/UploadZone";

interface ScanState {
  result: ScanResponse;
  file: File;
}

export default function Home() {
  const [scan, setScan] = useState<ScanState | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // /models is loaded once at page open so the mock-mode banner is honest
  // from the very first render. A failure here is non-fatal — we just show
  // a small error and let the user attempt a scan anyway.
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

      {scan && (
        <div className="mt-10 space-y-10">
          <ResultsPanel result={scan.result} mockMode={models?.mock_mode ?? null} />
          <ExplanationPanel file={scan.file} expectedSha256={scan.result.sha256} />
        </div>
      )}
    </main>
  );
}
