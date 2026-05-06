"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  SampleSummary,
  ScanResponse,
  getSamples,
  postSampleScan,
} from "@/lib/api";

interface SampleGalleryProps {
  /** Receives the scan result when a sample card is clicked. */
  onSelect: (result: ScanResponse, sample: SampleSummary) => void;
  /** Disable interactions while a scan is already in flight. */
  disabled?: boolean;
}

export function SampleGallery({ onSelect, disabled }: SampleGalleryProps) {
  const [samples, setSamples] = useState<SampleSummary[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getSamples(ctrl.signal)
      .then((response) => setSamples(response.samples))
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setError(err instanceof ApiError ? err.detail : "Could not load samples.");
      });
    return () => ctrl.abort();
  }, []);

  if (error) {
    return (
      <p className="text-xs text-muted-foreground">
        Sample gallery unavailable: <span className="text-danger">{error}</span>
      </p>
    );
  }

  if (samples === null) {
    return <p className="text-xs text-muted-foreground">Loading samples…</p>;
  }

  const handleClick = async (sample: SampleSummary) => {
    if (disabled || busyId) return;
    setBusyId(sample.id);
    setError(null);
    try {
      const result = await postSampleScan(sample.id);
      onSelect(result, sample);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Sample scan failed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <p className="mb-3 text-xs text-muted-foreground">
        No PE on hand? Try one of these synthetic samples — built on demand,
        nothing stored on disk.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        {samples.map((sample) => {
          const busy = busyId === sample.id;
          return (
            <button
              key={sample.id}
              type="button"
              onClick={() => handleClick(sample)}
              disabled={disabled || Boolean(busyId)}
              className="rounded-xl border border-border bg-surface p-3 text-left transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">{sample.label}</h4>
                {busy && <span className="text-xs text-accent">scanning…</span>}
              </div>
              <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                {sample.description}
              </p>
              <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">
                sha256: {sample.sha256.slice(0, 16)}…
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
