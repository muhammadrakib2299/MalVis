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

export const API_BASE_URL = API_BASE;
