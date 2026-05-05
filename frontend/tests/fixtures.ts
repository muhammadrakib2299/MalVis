/**
 * Shared test fixtures. Mirrors the wire types in src/lib/api.ts at the
 * minimum-fields-needed level — components only read a subset of the
 * FeatureResponse shape, so the fixture stays compact.
 */

import type {
  FeatureResponse,
  ModelPrediction,
  ScanResponse,
} from "@/lib/api";

const baseFeatures: FeatureResponse = {
  schema_version: "0.1.0",
  sha256: "a".repeat(64),
  size_bytes: 4096,
  machine: 0x14c,
  number_of_sections: 1,
  time_date_stamp: 0,
  characteristics: 0x102,
  magic: 0x10b,
  major_linker_version: 14,
  minor_linker_version: 0,
  size_of_code: 1234,
  size_of_initialized_data: 0,
  size_of_uninitialized_data: 0,
  address_of_entry_point: 0x1000,
  image_base: 0x400000,
  section_alignment: 0x1000,
  file_alignment: 0x200,
  subsystem: 3,
  dll_characteristics: 0x8160,
  size_of_image: 0x2000,
  size_of_headers: 0x200,
  imported_dll_count: 5,
  imported_function_count: 42,
  has_signature: false,
  has_resources: false,
  has_debug: false,
  has_tls: false,
  sections: [
    { name: ".text", virtual_size: 64, raw_size: 64, entropy: 0.1, characteristics: 0x60000020 },
  ],
  imported_dlls: [],
};

export function makePrediction(
  overrides: Partial<ModelPrediction> = {},
): ModelPrediction {
  return {
    model_name: "rf-v1",
    label: "benign",
    confidence: 0.92,
    latency_ms: 1.5,
    ...overrides,
  };
}

export function makeScan(
  overrides: Partial<ScanResponse> = {},
): ScanResponse {
  return {
    sha256: baseFeatures.sha256,
    features: baseFeatures,
    predictions: [makePrediction()],
    ...overrides,
  };
}
