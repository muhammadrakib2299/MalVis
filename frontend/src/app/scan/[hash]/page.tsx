"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ExplanationFromHash } from "@/components/ExplanationFromHash";
import { ModelCardPanel } from "@/components/ModelCardPanel";
import { PerturbationSimulator } from "@/components/PerturbationSimulator";
import { ResultsPanel } from "@/components/ResultsPanel";
import { SiteNav } from "@/components/site-nav";
import {
  ApiError,
  ModelsResponse,
  ScanResponse,
  getModels,
  getScanByHash,
} from "@/lib/api";

interface ScanPermalinkPageProps {
  params: { hash: string };
}

/**
 * Permalink view for a previously-scanned file.
 *
 * Renders:
 *   - File summary + verdict table (ResultsPanel)
 *   - SHAP waterfall *if* the hash matches a gallery sample
 *     (sample bytes are reconstructible — see ADR-001 / Step 14)
 *   - Perturbation simulator (works on the cached feature vector)
 *   - Model card panel
 *
 * `ExplanationFromHash` silently hides on 404, which is the expected
 * outcome for user-upload permalinks: the bytes were never retained,
 * so SHAP can't be reconstructed. Sample permalinks get the waterfall
 * for free because samples are deterministically rebuildable.
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
    <div className="min-h-screen bg-background">
      <SiteNav />

      <main className="mx-auto max-w-6xl px-6 py-10 md:py-12">
        <header className="mb-8 space-y-3">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Back to scanner
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Shared scan result
          </h1>
          <p className="truncate font-mono text-xs text-muted-foreground">
            sha256: {params.hash}
          </p>
        </header>

        {busy && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading…
          </p>
        )}

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
            <ExplanationFromHash sha256={scan.sha256} />
            <PerturbationSimulator baseline={scan.features} />
          </div>
        )}

        {models && (
          <section className="mt-12 border-t border-border pt-10">
            <ModelCardPanel models={models} />
          </section>
        )}
      </main>
    </div>
  );
}
