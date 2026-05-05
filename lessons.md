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

## Step 7 — Adversarial perturbation simulator (`POST /perturb`)

**Date:** 2026-05-05

**What landed**
- `backend/app/services/perturb.py` — `apply_perturbations(vector, specs, model_name=...)`. Four ops: `set`, `delta`, `scale`, `toggle`. Validates feature names against `FEATURE_VECTOR_ORDER`, rejects NaN/Inf, caps perturbations per request at 64.
- `backend/app/schemas/perturb.py` and `backend/app/routers/perturb.py` — `POST /perturb`. Request accepts either a full `FeatureResponse` (round-trip what /scan returned) or a bare `feature_vector` (cached client-side). Per-IP 30/min — looser than /scan because slider-drag UIs fire often, but bounded so a stuck slider can't DoS the worker.
- Response carries `baseline_predictions`, `perturbed_predictions`, the `applied` list (with `before`/`after`), and a per-model `deltas` envelope (`label_flipped`, `confidence_delta`) so the frontend renders the diff without arithmetic.
- `backend/tests/test_perturb.py` — every op, unknown feature → 422, NaN/Inf → 422, perturbation cap, baseline parity with `registry.predict_all`, model_name filter, both request shapes (features and vector).

**Decisions**
- **Operates on feature vectors, not PE bytes.** Re-uploading bytes per slider tick would be wasteful and would re-run the parser dozens of times for one user session. Vectors are JSON, cheap, and let the frontend cache the baseline locally and drive perturbation requests at slider-event rate.
- **Two request shapes (features OR feature_vector), not one.** The slider UI has the vector cached after the first /scan; a user pasting a previously-saved JSON has a `FeatureResponse`. Forcing one shape would push translation work onto every client. The schema requires *exactly one* — passing both isn't sensible, but the validation catches the empty case (422) so the caller sees a clear error.
- **Toggle is the friendly alias for set-on-bools.** The slider UI for boolean features is a switch, not a numeric input; binding "toggle" semantically (and rejecting it on non-bool features) makes invalid frontend states impossible to send. The boolean feature list is hard-coded — there are only four (`has_signature`, `has_resources`, `has_debug`, `has_tls`) and they're stable across schema versions.
- **NaN/Inf rejected with hard floor + ceiling at ±1e12.** Without the ceiling, `scale: 1e308` would produce a working vector but a meaningless prediction. The floor sits well above any plausible PE feature (the largest realistic value is `size_of_image` at maybe 1e9 bytes), so legitimate perturbations are unaffected.
- **Baseline is *predicted from the supplied vector*, not recomputed from scratch.** Otherwise a UI showing "before" predictions and a `/perturb` "before" wouldn't necessarily match — that gap would feel like a bug to users even though it's mathematically defensible.
- **`MAX_PERTURBATIONS_PER_REQUEST = 64`.** Way more than any UI needs; tight enough that an attacker can't ship a 100k-spec request to spike the worker.
- **No cache integration.** `/perturb` is intentionally outside the scan cache: the cache is keyed on PE-byte SHA-256, but `/perturb` works on synthetic feature vectors that have no PE behind them. Caching here would mean the cache key is the perturbed vector itself, which is borderline useless (sliders rarely revisit the exact same configuration).

**Pitfall noticed**
- The vectorizer reads section aggregates from `PEFeatures.sections`, but the `FeatureResponse` doesn't carry section bytes — only flat aggregates. When reconstructing a `PEFeatures` from a `FeatureResponse` for the perturb endpoint, the synthesized instance has `sections=[]`, so the aggregates fall back to zero. That's acceptable for `/perturb` because the user can perturb the aggregate features (`max_section_entropy`, etc.) directly via `set` ops, but it's a gotcha worth flagging: the round-trip `extract_features → FeatureResponse → PEFeatures` is *not* lossless.

**Lesson**
- An "adversarial" feature is the most demo-able piece of an explainability dashboard — but only if the round-trip is fast enough that the user *feels* the model react to their input. Designing the endpoint around the slider UI from day one (vector-in, deltas-out) is what unlocks that feel; designing it around "POST a binary, get a delta back" would have made every slider drag a 500ms pefile parse. Build the endpoint for the interaction, not for the noun.

---

## Step 8 — Sandboxed extractor (worker, abstraction, container)

**Date:** 2026-05-05

**What landed**
- `backend/app/extractor_worker.py` — standalone program. Reads PE bytes from stdin, writes a single-line JSON envelope to stdout, exits with code 0/2/3. Imports nothing beyond stdlib + (lazily) `app.services.pe_features` and pefile.
- `backend/app/services/extractor.py` — `Extractor` protocol with two implementations: `InProcessExtractor` (default) and `SubprocessExtractor` (forks the worker, applies wall-clock timeout + `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_CORE` on Unix). `get_extractor()` factory cached per process.
- `backend/Dockerfile.extractor` — minimal, non-root image with only `pefile` installed. Designed to be run with `--network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --memory=512m --cpus=1` per `SECURITY.md`.
- `backend/app/config.py` — new flags: `extractor_strategy`, `extractor_timeout_seconds`, `extractor_memory_mb`, `extractor_cpu_seconds`. Defaults to `inprocess` so tests stay fast.
- `backend/app/routers/scan.py` and `backend/app/routers/explain.py` — both routers now call `get_extractor().extract(...)` instead of `extract_features` directly.
- `SECURITY.md` updated to document the two-layer isolation (OS-level via subprocess + rlimits, container-level via Dockerfile.extractor).
- `backend/tests/test_extractor.py` covers worker stdin/stdout protocol (returncodes 0/2 on valid/garbage/empty), parity between `InProcessExtractor` and `SubprocessExtractor` outputs, parse-error propagation through the subprocess JSON envelope, factory selection by config, factory rejects unknown strategy.

**Decisions**
- **Worker is a CLI program, not a long-lived service.** A long-lived sidecar with HTTP/socket IPC adds a daemon to harden, an attack surface to audit, and reconnect logic. The stdin → stdout → exit pattern means each request gets a fresh process; an exploit lasts at most one parse and then the kernel wins.
- **Two stacked isolation layers, both shippable today.** OS-level via `SubprocessExtractor` (works on any Linux/Mac host without docker compose); container-level via `Dockerfile.extractor` (production deploy). Each layer is useful on its own — the OS-level path runs in CI, the container path gets the full SECURITY.md posture. Defense in depth, not "pick one".
- **`Dockerfile.extractor` installs only `pefile`.** No FastAPI, no scikit-learn, no SHAP. The image is tiny, which means `docker scan` has fewer findings to triage, supply-chain audits are cheaper, and any new import to the worker stands out in code review. If a future change adds a transitive dep, the image build will not silently drag it along.
- **Worker exit codes carry semantics.** 0 = success, 2 = parse failure, 3 = system error. The caller maps 2 → `PEParseError` → 400 (client problem), 3 → 500 (server problem). Without the split, every worker failure looks the same to the API and we'd lose the "is this a hostile file or is the worker broken" signal.
- **`InProcessExtractor` stays the default in config.** Subprocess fork-per-request adds ~30 ms; the unit test suite would slow to a crawl. Production sets `extractor_strategy=subprocess` via env var; the test runner doesn't, so behavior diverges by design.
- **`reset_extractor_cache()` is a *test hook*, not API surface.** Documented as such in the docstring. The factory caches because the strategy is determined at config time, not per-request — production never needs to reset it.
- **rlimits are best-effort.** `resource.setrlimit` doesn't exist on Windows. The dev workflow on Windows falls back to timeout-only isolation, which is what the user-facing security guarantee already says (the *deploy target* is Linux). Documenting the platform asymmetry in the docstring is more honest than papering over it.

**Pitfall noticed**
- After replacing `extract_features` with `get_extractor().extract` in the routers, the cache-hit test still patched `scan.extract_features` — but the binding had been removed, so `monkeypatch.setattr` would raise `AttributeError`. The fix is to patch `extractor._extractor_cache` with a `_Boom` object. This is the second time the same import-binding pitfall has bitten this project (Step 6 lessons noted it for `extract_features`); next time, the right move is to patch the *factory* return value, not a module-level binding. Memo to self: when the consumer's namespace is a moving target, patch a function-call boundary, not a name lookup.

**Lesson**
- The blast radius of a parser bug is a *system* property, not a *code* property. Rewriting `pe_features.py` to be 100% safe is impossible — pefile is a wide attack surface and "more careful Python" doesn't fix that. Putting the parser behind two layers of OS-level isolation (subprocess rlimits + container with `--network=none --read-only --cap-drop=ALL`) bounds the damage to "an attacker gets a 30-second-life-expectancy process with no network and no filesystem". That's the kind of property that survives a bug we haven't found yet — defense in depth pays for itself the day a CVE drops.

---

## Step 9 — Frontend scaffolding (upload zone + multi-model results)

**Date:** 2026-05-05

**What landed**
- `frontend/` directory: Next.js 14 (App Router) + TypeScript strict + Tailwind. `package.json`, `tsconfig.json`, `next.config.mjs`, `tailwind.config.ts`, `postcss.config.js`, `.env.local.example`, `next-env.d.ts`, `.gitignore`, `frontend/README.md`.
- `frontend/src/app/layout.tsx` and `globals.css` — dark theme, system font stack, no flair.
- `frontend/src/lib/api.ts` — typed client. TypeScript types mirror the Pydantic schemas; `ApiError` surfaces `{status, detail}` from FastAPI uniformly. Wrappers: `postScan`, `getModels`, `getReady`. `NEXT_PUBLIC_API_BASE` env var.
- `frontend/src/components/UploadZone.tsx` — drag-and-drop, file picker fallback, client-side MZ-magic check + 10 MB cap matching the backend, error toast.
- `frontend/src/components/ResultsPanel.tsx` — file summary card (SHA-256, size, sections, imports) and a verdict table (model · label · confidence · latency). Highlights the row when models disagree, surfaces a top-banner when `/models.mock_mode` is true.
- `frontend/src/app/page.tsx` — wires `getModels()` on mount + `UploadZone` → `ResultsPanel`. Header surfaces `feature_schema_version`, feature count, model count, and a "mock mode" pill.
- `README.md` roadmap updated: Phase 1 ✅, Phase 2 ✅, Phase 3 in progress.

**Decisions**
- **App Router, not Pages.** Next 14 has stabilized App Router and the future is here; starting on legacy now would cost a migration later. Server components aren't strictly needed for this UI but the routing model is the standard.
- **Dependencies installed locally only — `node_modules/` is gitignored, no lockfile committed yet.** I deliberately did not run `npm install` in this commit. Committing the lockfile in a separate "freeze deps" step (once the user has run it on their dev box) keeps this commit reviewable as pure scaffolding. Reviewers reading the diff can see exactly which packages are pulled in without scrolling through 10k lines of lockfile.
- **Client-side MZ-magic check.** The backend enforces it, but doing the same check before the upload starts saves a round-trip on obvious mistakes (a user dropping a `.png`) and gives instant feedback. The check is *not* trusted server-side — defense in depth, same posture as cache-after-validation.
- **Mock-mode banner driven by `/models`, not by individual prediction `is_mock` flags.** The `/scan` response doesn't currently include `is_mock` per prediction (the registry adds it at `/models` granularity). Surfacing the banner from `/models.mock_mode` means the UI is honest from the very first render, before any scan happens. If we ever want per-row banners (real RF + mock XGBoost), the API needs to grow `is_mock` into `ModelPrediction` first — small change, deferred.
- **Disagreement view is built into the verdict table, not a separate component.** When two models return different labels, the panel is highlighted and a "Models disagree" pill appears. This is the most demo-able piece of the dashboard (per Phase 3 TODO) and we want it visible in v1, not behind a tab.
- **No D3, no Recharts yet.** The verdict table is plain HTML — fast, accessible, no chart library churn. SHAP waterfall lands in a focused step where the chart-library decision (D3 raw vs. Recharts vs. visx) is the question, not bundled with scaffolding.
- **`output: "standalone"` in `next.config.mjs`.** Phase 4's deploy story produces a small image; setting standalone now means the Dockerfile in Phase 4 is one-liner.
- **Tailwind palette uses brand tokens (`ink`, `surface`, `border`, `accent`, `warn`, `danger`, `ok`).** Not a design system, just a tiny semantic layer so a future design pass can swap values in one place. No chosen "design" yet — the look intentionally stays toolbar-utilitarian.

**Pitfall noticed**
- Without committing `package-lock.json`, anyone cloning the repo runs `npm install` against the version constraints in `package.json` and gets *whatever* their npm picks today. That's deliberate for this scaffolding commit (small diff, easy review) but a follow-up commit needs to land the lockfile before anyone else builds. Failing to do that risks a "works on my machine" Phase 4 deploy.

**Lesson**
- A frontend commit is also a *contract commit*. The TypeScript types in `api.ts` are the single source of truth for everything React renders — they have to mirror the Pydantic schemas exactly, and any drift will show up as a runtime error a user sees. Pin the contract in code (not in a doc), keep it in one file, and review backend schema changes with this file open. The day the backend renames `model_name` to `id`, `api.ts` is where the discipline lives.

---

## Step 10 — SHAP waterfall and `/explain` integration

**Date:** 2026-05-05

**What landed**
- `frontend/src/lib/api.ts` — added `FeatureContribution`, `ModelExplanation`, `ExplainResponse` types and `postExplain(file, options)` with `modelName` + `topN`.
- `frontend/src/components/ShapWaterfall.tsx` — pure-SVG horizontal-bar waterfall, no chart library. Sorts contributions by `|shap_value|` client-side (defense against future backend changes that drop the sort), colors signed bars (`danger` for malicious-pushing, `ok` for benign-pushing), exposes `aria-label` per bar plus a `sr-only` table for screen readers.
- `frontend/src/components/ExplanationPanel.tsx` — fetches `/explain` on mount, renders one `ShapWaterfall` per model, shows a `mock` pill per-model when `is_mock` is true, validates `sha256` matches the scan's hash (catches any future backend bug loudly).
- `frontend/src/app/page.tsx` — keeps both the `ScanResponse` and the originating `File` in state so the explain panel can re-POST the bytes. `UploadZone` callback now hands back `(result, file)`.

**Decisions**
- **No chart library.** Recharts/visx/D3 would each add ~30–80 KB gzipped to the bundle for a chart that's structurally a sorted list of horizontal bars. SVG with Tailwind classes does the job in ~80 lines. The lesson from prior steps — minimum dependency surface — applies to the frontend too.
- **Re-POST the file to `/explain` rather than caching the explanation server-side.** The prediction cache is keyed on PE-byte SHA-256; adding a parallel explanation cache means another invalidation surface and another deploy-time cache to flush. Re-extracting features for explain is bounded (the upload validator still gates the request) and the slower path is acceptable for a once-per-scan operation. Revisit if `/explain` grows expensive (e.g. real shap.TreeExplainer init dwarfs upload time).
- **Per-model stacked layout, not tabs.** With two models the user wants to *compare*, not *switch*. Tabs hide the other model's reasoning at exactly the moment it's most useful (the disagreement view). Stacked vertical layout makes the comparison the default. Three+ models will need a denser layout, but that's a Step-N concern.
- **Client-side re-sort.** The backend already returns contributions sorted by `|shap_value|`, but the frontend sorts again. Reason: a future change to backend pagination, top-N truncation, or schema reordering could silently break the visualization. The cost is `O(n log n)` on at most 64 entries — invisible. The benefit is one fewer way the chart can quietly lie.
- **Color convention: red for "pushes toward malicious".** Tree-SHAP for binary classification with class 1 = malicious produces positive `shap_value` for malicious-pushing features. Red/green is the most intuitive read for the dashboard's audience (security analysts), and the legend lives directly in the panel header so a colorblind user reading the docs gets the convention spelled out.
- **`sha256` cross-check between `/scan` and `/explain` responses.** Same file, same hash — the assertion catches a class of nasty bugs (file replaced mid-flight, backend serving cached results from another session, etc.) before they become "the explanation doesn't match the prediction" support tickets.
- **Tabular `sr-only` fallback, not just `aria-label`.** The `aria-label` per bar is good for navigation but a screen-reader user wants to *scan* the values too. The hidden table satisfies the "tabular fallback" requirement in `TODO.md` Phase 3 directly and lets keyboard users cycle through values without having to step over each bar.

**Pitfall noticed**
- React's `useEffect` with object dependencies (passing the `File` itself) re-runs on every parent render because `File` instances aren't reference-stable across re-renders. The pattern that works here: `page.tsx` keeps the `File` in state once and only ever sets it to a *new* `File` on a fresh upload, so the effect fires exactly when expected. If a future refactor passes a *recreated* `File` (e.g. via Form.values), the explain effect will spam requests. Worth noting: prefer scalar dependencies (`expectedSha256`) over object identity wherever possible.

**Lesson**
- An explainability dashboard isn't credible until the user can see *why*, not just *what*. The verdict table in Step 9 was the headline; this waterfall is the substance. Building it without a chart library kept the install footprint honest, and putting the colour convention in the panel header (instead of in a hidden tooltip) means a reviewer landing for 30 seconds gets the intuition immediately. Visualizations are user-experience contracts: spell them out in plain text right next to the chart.

---
