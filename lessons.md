# MalVis — Lessons learned

A running log of decisions, surprises, and lessons captured during the build. Each entry is dated and tied to a commit. Future-me reads this when picking the project up after a break, and reviewers/admissions readers see how the work actually unfolded — not just the polished end state.

---

## How to use this file

- One section per build step.
- Lead with the **decision** or **lesson**, then a short **why**.
- Note any pitfall worth warning a future contributor about.
- Keep it honest — this is a learning artifact, not marketing copy.

---

## Step 1 — Repo bootstrap

**Date:** 2026-05-05

**What landed**
- `lessons.md` (this file)
- `.gitignore` covering Python, Node, model artifacts, `.env`, datasets, OS noise
- `pyproject.toml` with ruff + black configured (single source of truth, no duplicate config)
- Folder skeleton matching the README's "Project structure" diagram
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)

**Decisions**
- **Single `pyproject.toml` over `setup.cfg` + `requirements.txt`.** Ruff and black both read pyproject natively; one config file is one less thing to drift out of sync. `requirements.txt` stays for now because Docker layer caching is simpler than `pip install -e .`.
- **Models are gitignored from day one.** `artifacts/` exists in tree but contents are excluded. Pickles will be too large and arguably sensitive; they ship via release assets or a separate model-registry path, not git.
- **`.env*` excluded except `.env.example`.** Standard pattern but worth being explicit — secrets in git is a dragon we never want to fight.

**Lesson**
- The skeleton is dull but it's the most important commit in the repo. Every later phase assumes these paths exist and these conventions hold. Get it right once.

---

## Step 2 — FastAPI shell with `/health`

**Date:** 2026-05-05

**What landed**
- `backend/requirements.txt` with pinned versions across the whole ML + web stack
- `backend/app/config.py` — `pydantic-settings` based config, frozen at import via `lru_cache`
- `backend/app/main.py` — FastAPI app, `/health` liveness probe only (intentionally cheap)
- `backend/Dockerfile` — multi-stage, non-root user (UID 10001), `libgomp1` only at runtime, healthcheck baked in
- `backend/.dockerignore` keeping the build context tight
- `backend/tests/test_health.py` — first pytest, uses `TestClient` (no real network)

**Decisions**
- **`pydantic-settings` over `os.getenv` everywhere.** Type-safe, validates at startup, and `lru_cache` makes "read once" enforceable without globals scattered around.
- **`/health` is intentionally dumb.** No model loads, no DB pings, no disk I/O. Liveness ≠ readiness. A future `/ready` endpoint will gate on the model registry; mixing them now would mean restarts cascade into 503s while models warm up.
- **Multi-stage Dockerfile, runtime stage gets only `libgomp1`.** xgboost wheels need libgomp at import time but nothing else from the build toolchain. Smaller image, smaller attack surface.
- **`--proxy-headers --forwarded-allow-ips=*` in CMD.** When Cloudflare or Caddy fronts the API, `request.client.host` would otherwise be the proxy's IP, breaking per-IP rate limiting. Worth wiring this in before middleware lands.
- **Pinned exact versions.** Pip-with-hashes mode comes later (see `SECURITY.md`); pinning is the floor.

**Pitfall noticed**
- `httpx` and `pytest` are bundled into `requirements.txt` for now (single-file Docker install). When the image gets big, split into `requirements-dev.txt` and use a separate `--target=test` build stage. Don't do it preemptively.

**Lesson**
- Boring scaffolding pays for itself. `/health` looks trivial, but having it green from day one makes Docker healthchecks, deploy gates, and reverse-proxy upstream checks all "just work" later.

---

## Step 3 — Security middleware and upload validation

**Date:** 2026-05-05

**What landed**
- `backend/app/security/limiter.py` — slowapi `Limiter` keyed on real client IP (works because uvicorn runs with `--proxy-headers`)
- `backend/app/security/upload.py` — `read_pe_upload`, `assert_pe_magic`, custom `UploadValidationError`
- `backend/app/main.py` extended with: rate-limit middleware, 429 JSON handler, locked-down CORS (allowlist + GET/POST only)
- `backend/tests/test_security.py` covering accept/reject paths for magic-byte and size enforcement

**Decisions**
- **Rate limiting at the application layer, not just the proxy.** Cloudflare is great but won't be in front of every deployment (local dev, self-hosters). slowapi means the contract holds even when the proxy doesn't. Defense in depth.
- **Cheapest checks first in `read_pe_upload`.** Order: declared `Content-Length` → streamed size cap (mid-read break) → magic-byte sniff. A malicious client that lies about Content-Length is caught by the streamed cap, and we never accumulate gigabytes in RAM before deciding "no."
- **Upload bytes never written to disk.** `read_pe_upload` returns `bytes` and the caller is on the hook for not retaining them. Per-request tmpfs is for the sandboxed extractor in Step 4, not the API process.
- **CORS is an explicit allowlist with GET/POST only.** No `*`, no credentials. The OPTIONS preflight gets 600s caching to keep the chatter down.
- **Custom `UploadValidationError`** subclassing `HTTPException` so routers and tests can `except UploadValidationError` cleanly without losing FastAPI's auto-conversion to JSON.

**Pitfall noticed**
- `slowapi` requires `app.state.limiter = limiter` *before* the middleware is added, otherwise the decorator-style limits silently no-op. Wired explicitly and noted here so a future refactor doesn't lose it.

**Lesson**
- Validation order is a security property, not a stylistic choice. Cheapest-check-first means an attacker can't make us do expensive work just by sending garbage. Write that down (right here) so the order isn't accidentally "tidied up" later.

---

## Step 4 — PE feature extractor and `/scan` endpoint stub

**Date:** 2026-05-05

**What landed**
- `backend/app/services/pe_features.py` — in-memory PE parsing via `pefile`, returns a frozen `PEFeatures` dataclass. `FEATURE_SCHEMA_VERSION` constant is the wire contract; bumping it invalidates pinned model artifacts on purpose.
- `backend/app/schemas/scan.py` — Pydantic `FeatureResponse` / `ScanResponse` / `ModelPrediction`. The wire shape is final from day one even though predictions are stubbed.
- `backend/app/routers/scan.py` — `POST /scan` wired through `read_pe_upload` → `extract_features`. Per-IP `10/minute` limit on top of the global default.
- `backend/app/main.py` — router included after the limiter is bound to `app.state`.
- `backend/tests/fixtures/pe_builder.py` — programmatic minimal-PE32 generator used by both unit and integration tests, so no binary fixture ships in git.
- `backend/tests/test_pe_features.py` and `backend/tests/test_scan.py`.

**Decisions**
- **Two layers for the feature shape — internal dataclass + external Pydantic model.** The dataclass is what the extractor returns; the Pydantic schema is what the frontend sees. They're 1:1 today, but separating them means a future move to LIEF (or a richer feature set) doesn't ripple into the wire contract without an explicit version bump.
- **`FEATURE_SCHEMA_VERSION` is the contract.** A trained model is locked to a specific feature ordering; if the schema drifts, every prediction is silently wrong. The version pins to the model manifest so a mismatch becomes a startup failure instead of a quiet correctness bug.
- **`fast_load=True` then targeted `parse_data_directories`.** Walking every data directory by default means a malformed resource tree can crash the parser even when we only want imports. Selective parsing keeps the blast radius tight; a broken directory degrades a feature flag (`has_resources=False`) instead of failing the whole request.
- **Single broad `except Exception` around the parser.** `pefile` raises `PEFormatError` for "not a PE", but it can also propagate unexpected exceptions (mmap, struct, recursion) on adversarial input. Both get funneled into `PEParseError` so a 500 on a hostile upload is impossible by construction.
- **Truncate sections at 16 and imports at 64 — but record the count before truncating.** A PE with 200 sections is almost certainly hostile or packed; we cap the work but never silently drop the signal. The `number_of_sections` feature still reflects the real count.
- **Test fixture is a programmatic PE, not a binary file in git.** Shipping even a "harmless" sample EXE in the repo invites every AV scanner on contributors' laptops to quarantine the checkout. `struct.pack` produces a deterministic, inspectable, AV-invisible PE on demand.
- **Eager `del body` after extraction.** Belt-and-suspenders given Python's reference semantics, but cheap and aligns with the "never retain upload bytes" rule from `SECURITY.md`.

**Pitfall noticed**
- `pefile.DIRECTORY_ENTRY` keys map to integer indices; the parsed attributes hang off the `PE` instance as `DIRECTORY_ENTRY_*` (no `IMAGE_` prefix). Mixing the two namespaces silently returns `None` and false-negatives every directory presence check. `_has_directory` strips the prefix and falls back to the raw data-directory table when the parsed attribute is missing.

**Lesson**
- The wire schema for ML predictions wants to be locked in *before* the model lands, not after. Once a frontend ships against a shape, every refactor to that shape is a coordinated deploy. The `predictions: []` stub today buys a stable contract for free and lets the frontend work proceed in parallel.

---

## Step 5 — Model registry, mock predictors, `/models` and `/ready`

**Date:** 2026-05-05

**What landed**
- `backend/app/services/model_registry.py` — lazy thread-safe singleton with two paths: a deterministic `_MockPredictor` (default, runs without trained pickles) and `_SklearnPredictor` for real `*.joblib` artifacts. Real loader hashes every pickle and refuses any whose SHA-256 isn't in `MANIFEST.json` — the SECURITY.md rule, enforced.
- `FEATURE_VECTOR_ORDER` and `PEFeatures.to_vector()` in `pe_features.py` — frozen feature ordering so a model trained today isn't silently fed a permuted vector tomorrow. Includes `max_section_entropy` / `mean_section_entropy` / `total_section_raw_size` aggregates so section-derived signal survives the flatten.
- `backend/app/routers/scan.py` — `predictions` now populated from `registry.predict_all(features)`. Mock-or-real is invisible at this layer.
- `backend/app/routers/meta.py` — `GET /models` (list + paper citations + metrics) and `GET /ready` (503 until registry loads). Liveness (`/health`) and readiness (`/ready`) stay separate.
- `backend/tests/test_model_registry.py` and `backend/tests/test_meta.py` covering: mock determinism, mock disagreement, SHA-256 mismatch refused, schema-version mismatch refused, valid SHA accepted, `/models` and `/ready` shape.

**Decisions**
- **Mock by default until artifacts arrive.** `use_mock_models=True` plus a missing `MANIFEST.json` both fall through to the mock path. The dashboard demos end-to-end *today* — a frontend developer doesn't have to wait on the trained pickles being recovered. The mock predictors are clearly labelled (`is_mock: true` on `/models`, `mock_mode: true` on `/ready`); honesty over a fake-looking-real demo.
- **Mocks deterministic, biased per-model.** Same input → same prediction (reproducible demos), and per-model `bias` makes RF and XGBoost disagree often enough that the planned "disagreement view" actually has data to show. A mock that always agrees would make the most demo-able feature look broken.
- **Singleton is lazy, fails loudly.** Loading on import would mean a bad manifest blocks `/health`. Loading on first prediction would mean a malformed deploy is hidden until the first user request. Lazy-on-first-`/ready`-or-`/scan` strikes the balance, and a load failure is *not* retried — silently retrying a misconfigured manifest would mask an operator error indefinitely.
- **`_load_real` imports `joblib` locally.** Keeping joblib + scikit-learn out of the import path means the mock-only test runs (and any future minimal docker image) don't have to drag the full ML stack along.
- **Manifest pins `feature_schema_version`.** A trained pickle is married to a feature ordering. If the runtime's `FEATURE_SCHEMA_VERSION` drifts from the manifest's, the loader aborts — better than serving silently-wrong predictions for a week before someone notices.
- **`/models` exposes `feature_order` and `feature_count`.** The frontend uses it to render the SHAP waterfall axes correctly without hardcoding the schema; bumping the schema version doesn't require a synchronized frontend deploy as long as the frontend reads from this endpoint.

**Pitfall noticed**
- Pydantic v2 reserves `model_*` as a protected attribute namespace; defining `ModelInfo` raised a warning until `protected_namespaces=()` was set on its `ConfigDict`. Worth knowing — the field name `model_name` on `ModelPrediction` is fine because it's defined separately, but anything that mixes `model_*` fields with default Pydantic config will warn.

**Lesson**
- A "mock mode" only earns its keep if it's *honestly* mocked. The temptation is to make the mocks look indistinguishable from real predictions — that's a footgun for the application essay (running a portfolio piece on fake data without saying so is the kind of thing reviewers notice). Plumbing `is_mock` and `mock_mode` through every response means the demo shows the truth, and the day the real artifacts land, removing the banner is a config flip — not a code change.

---

## Step 6 — SHA-256 cache and `/explain`

**Date:** 2026-05-05

**What landed**
- `backend/app/services/cache.py` — generic `TTLCache[T]` (LRU + TTL), thread-safe, injectable clock for deterministic tests.
- `backend/app/routers/scan.py` — fast path: hash the validated bytes, return the cached `ScanResponse` if present, otherwise parse + predict + cache. The cache check happens *after* `read_pe_upload` so cap + magic-byte enforcement still run on every request — defense in depth, not bypassable by replaying a previously-cached hash.
- `backend/app/services/explain.py` — per-model SHAP-style explanations. Real path lazy-builds a `shap.TreeExplainer` per loaded model and caches it. Mock path produces deterministic per-feature contributions from a hash of `(model_id, index, value)`, all flagged `is_mock=True`.
- `backend/app/schemas/explain.py` and `backend/app/routers/explain.py` — `POST /explain` endpoint. Form fields: `upload`, optional `model_name` to focus a single model, `top_n` (1–64).
- Tests: TTL expiry, LRU eviction, MRU promotion, concurrent-write smoke, cache-hit on second scan (parser monkey-patched to AssertionError so a bypass would be loud), `/explain` happy/filter/unknown-model/non-PE.

**Decisions**
- **Cache check runs *after* upload validation.** Inverting the order would let a cached prediction shortcut the 10 MB cap and MZ-magic check. Validation is cheap; do it on every request and cache only the final response. The cost is one `read_pe_upload` per request — acceptable, and it keeps the security contract uniform.
- **Cache key is the SHA-256 of the validated body, not the upload's filename or `Content-MD5`.** Filenames are client-controlled; MD5 collisions are exploitable. SHA-256 is the only hash we can defend in the threat model.
- **Module-level cache singleton, exposed via `get_scan_cache()`.** Tests need to clear it; the helper means tests don't reach into private state. The cache itself is idempotent across restarts (no persistence by design — see SECURITY.md, "binaries never persisted; LRU hash→prediction cache only").
- **Real explainer cache is separate from prediction cache.** TreeExplainer init is the expensive piece (it walks the tree); per-sample SHAP calls are fast. Caching the explainer object once per model means 2nd-onward `/explain` calls don't re-pay that cost. Eviction isn't needed because the model set is bounded.
- **`shap_values` shape varies between RF and XGBoost.** sklearn binary classifiers return `[class_0, class_1]` arrays; xgboost returns a single 2D array. The handler probes `isinstance(raw, list)` and falls back to `np.atleast_1d` on `expected_value` so both paths land on a clean per-class row without special-casing the model family at the call site.
- **`top_n` is server-side, not frontend-side.** The waterfall renders ~10–15 features; capping at 64 keeps payloads small and prevents a malicious client from asking for a huge response. The sort is by absolute SHAP magnitude with feature-name tiebreak, so the order is deterministic.
- **`is_mock` is per-explanation, not per-response.** Real RF + mock XGBoost is a perfectly valid mid-migration state once one trained pickle lands and the other hasn't. Forcing a global flag would either lie about half the data or block partial rollout.

**Pitfall noticed**
- Patching `app.services.pe_features.extract_features` does not affect `scan.py` after it's been imported, because `scan.py` did `from ... import extract_features` — that creates a *new binding* in the `scan` namespace. The cache-hit test patches `app.routers.scan.extract_features` instead. Generally true for any function imported by name and then mocked: patch the consumer's namespace, not the producer's.

**Lesson**
- The cache is a contract about *which version of the world* a prediction came from. The TTL ceiling is the maximum staleness anyone can be served — bump model artifacts, the cache holds old predictions for at most one TTL window. That's a feature: it keeps a model rollout from being instantaneous-but-fragile (one bad worker poisoning another's cache). When/if the deploy story ever needs cache invalidation on model load, that's a four-line change in `model_registry.load`; don't pre-build it.

---
