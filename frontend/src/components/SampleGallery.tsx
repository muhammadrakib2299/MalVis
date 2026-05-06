"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
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
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        Loading samples…
      </div>
    );
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
    <div className="grid gap-3 md:grid-cols-3">
      {samples.map((sample) => {
        const busy = busyId === sample.id;
        return (
          <button
            key={sample.id}
            type="button"
            onClick={() => handleClick(sample)}
            disabled={disabled || Boolean(busyId)}
            // Match Card visuals (border + bg + shadow) so the gallery
            // tiles read as clickable cards. Hover lifts the border to
            // the primary colour as a click-affordance hint.
            className={cn(
              "rounded-lg border border-border bg-card p-3 text-left text-card-foreground shadow-sm transition-colors",
              "hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-medium">{sample.label}</h4>
              {busy && (
                <Badge variant="secondary" className="gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                  scanning
                </Badge>
              )}
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
  );
}
