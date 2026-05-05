/**
 * Typed client for the MalVis backend.
 *
 * Types here mirror the Pydantic schemas in backend/app/schemas/*.py.
 * If a schema changes server-side, this file is the *one* place to update —
 * components import from `@/lib/api` and don't reach into raw fetch elsewhere.
 *
 * Schema-version pinning lives on the backend (FEATURE_SCHEMA_VERSION); the
 * frontend reads `feature_schema_version` from /models and surfaces it,
 * so a server upgrade never silently mismatches a cached UI.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// ---------- Wire types ----------------------------------------------------

export interface SectionResponse {
  name: string;
  virtual_size: number;
  raw_size: number;
  entropy: number;
  characteristics: number;
}

export interface FeatureResponse {
  schema_version: string;
  sha256: string;
  size_bytes: number;
  machine: number;
  number_of_sections: number;
  time_date_stamp: number;
  characteristics: number;
  magic: number;
  major_linker_version: number;
  minor_linker_version: number;
  size_of_code: number;
  size_of_initialized_data: number;
  size_of_uninitialized_data: number;
  address_of_entry_point: number;
  image_base: number;
  section_alignment: number;
  file_alignment: number;
  subsystem: number;
  dll_characteristics: number;
  size_of_image: number;
  size_of_headers: number;
  imported_dll_count: number;
  imported_function_count: number;
  has_signature: boolean;
  has_resources: boolean;
  has_debug: boolean;
  has_tls: boolean;
  sections: SectionResponse[];
  imported_dlls: string[];
}

export interface ModelPrediction {
  model_name: string;
  label: "malicious" | "benign";
  confidence: number;
  latency_ms: number;
}

export interface ScanResponse {
  sha256: string;
  features: FeatureResponse;
  predictions: ModelPrediction[];
}

export interface ModelInfo {
  id: string;
  family: string;
  is_mock: boolean;
  trained_at: string;
  training_dataset: string;
  metrics: Record<string, number>;
  paper_citation: string;
  notes: string;
}

export interface ModelsResponse {
  feature_schema_version: string;
  feature_count: number;
  feature_order: string[];
  mock_mode: boolean;
  models: ModelInfo[];
}

export interface ReadyResponse {
  status: "ready";
  mock_mode: boolean;
  model_count: number;
  feature_schema_version: string;
}

export interface FeatureContribution {
  feature: string;
  value: number;
  shap_value: number;
}

export interface ModelExplanation {
  model_name: string;
  is_mock: boolean;
  label: "malicious" | "benign";
  confidence: number;
  base_value: number;
  contributions: FeatureContribution[];
}

export interface ExplainResponse {
  sha256: string;
  feature_schema_version: string;
  explanations: ModelExplanation[];
}

// ---------- Error envelope ------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`[${status}] ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Body wasn't JSON — keep statusText.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ---------- Endpoint wrappers --------------------------------------------

export async function postScan(file: File, signal?: AbortSignal): Promise<ScanResponse> {
  const form = new FormData();
  form.append("upload", file, file.name);
  const response = await fetch(`${API_BASE}/scan`, {
    method: "POST",
    body: form,
    signal,
  });
  return unwrap<ScanResponse>(response);
}

export async function getModels(signal?: AbortSignal): Promise<ModelsResponse> {
  const response = await fetch(`${API_BASE}/models`, { signal });
  return unwrap<ModelsResponse>(response);
}

export async function getReady(signal?: AbortSignal): Promise<ReadyResponse> {
  const response = await fetch(`${API_BASE}/ready`, { signal });
  return unwrap<ReadyResponse>(response);
}

export interface PostExplainOptions {
  /** Restrict the explanation to a single model. Omit for all models. */
  modelName?: string;
  /** Top-N contributions to return (1–64). Backend default is 12. */
  topN?: number;
  signal?: AbortSignal;
}

export type PerturbOp = "set" | "delta" | "scale" | "toggle";

export interface PerturbationSpec {
  feature: string;
  op: PerturbOp;
  value?: number;
}

export interface AppliedPerturbation {
  feature: string;
  op: PerturbOp;
  before: number;
  after: number;
}

export interface PredictionDelta {
  model_name: string;
  baseline_label: "malicious" | "benign";
  perturbed_label: "malicious" | "benign";
  label_flipped: boolean;
  confidence_delta: number;
}

export interface PerturbRequest {
  features?: FeatureResponse;
  feature_vector?: number[];
  perturbations: PerturbationSpec[];
  model_name?: string;
}

export interface PerturbResponse {
  sha256: string | null;
  feature_schema_version: string;
  applied: AppliedPerturbation[];
  baseline_predictions: ModelPrediction[];
  perturbed_predictions: ModelPrediction[];
  deltas: PredictionDelta[];
}

export async function postPerturb(
  body: PerturbRequest,
  signal?: AbortSignal,
): Promise<PerturbResponse> {
  const response = await fetch(`${API_BASE}/perturb`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return unwrap<PerturbResponse>(response);
}

export async function postExplain(
  file: File,
  { modelName, topN, signal }: PostExplainOptions = {},
): Promise<ExplainResponse> {
  const form = new FormData();
  form.append("upload", file, file.name);
  if (modelName) form.append("model_name", modelName);
  if (topN !== undefined) form.append("top_n", String(topN));
  const response = await fetch(`${API_BASE}/explain`, {
    method: "POST",
    body: form,
    signal,
  });
  return unwrap<ExplainResponse>(response);
}

export const API_BASE_URL = API_BASE;
