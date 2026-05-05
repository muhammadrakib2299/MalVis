# ADR-001: PE feature set and schema version

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** Md. Rakibul Hasan
- **Supersedes:** —
- **Superseded by:** —

## Context

MalVis runs predictions across multiple ML models trained on a fixed feature schema derived from Windows PE files. A trained Random Forest or XGBoost classifier is *physically married* to a specific feature ordering: changing the order, adding a feature, removing one, or even renaming one silently invalidates every prediction the model has ever made.

We need a feature set that is:

1. **Cheap to extract.** Static parsing only — `pefile` reads the PE header and does not execute the binary. No disassembly, no dynamic analysis, no LIEF (yet — its multi-format support could land in a v2 schema).
2. **Stable under hostile input.** A malformed PE crashing the extractor must not corrupt feature output. Aggregate features over sections must degrade gracefully when individual sections are unparseable.
3. **Wide enough to differentiate.** The published paper trains on a richer schema; a v1 dashboard need not match it byte-for-byte but must capture the structural signal.
4. **Pinnable.** A future change to the schema must be detectable at load time (ideally as a startup error against an artifact trained on the old schema), not as silently-wrong predictions in production.

The v1 schema was decided after a survey of features used by the paper, EMBER, and similar header-based malware classifiers, weighted by `pefile` parser stability and frontend interpretability (a feature with no obvious semantic gloss won't help a SHAP waterfall be readable).

## Decision

The feature schema is encoded in two coupled constants in `backend/app/services/pe_features.py`:

```python
FEATURE_SCHEMA_VERSION = "0.1.0"
FEATURE_VECTOR_ORDER: tuple[str, ...] = (
    "size_bytes", "machine", "number_of_sections", "time_date_stamp",
    "characteristics", "magic", "major_linker_version", "minor_linker_version",
    "size_of_code", "size_of_initialized_data", "size_of_uninitialized_data",
    "address_of_entry_point", "image_base", "section_alignment", "file_alignment",
    "subsystem", "dll_characteristics", "size_of_image", "size_of_headers",
    "imported_dll_count", "imported_function_count",
    "has_signature", "has_resources", "has_debug", "has_tls",
    "max_section_entropy", "mean_section_entropy", "total_section_raw_size",
)
```

### Categories

- **File-level scalars** — `size_bytes`, `machine`, `number_of_sections`, `time_date_stamp`, `characteristics`. Cheap, present in every PE.
- **Optional header fields** — `magic`, linker versions, code/data sizes, entry point, image base, alignments, subsystem, DLL characteristics, image/headers sizes. Direct read; no derivation.
- **Import counts** — `imported_dll_count`, `imported_function_count`. Aggregates over the parsed import directory; bounded (`_MAX_IMPORTED_DLLS = 64`) so a hostile PE can't make extraction unbounded.
- **Boolean directory flags** — `has_signature`, `has_resources`, `has_debug`, `has_tls`. Encoded as 0/1 in the vector. Useful for the perturbation simulator's toggle UI.
- **Section aggregates** — `max_section_entropy`, `mean_section_entropy`, `total_section_raw_size`. Per-section data varies in length between PEs; aggregates produce a fixed-shape signal the model can consume without padding.

### Excluded (deliberately, for v1)

- **Per-section vectors.** Variable shape; would require either truncation/padding or a recurrent model. Aggregates capture enough signal for the dashboard demo.
- **Resource directory contents.** Recursing into resources broadens the parser's blast radius; the boolean `has_resources` is enough for v1.
- **Imphash, ssdeep, full hashes.** Would be useful but they're not in the paper's reported schema and they require separate libraries beyond `pefile`.
- **Disassembly-derived features.** Out of scope — static disassembly is its own surface.
- **String n-grams.** High-cardinality, embedding required, not implementable as flat scalars.

### Schema-version-as-contract

`FEATURE_SCHEMA_VERSION` is the wire contract:

- The `FeatureResponse` Pydantic schema includes it on every `/scan` and `/explain` response.
- `MANIFEST.json` may include `feature_schema_version`. The model registry (`app/services/model_registry.py::_load_real`) refuses to load any pickle whose manifest declares a different version than the runtime constant.
- The frontend (`/models`) surfaces `feature_schema_version` and `feature_count` so the UI never silently renders against a mismatched schema.

The version is bumped whenever any of the following changes:

- A name in `FEATURE_VECTOR_ORDER` is added, removed, renamed, or reordered.
- An aggregate's computation changes (e.g., switching `mean_section_entropy` to median).
- A scalar's units change (e.g., `size_bytes` to KB).

A schema version bump is a *deploy event*. Old artifacts must be retrained or re-pinned before the new version reaches production.

## Consequences

### Positive

- **Predictions are auditable.** A `FeatureResponse` payload + the schema version are enough to re-derive the vector that was fed to the model.
- **Mismatched artifacts fail loudly.** A schema bump that lands without re-pinned manifests aborts at load time, not in production.
- **Frontend is decoupled from compile-time schema.** `/models` exposes `feature_order`, so a renamed feature doesn't require a synchronized frontend deploy as long as the *count* stays the same. (A count change is treated as a major bump.)
- **Aggregate degradation.** A PE with corrupt sections still produces a defined vector — `max_section_entropy = 0`, `total_section_raw_size = 0` — rather than a parse error.

### Negative

- **Truncated information.** Aggregating sections collapses positional signal. A sophisticated packer that hides high-entropy data in a small section may evade detection that per-section features would catch. Documented as a known limitation in the model card.
- **No imphash.** Some malware families are most cleanly identified by import-table hashes; v1 doesn't surface them. A v2 schema bump can add `imphash` once we're willing to pin a separate hash library and bump everyone's manifest.
- **Schema bumps are heavy.** Even a single rename forces every artifact through a rebuild + remanifest cycle. We accept the friction in exchange for the failure-mode guarantee.

### Neutral / monitor

- The `_MAX_SECTIONS = 16` and `_MAX_IMPORTED_DLLS = 64` truncation caps preserve `number_of_sections` and `imported_dll_count` as features even when the full data is truncated — so truncation never silently changes the vector. If real-world PEs routinely exceed these caps, raise the caps and bump the schema (the cap is *not* part of the version, but a behavior change is).

## Alternatives considered

- **Match the paper's schema exactly (v1 = paper-v1).** Rejected for v1 because the paper's schema includes features that require LIEF or a custom parser — out of scope for the dashboard's first ship. Planned for the schema-bump-to-v0.2 once the paper artifacts are available for cross-reference.
- **Per-section variable-length vectors with a recurrent model.** Rejected as premature — a tree classifier on flat aggregates is what the paper benchmarks; introducing a new model family is a research project, not a v1 dashboard task.
- **Auto-derive `FEATURE_VECTOR_ORDER` from the dataclass fields by reflection.** Rejected because the *order* is the contract; reflection would make a field reorder silently change the vector. The explicit tuple is what guarantees the pinned ordering.

## References

- `backend/app/services/pe_features.py` — `FEATURE_VECTOR_ORDER`, `FEATURE_SCHEMA_VERSION`, `PEFeatures.to_vector()`.
- `backend/app/services/model_registry.py` — `_load_real` schema-version check.
- `backend/app/routers/meta.py` — `/models` endpoint exposing the schema to the frontend.
- `lessons.md` Step 4, Step 5 — context for the original schema introduction and the registry pinning.
