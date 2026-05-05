"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  ModelsResponse,
  ScanResponse,
  getModels,
  getScanByHash,
} from "@/lib/api";
import { ModelCardPanel } from "@/components/ModelCardPanel";
import { PerturbationSimulator } from "@/components/PerturbationSimulator";
import { ResultsPanel } from "@/components/ResultsPanel";

interface ScanPermalinkPageProps {
  params: { hash: string };
}

/**
 * Permalink view for a previously-scanned file.
 *
 * Renders:
 *   - File summary + verdict table (ResultsPanel)
 *   - Perturbation simulator (works on the cached feature vector)
 *   - Model card panel
 *
 * Does **not** render the SHAP waterfall — explanations require the
 * original PE bytes, and we deliberately don't retain user uploads
 * past the cache TTL (SECURITY.md). Sample-driven permalinks could
 * support explanations because the bytes are reconstructible, but
 * wiring that path is a follow-up step.
 */
export default function ScanPermalinkPage({ params }: ScanPermalinkPageProps) {
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    Promise.all([
      getScanByHash(params.hash, ctrl.signal),
      getModels(ctrl.signal),
    ])
      .then(([scanResponse, modelsResponse]) => {
        setScan(scanResponse);
        setModels(modelsResponse);
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setError(
            "No scan with that SHA-256 is available. Uploads aren't retained past the cache TTL.",
          );
        } else {
          setError(err instanceof ApiError ? err.detail : "Could not load scan.");
        }
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setBusy(false);
      });

    return () => ctrl.abort();
  }, [params.hash]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <header className="mb-8">
        <Link href="/" className="text-xs text-zinc-500 hover:text-accent">
          ← Back to scanner
        </Link>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">
          Shared scan result
        </h1>
        <p className="mt-2 truncate font-mono text-xs text-zinc-500">
          sha256: {params.hash}
        </p>
      </header>

      {busy && <p className="text-sm text-zinc-400">Loading…</p>}

      {error && (
        <div
          role="alert"
          className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      {scan && (
        <div className="space-y-10">
          <ResultsPanel result={scan} mockMode={models?.mock_mode ?? null} />
          <PerturbationSimulator baseline={scan.features} />
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
