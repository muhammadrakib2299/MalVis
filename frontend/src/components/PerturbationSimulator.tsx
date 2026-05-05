"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  FeatureResponse,
  PerturbResponse,
  PerturbationSpec,
  PredictionDelta,
  postPerturb,
} from "@/lib/api";

interface PerturbationSimulatorProps {
  baseline: FeatureResponse;
}

/**
 * Curated subset of features exposed as sliders/toggles.
 *
 * The full feature vector has ~28 entries; surfacing all of them as
 * controls would drown the user in noise. The picks below are the most
 * *demo-able* — features whose perturbation visibly moves the verdict
 * for typical malware vs. benign distributions, and features that map
 * cleanly to a slider-or-toggle UI control.
 *
 * Adding more controls is cheap: append to this list. The perturbation
 * service validates names against `FEATURE_VECTOR_ORDER` server-side, so
 * a typo here surfaces as a 422 rather than silent garbage.
 */
type SliderControl = {
  kind: "slider";
  feature: string;
  label: string;
  min: number;
  max: number;
  step: number;
  /** What the slider reads from the baseline `FeatureResponse`. */
  read: (f: FeatureResponse) => number;
};

type ToggleControl = {
  kind: "toggle";
  feature: string;
  label: string;
  read: (f: FeatureResponse) => boolean;
};

type Control = SliderControl | ToggleControl;

const CONTROLS: readonly Control[] = [
  {
    kind: "slider",
    feature: "imported_dll_count",
    label: "Imported DLLs",
    min: 0,
    max: 200,
    step: 1,
    read: (f) => f.imported_dll_count,
  },
  {
    kind: "slider",
    feature: "imported_function_count",
    label: "Imported functions",
    min: 0,
    max: 2000,
    step: 1,
    read: (f) => f.imported_function_count,
  },
  {
    kind: "slider",
    feature: "max_section_entropy",
    label: "Max section entropy",
    min: 0,
    max: 8,
    step: 0.05,
    // The aggregate is computed server-side from sections; baseline UI
    // value of 0 is fine — the slider drives an absolute "set".
    read: () => 0,
  },
  {
    kind: "slider",
    feature: "mean_section_entropy",
    label: "Mean section entropy",
    min: 0,
    max: 8,
    step: 0.05,
    read: () => 0,
  },
  {
    kind: "slider",
    feature: "size_of_code",
    label: "Size of code (bytes)",
    min: 0,
    max: 4_000_000,
    step: 1024,
    read: (f) => f.size_of_code,
  },
  { kind: "toggle", feature: "has_signature", label: "Authenticode signature", read: (f) => f.has_signature },
  { kind: "toggle", feature: "has_resources", label: "Has resources", read: (f) => f.has_resources },
  { kind: "toggle", feature: "has_debug", label: "Has debug info", read: (f) => f.has_debug },
  { kind: "toggle", feature: "has_tls", label: "Has TLS callbacks", read: (f) => f.has_tls },
];

type ControlState = Record<string, number | boolean>;

function initialState(baseline: FeatureResponse): ControlState {
  const state: ControlState = {};
  for (const c of CONTROLS) {
    state[c.feature] = c.read(baseline);
  }
  return state;
}

function specsFor(state: ControlState, baseline: FeatureResponse): PerturbationSpec[] {
  // Only emit a perturbation when the user has moved the control off its
  // baseline. An empty `applied` list is a perfectly valid request — the
  // backend just returns baseline = perturbed and the UI shows zero deltas.
  const out: PerturbationSpec[] = [];
  for (const c of CONTROLS) {
    const current = state[c.feature];
    if (c.kind === "slider") {
      const baselineValue = c.read(baseline);
      if (current !== baselineValue) {
        out.push({ feature: c.feature, op: "set", value: Number(current) });
      }
    } else {
      const baselineValue = c.read(baseline);
      if (current !== baselineValue) {
        // "set" on bool features is the canonical move; "toggle" is an
        // alias the backend offers, but "set 0/1" produces a deterministic
        // result regardless of how many times the user flips the switch.
        out.push({ feature: c.feature, op: "set", value: current ? 1 : 0 });
      }
    }
  }
  return out;
}

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString();
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}

export function PerturbationSimulator({ baseline }: PerturbationSimulatorProps) {
  const [state, setState] = useState<ControlState>(() => initialState(baseline));
  const [response, setResponse] = useState<PerturbResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Reset whenever the baseline changes (i.e. the user uploaded a new file).
  useEffect(() => {
    setState(initialState(baseline));
    setResponse(null);
  }, [baseline]);

  // Debounced refetch on any control change. AbortController + ref so an
  // in-flight request from a stale slider position doesn't overwrite the
  // current one if the user keeps dragging.
  const inflight = useRef<AbortController | null>(null);
  const specs = useMemo(() => specsFor(state, baseline), [state, baseline]);

  useEffect(() => {
    const handle = setTimeout(() => {
      inflight.current?.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      setBusy(true);
      setError(null);
      postPerturb(
        { features: baseline, perturbations: specs },
        ctrl.signal,
      )
        .then((r) => {
          if (!ctrl.signal.aborted) setResponse(r);
        })
        .catch((err) => {
          if (ctrl.signal.aborted) return;
          setError(err instanceof ApiError ? err.detail : "Perturbation request failed.");
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setBusy(false);
        });
    }, 200); // ms — smooth slider drags without flooding the backend

    return () => clearTimeout(handle);
  }, [baseline, specs]);

  const reset = () => setState(initialState(baseline));

  return (
    <section className="rounded-xl border border-border bg-surface p-4">
      <header className="mb-4 flex items-baseline justify-between">
        <div>
          <h3 className="text-sm uppercase tracking-wide text-zinc-400">
            Perturb the features
          </h3>
          <p className="text-xs text-zinc-500">
            Adjust values below and watch each model&apos;s verdict update. A flipped
            verdict is highlighted; this is what an attacker would aim for.
          </p>
        </div>
        <button
          type="button"
          onClick={reset}
          className="rounded-md border border-border px-2 py-1 text-xs text-zinc-300 hover:border-accent hover:text-accent"
        >
          Reset
        </button>
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-3">
          {CONTROLS.map((c) =>
            c.kind === "slider" ? (
              <SliderRow
                key={c.feature}
                control={c}
                value={Number(state[c.feature])}
                onChange={(v) => setState((s) => ({ ...s, [c.feature]: v }))}
              />
            ) : (
              <ToggleRow
                key={c.feature}
                control={c}
                value={Boolean(state[c.feature])}
                onChange={(v) => setState((s) => ({ ...s, [c.feature]: v }))}
              />
            ),
          )}
        </div>

        <div className="space-y-3">
          <header className="flex items-center justify-between text-xs">
            <span className="uppercase tracking-wide text-zinc-500">Delta</span>
            <span className="text-zinc-500">{busy ? "Updating…" : `${specs.length} perturbed`}</span>
          </header>

          {error && (
            <p
              role="alert"
              className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
            >
              {error}
            </p>
          )}

          {response?.deltas.map((d) => (
            <DeltaCard key={d.model_name} delta={d} />
          )) ?? (
            <p className="text-xs text-zinc-500">No predictions yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}

function SliderRow({
  control,
  value,
  onChange,
}: {
  control: SliderControl;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-xs">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-zinc-300">{control.label}</span>
        <span className="font-mono text-zinc-500">{formatNumber(value)}</span>
      </div>
      <input
        type="range"
        min={control.min}
        max={control.max}
        step={control.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
    </label>
  );
}

function ToggleRow({
  control,
  value,
  onChange,
}: {
  control: ToggleControl;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between text-xs">
      <span className="text-zinc-300">{control.label}</span>
      <span className="relative inline-flex h-5 w-9 items-center">
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
        />
        <span className="block h-5 w-9 rounded-full bg-ink/80 transition-colors peer-checked:bg-accent" />
        <span className="absolute left-0.5 h-4 w-4 translate-x-0 rounded-full bg-zinc-300 transition-transform peer-checked:translate-x-4" />
      </span>
    </label>
  );
}

function DeltaCard({ delta }: { delta: PredictionDelta }) {
  const flipped = delta.label_flipped;
  return (
    <div
      className={[
        "rounded-md border p-3 text-xs",
        flipped ? "border-warn bg-warn/10" : "border-border",
      ].join(" ")}
    >
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-mono">{delta.model_name}</span>
        {flipped && <span className="text-xs font-medium text-warn">flipped</span>}
      </div>
      <div className="flex items-center gap-2 text-zinc-400">
        <span className={delta.baseline_label === "malicious" ? "text-danger" : "text-ok"}>
          {delta.baseline_label}
        </span>
        <span aria-hidden>→</span>
        <span className={delta.perturbed_label === "malicious" ? "text-danger" : "text-ok"}>
          {delta.perturbed_label}
        </span>
        <span className="ml-auto font-mono text-zinc-500">
          Δconf {delta.confidence_delta >= 0 ? "+" : ""}
          {(delta.confidence_delta * 100).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}
