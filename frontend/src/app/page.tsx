"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { ExplanationPanel } from "@/components/ExplanationPanel";
import { ModelCardPanel } from "@/components/ModelCardPanel";
import { PerturbationSimulator } from "@/components/PerturbationSimulator";
import { ResultsPanel } from "@/components/ResultsPanel";
import { SampleGallery } from "@/components/SampleGallery";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { UploadZone } from "@/components/UploadZone";
import { ApiError, ModelsResponse, ScanResponse, getModels } from "@/lib/api";

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
    <div className="min-h-screen bg-background">
      {/* Top nav — kept light so the eye lands on the hero, not the chrome. */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <a href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <ShieldCheck className="h-5 w-5 text-primary" aria-hidden />
            <span>MalVis</span>
          </a>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10 md:py-16">
        {/* Hero. Single column on mobile, two-column on md+: copy + status card. */}
        <section className="grid gap-10 md:grid-cols-[1.4fr_1fr] md:items-start">
          <div className="space-y-5">
            <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-wider">
              Research demo · Windows PE only
            </Badge>
            <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
              Explainable malware detection,{" "}
              <span className="text-primary">live in the browser</span>.
            </h1>
            <p className="max-w-xl text-base text-muted-foreground md:text-lg">
              Upload a Windows PE file or scan a curated sample. Compare per-model
              verdicts, inspect the SHAP features that drove each decision, and
              perturb feature values to watch the prediction shift.
            </p>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <a
                href="#scan"
                className="inline-flex h-10 items-center rounded-md bg-primary px-4 font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Scan a file
              </a>
              <a
                href="#model-card"
                className="inline-flex h-10 items-center rounded-md border border-border px-4 font-medium transition-colors hover:bg-secondary"
              >
                Read the model card
              </a>
            </div>
            <p className="max-w-xl text-xs text-warn">
              Research and educational tool — not a substitute for production
              triage or endpoint protection. Read the model card before
              acting on a verdict.
            </p>
          </div>

          {/* Status card — proves the backend is alive and shows the schema
              the loaded models speak. Replaces the previous one-line
              "Schema X · N features · M models" footnote with a real card. */}
          <Card className="md:mt-2">
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-wide text-muted-foreground">
                Backend status
              </CardTitle>
              <CardDescription>
                {modelsError ? "Disconnected." : models ? "Connected." : "Connecting…"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {modelsError && (
                <p
                  role="alert"
                  className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
                >
                  {modelsError}
                </p>
              )}
              {models && (
                <>
                  <dl className="grid grid-cols-2 gap-3">
                    <div>
                      <dt className="text-xs text-muted-foreground">Schema</dt>
                      <dd className="font-mono text-sm">v{models.feature_schema_version}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Features</dt>
                      <dd className="font-mono text-sm">{models.feature_count}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Models</dt>
                      <dd className="font-mono text-sm">{models.models.length} loaded</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Mode</dt>
                      <dd>
                        {models.mock_mode ? (
                          <Badge variant="warn">mock predictors</Badge>
                        ) : (
                          <Badge variant="ok">real models</Badge>
                        )}
                      </dd>
                    </div>
                  </dl>
                </>
              )}
              {!models && !modelsError && (
                <div className="space-y-2">
                  <div className="h-3 w-3/4 animate-pulse rounded bg-muted" />
                  <div className="h-3 w-1/2 animate-pulse rounded bg-muted" />
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Scan section. Anchored so the hero CTA jumps here. */}
        <section id="scan" className="mt-16 space-y-6 scroll-mt-24">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Scan a binary</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              We never persist your file. Only the SHA-256 is logged.
            </p>
          </div>
          <Card>
            <CardContent className="pt-6">
              <UploadZone onResult={(result, file) => setScan({ result, file })} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Or try a sample</CardTitle>
              <CardDescription>
                Synthetic, hash-pinned samples — built on demand, nothing stored on disk.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SampleGallery onSelect={(result) => setScan({ result, file: null })} />
            </CardContent>
          </Card>
        </section>

        {scan && (
          <section className="mt-16 space-y-10">
            <ResultsPanel result={scan.result} mockMode={models?.mock_mode ?? null} />
            {scan.file && (
              <ExplanationPanel
                file={scan.file}
                expectedSha256={scan.result.sha256}
              />
            )}
            <PerturbationSimulator baseline={scan.result.features} />
          </section>
        )}

        {models && (
          <section id="model-card" className="mt-16 border-t border-border pt-10 scroll-mt-24">
            <ModelCardPanel models={models} />
          </section>
        )}
      </main>

      <footer className="mt-16 border-t border-border py-8">
        <div className="mx-auto max-w-6xl px-6 text-xs text-muted-foreground">
          MalVis — built on the published malware-detection paper. Static analysis only.
          Bring your own threat-intel.
        </div>
      </footer>
    </div>
  );
}
