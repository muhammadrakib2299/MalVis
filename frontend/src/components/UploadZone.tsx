"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError, ScanResponse, postScan } from "@/lib/api";

const MAX_BYTES = 10 * 1024 * 1024; // mirror backend cap; reject earlier

interface UploadZoneProps {
  onResult: (result: ScanResponse, file: File) => void;
  disabled?: boolean;
}

export function UploadZone({ onResult, disabled }: UploadZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Magic-byte pre-check: read the first two bytes client-side and refuse
   * anything that isn't `MZ`. The backend enforces the same rule, but
   * doing it here saves a round-trip on obvious mistakes (PNG, ZIP, etc.)
   * and gives instant feedback in the UI.
   */
  const validatePeFile = useCallback(async (file: File): Promise<string | null> => {
    if (file.size === 0) return "File is empty.";
    if (file.size > MAX_BYTES) {
      return `File exceeds the ${MAX_BYTES / (1024 * 1024)} MB limit.`;
    }
    const head = new Uint8Array(await file.slice(0, 2).arrayBuffer());
    if (head.length < 2 || head[0] !== 0x4d || head[1] !== 0x5a) {
      return "Not a Windows PE file (missing MZ magic bytes).";
    }
    return null;
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      const validationError = await validatePeFile(file);
      if (validationError) {
        setError(validationError);
        return;
      }

      setBusy(true);
      try {
        const result = await postScan(file);
        onResult(result, file);
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError(err instanceof Error ? err.message : "Upload failed.");
        }
      } finally {
        setBusy(false);
      }
    },
    [onResult, validatePeFile],
  );

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragActive(false);
      if (disabled || busy) return;
      const file = event.dataTransfer.files?.[0];
      if (file) void handleFile(file);
    },
    [busy, disabled, handleFile],
  );

  const onPick = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) void handleFile(file);
      // Reset so picking the same file twice still triggers onChange.
      event.target.value = "";
    },
    [handleFile],
  );

  const isDisabled = disabled || busy;

  return (
    <div className="w-full">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!isDisabled) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        className={[
          "rounded-2xl border-2 border-dashed p-10 transition-colors",
          dragActive ? "border-accent bg-surface" : "border-border",
          isDisabled ? "opacity-60" : "hover:border-accent",
        ].join(" ")}
        aria-busy={busy}
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-lg font-medium">Drop a Windows PE file here</p>
          <p className="text-sm text-zinc-400">
            10 MB max. We never persist your binary; only the SHA-256 is logged.
          </p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isDisabled}
            className="mt-2 rounded-lg bg-accent px-4 py-2 font-medium text-ink disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? "Scanning…" : "Choose a file"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".exe,.dll,.sys,application/vnd.microsoft.portable-executable,application/octet-stream"
            onChange={onPick}
            className="hidden"
          />
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
    </div>
  );
}
