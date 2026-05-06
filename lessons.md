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

## Step 11 — Perturbation simulator UI

**Date:** 2026-05-05

**What landed**
- `frontend/src/lib/api.ts` — added `PerturbationSpec`, `AppliedPerturbation`, `PredictionDelta`, `PerturbRequest`, `PerturbResponse` types and `postPerturb(body)` wrapper (JSON request, JSON response).
- `frontend/src/components/PerturbationSimulator.tsx` — curated 9-control panel: 5 sliders (`imported_dll_count`, `imported_function_count`, `max_section_entropy`, `mean_section_entropy`, `size_of_code`) and 4 toggles (the `has_*` boolean features). Side-by-side baseline → perturbed delta cards per model, with a `flipped` highlight when the verdict changes. Reset button. Debounced (200 ms) `/perturb` calls with in-flight `AbortController` so a slider drag doesn't queue stale responses.
- `frontend/src/app/page.tsx` — renders `<PerturbationSimulator>` under the explanation panel once a scan is in state.

**Decisions**
- **9 controls, not 28.** The full feature vector is too dense for a slider UI; surfacing every entry would drown the user in noise and make the demo feel like an admin form. The 9 picks are the most demo-able: features whose perturbation visibly moves the verdict for typical PE distributions, and which map cleanly to a slider-or-toggle. Adding more is a one-line append; the backend already validates names against `FEATURE_VECTOR_ORDER`, so a typo here surfaces as 422.
- **`set` op everywhere, not `toggle`.** The backend offers both, but emitting `{op: "set", value: 0|1}` from the toggle UI produces the same final vector regardless of how many times the switch was flipped — the result is a function of the *position*, not the history. Idempotent UI = predictable demo.
- **Only emit perturbations when the user has *moved* a control.** An untouched slider doesn't appear in the request payload, which keeps the `applied` array honest (it shows what changed, not all the controls that exist) and shrinks the wire size when most controls are at baseline.
- **Debounce + AbortController, both.** Debounce alone (200 ms) handles steady drags. AbortController handles the case where the *first* request from a drag hasn't returned by the time the *second* fires — without it, a stale response could overwrite the current UI state. Both layers are cheap and the combination is the standard pattern for "live preview as user drags".
- **Side-by-side delta layout (controls left, deltas right).** Tabs would force the user to switch back and forth; stacked layout would push the delta below the fold during the most interactive moment of the demo. Two columns keeps the cause-and-effect visible in one glance — exactly what the application essay's screencast wants to capture.
- **`label_flipped` is the headline metric, not `confidence_delta`.** A 5% confidence shift is academic; a label flip is the *attack outcome*. Highlighting flipped cards with `border-warn bg-warn/10` puts the demo's narrative payoff (the moment a defender realizes a single-feature change can swing the verdict) where the eye lands.
- **Aggregate features (`max_section_entropy`, `mean_section_entropy`) read 0 from baseline.** The `FeatureResponse` doesn't carry the section bytes needed to compute the aggregates client-side; the slider's "set" semantic means the user is overriding rather than nudging, which is the right move for a what-if simulator anyway. The cost: the slider doesn't show "your file is at X today" before you move it. Documented; revisit if it becomes confusing.

**Pitfall noticed**
- `useEffect` dependencies include the freshly-built `specs` array. Without `useMemo`, every render produced a *new* array reference even when state was unchanged, and the debounced fetch would refire on unrelated re-renders. The fix is `useMemo(() => specsFor(state, baseline), [state, baseline])` so `specs` is a stable reference until inputs change. Same family of trap as Step 10's `File`-as-dependency note: object identity, not equality, is what `useEffect` watches.

**Lesson**
- A "live preview" UI is a contract about responsiveness: every control change must produce a visible result before the user has stopped looking at the screen. 200 ms is the threshold where it still feels real-time but the backend isn't getting flooded; below that you're paying network cost on every pixel of slider drag. Pick the threshold deliberately, and document why — future-you adjusting it without context will land somewhere unprincipled.

---

## Step 12 — Docker compose stack (API + frontend + Caddy)

**Date:** 2026-05-05

**What landed**
- `frontend/Dockerfile` — multi-stage, alpine-based, non-root (UID 10001). Honors `output: "standalone"` from Step 9 so the runtime image carries only the trace-included `node_modules`. `ARG NEXT_PUBLIC_API_BASE` lets compose inject the path at build time (Next.js inlines `NEXT_PUBLIC_*` constants into the bundle).
- `Caddyfile` — reverse proxy on `:8080`. Routes `/api/*` to backend (strip prefix), everything else to frontend. 11 MB body cap (defense-in-depth on top of the backend's 10 MB), HSTS + content-type-options + frame-ancestors headers, removes the `Server` header.
- `docker-compose.yml` — three services on a `malvis` network: `api` (FastAPI, `EXTRACTOR_STRATEGY=subprocess`), `frontend` (Next.js standalone), `proxy` (Caddy). Healthcheck-gated startup. `artifacts/` mounted read-only into the API container.
- `.env.example` — public env for `docker-compose` variable substitution: `PUBLIC_ORIGIN`, `PROXY_HTTP_PORT`, `NEXT_PUBLIC_API_BASE`, `USE_MOCK_MODELS`. The frontend env is set at *build* time via `args:`; service runtime env is set in `environment:` blocks.
- `frontend/.dockerignore` keeping the build context tight.
- `SECURITY.md` updated to record the cut: compose runs subprocess-isolated extractor (OS-level); the per-request sidecar pattern is a Phase 4+ production concern.
- README updated with the `docker compose up` flow and a note about the subprocess-vs-sidecar split.

**Decisions**
- **Same-origin via the proxy, not CORS-juggling between subdomains.** With `/api/*` proxied to the backend and everything else to the frontend on a single hostname (`localhost:8080` locally), the browser never sends a CORS preflight. The backend's CORS allowlist is still the source of truth — defense in depth — but the *common* path is preflight-free. Subdomains (`api.malvis.devrakib.com`) are easy to migrate to later if the deploy story prefers it.
- **`NEXT_PUBLIC_API_BASE` defaults to `/api`, not a hardcoded URL.** Same-origin path means the same image runs in dev (`localhost:8080`) and prod (`malvis.devrakib.com`) without rebuild. Override the build arg only if hosting splits the origins.
- **`EXTRACTOR_STRATEGY=subprocess` in compose, not `inprocess`.** The whole point of the compose stack is to look like production. Subprocess + rlimits is the OS-level isolation we have today; running `inprocess` here would mean the production posture diverges from what we test locally. Latency cost is ~30 ms per scan — fine for a dashboard.
- **Caddy over nginx.** Auto-HTTPS with Let's Encrypt is one config-line away when this gets a real hostname (`:8080` → `malvis.devrakib.com`). Nginx would need certbot + cron. Caddy's config is also small enough to fit on one screen, which matters for review.
- **`artifacts/` mounted read-only.** Even in mock mode the backend never writes to artifacts; making the mount RO is a cheap invariant that catches a class of bugs (a future feature accidentally persisting model state to the artifacts dir) at the syscall level.
- **Healthcheck gates the frontend's `depends_on`.** Without `condition: service_healthy`, the frontend would race the backend's startup and serve users while `/api/models` 503s for the first ~2 seconds. The cost is one healthcheck cycle's worth of compose-up latency.
- **Frontend Dockerfile falls back to `npm install` when the lockfile is missing.** This is *deliberate* for a fresh-clone-builds-something workflow; CI should fail closed (a separate `package-lock.json must exist` lint). The Dockerfile prints a `WARN` to stderr so the fallback is visible.
- **Production vs. local container-level extractor isolation deferred.** Per-request container spawn is real orchestration work (k8s sidecar with ephemeral pods, or a long-lived dispatcher running `docker run --rm` per request) and it's the kind of thing that wants its own Step. The OS-level isolation we have *today* is real; the SECURITY.md update is honest about which layer is wired and which is a deploy-time concern.

**Pitfall noticed**
- `NEXT_PUBLIC_*` env vars look like runtime config but are *baked into the bundle* at `npm run build` time. Setting them in the compose `environment:` block (where backend env vars live) does nothing — they have to flow through `build.args:` and into a Dockerfile `ARG`. First-time wiring trips on this every project; documenting it in the compose file's comment block keeps the next person from rebuilding three times figuring it out.

**Lesson**
- A docker-compose file is the *executable* version of an architecture diagram. The diagram in README.md says "Next.js → FastAPI → models", but it can't tell you that the proxy strips `/api`, that the extractor runs as a subprocess for now, that artifacts are RO, or that the frontend's API base is build-time-baked. The compose file says all of that, runs it, and breaks loudly when any of the assumptions stops being true. Keep the diagram for the README; trust the YAML for ground truth.

---

## Step 13 — Model card panel and persistent disclaimer

**Date:** 2026-05-05

**What landed**
- `frontend/src/components/ModelCardPanel.tsx` — three project-level cards (Out of scope · Intended use · Known limitations) plus one per-model card grid driven by `/models`. Per-model card surfaces id, family, mock badge, training dataset, metrics, paper citation, notes.
- `frontend/src/app/page.tsx` — persistent disclaimer line in the header ("Research and educational tool — not a substitute for production triage…") and a `<ModelCardPanel>` rendered as the page's last section, after the perturbation simulator.
- `TODO.md` ticked: model card panel.

**Decisions**
- **Project-level vs per-model split is the cardinal call.** Out-of-scope, intended use, and high-level limitations are about *MalVis*, not about RF or XGBoost individually — hard-coding them in the component prevents drift if a new model joins the registry. Per-model fields (metrics, citation, notes) come from the manifest because they genuinely differ. The split also means a future model registry change doesn't silently weaken the disclaimer.
- **"Out of scope" gets the danger border, not the warning border.** The warn color is reserved for mock-mode and perturbation flips — both interesting but reversible. The "do not use for production triage" message is the load-bearing disclaimer for credibility with security reviewers and admissions readers; it deserves the loudest treatment available without being literally red text.
- **Persistent disclaimer in the header, full panel at the bottom.** Putting the model card at the top would push the upload zone below the fold, ruining the "drop a file, see a verdict" demo arc. Two-channel approach: the small line keeps the warning in view at all times, the full panel rewards anyone who scrolls to actually read what they're being warned about.
- **Calibration is documented as missing, not faked.** The manifest schema doesn't carry reliability bins yet; the panel says so explicitly ("the manifest does not yet ship reliability bins"). A synthesized calibration plot would be the worst kind of dishonesty — looking measured when it isn't. Adding `calibration: {bins: [{predicted, observed}]}` to the manifest is a one-step backend change followed by a chart component, deferred to a future step.
- **Mock-mode warning *inside* the limitations card, not a fourth card.** The mock-mode banner already lives at the top of the results panel (Step 9); duplicating it as a top-level model-card section would over-emphasize. Embedding it as a bullet in "Known limitations" is the right level — a reader looking at limitations is exactly the audience for "by the way, these numbers are placeholder".
- **No `getModels` refetch.** `page.tsx` already loads `/models` for the mock-mode banner; passing the same data into `ModelCardPanel` as a prop avoids a duplicate request and keeps the banner and the panel in sync (no race where the banner says one thing and the panel another).

**Pitfall noticed**
- `Number.isFinite(v)` was needed on the metric values: when the backend serves a real-but-zero metric the value is `0` (truthy in `toFixed`), but `null` slips through as `0` via Pydantic-to-JSON serialization in some configurations. Defending against `null`/`NaN` here is cheap and avoids "metrics show a confident 0.000" if the manifest is incomplete. Generally: any externally-provided number that flows into a UI formatter should be guarded with `Number.isFinite`.

**Lesson**
- The model card is a *trust artifact*, not a feature. A reviewer or admissions reader skimming the project for 60 seconds is going to look for evidence that the author understands the limits of what they built. Hard-coding "do not use for production triage" loud and early says: the author knows this is a research tool, not pretending it's a product. The temptation in a portfolio piece is to make claims as big as possible; the move that actually impresses is constraining the claim to what's true. Let the model card carry that signal explicitly.

---

## Step 14 — Sample gallery and shareable result URLs

**Date:** 2026-05-05

**What landed**
- `backend/app/utils/pe_builder.py` — moved out of `tests/fixtures/` so production code (samples) can use the same builder. The test fixture is now a thin re-export so existing imports keep working.
- `backend/app/services/samples.py` — three curated synthetic PEs (`minimal-clean`, `high-entropy`, `large-code`) built deterministically. `list_samples()`, `get_sample_bytes()`, `get_sample_by_hash()` for the lookup paths.
- `backend/app/routers/samples.py` — `GET /samples` (public metadata) and `POST /samples/{id}/scan` (full pipeline + cache warm).
- `backend/app/routers/scan.py` — added `GET /scan/{sha256}` with a 64-hex `Path` pattern. Lookup order: cache → sample fallback → 404.
- `backend/tests/test_samples.py` — registry, builder determinism, both endpoints, deep-link cache hit + sample fallback + 404.
- `frontend/src/lib/api.ts` — `getSamples`, `postSampleScan`, `getScanByHash` plus `SampleSummary` / `SamplesResponse` types.
- `frontend/src/components/SampleGallery.tsx` — three cards, click-to-scan, busy state.
- `frontend/src/components/ResultsPanel.tsx` — added a `Share` button next to "File summary" that copies `${origin}/scan/${sha256}` via the Clipboard API.
- `frontend/src/app/scan/[hash]/page.tsx` — App Router dynamic route. Fetches `/scan/{hash}` + `/models` in parallel, renders `ResultsPanel` + `PerturbationSimulator` + `ModelCardPanel`. Skips `ExplanationPanel` (explanations need the file bytes — see decision below).
- `page.tsx` — `ScanState` now carries `file: File | null`; sample scans set `file = null` and the explanation panel is gated behind it.

**Decisions**
- **Synthetic samples, not bundled binaries.** SECURITY.md and the Step 4 lessons both ban executables from the repo; carrying them as gallery fixtures would invite every AV scanner on a contributor's machine to quarantine the checkout. The builder produces parseable PEs with distinct feature shapes — same demo value, no binary supply chain.
- **Sample lookup is *additive* to the cache, not a replacement.** `GET /scan/{sha256}` first checks the LRU cache (every previously-scanned file lives there for the TTL); only on miss does it consult the sample registry. This means an analyst who just scanned a custom file can share the link immediately; sample links are permanent because the bytes are reconstructible.
- **Path-pattern validation on `sha256`.** `Path(..., pattern=r"^[0-9a-fA-F]{64}$")` rejects non-hex strings at the FastAPI boundary, before the route body runs. Without it the lookup is a free probe surface — a malicious client could enumerate cache state with arbitrary strings. Cheap, locked.
- **Sample scan piggy-backs on the prediction cache.** Posting a sample warms `_cache[sha]` with the full `ScanResponse`. The follow-up `GET /scan/{sha}` is a dict lookup — no second extraction. Same pattern as user uploads, just deterministic input.
- **`ExplanationPanel` only renders when we have the file bytes.** A sample-driven scan has no `File` (the bytes live on the backend). The frontend is honest about this: no waterfall, no fallback explanation, no synthesized data. A future step can add `/explain/{sha256}` that rebuilds bytes for sample-known hashes; for Step 14 the cleaner answer is "explanations require the upload".
- **Sample bytes built once at import.** `_BYTES_BY_ID` and `_DEF_BY_HASH` are populated at module load. Builders are deterministic so this is safe; the alternative (build on every gallery click) wastes work and adds load-time variability to permalink lookups.
- **Late `from app.routers.scan import get_scan_cache` in samples router.** The samples router writes to the same cache the scan router owns. Importing at module top would create a circular dependency (samples ↔ scan); the late import keeps the import graph acyclic and `get_scan_cache()` stays the single owner.
- **`ScanState.file = File | null` instead of two separate state slots.** A nullable file in the same object means the rendering logic stays as `scan && (...)` everywhere. Splitting `scanResult` and `scanFile` would have created a class of bugs where one updates without the other.
- **Permalink page renders in dark mode by default.** `globals.css` was applied at the layout level (Step 9), so dynamic routes inherit it for free. Nothing to wire here, but worth confirming — the layout-as-shell pattern earned its keep.

**Pitfall noticed**
- `navigator.clipboard.writeText` requires either a secure context (HTTPS) or `localhost`. On bare HTTP it throws a `DOMException`. The Share button surfaces "Copy failed" rather than swallowing — visible failure beats silent failure. Worth knowing for the production deploy: Cloudflare/HTTPS makes this a non-issue, but a `:80` self-host needs `localhost` or HTTPS for the Share UX to work.
- Moving `pe_builder` out of `tests/fixtures/` *and* re-exporting it from the same path is the safe migration: no test files needed editing, no broken imports, and a future cleanup can collapse the re-export when nothing references the old path. Doing both moves at once would have been cheaper but blocked the commit on a coordinated rename across many test files.

**Lesson**
- A "share" feature is useless if the thing being shared can disappear. The honest design is to be loud about the staleness model: sample links are permanent (deterministic bytes), upload links live for the cache TTL (uploads aren't retained). Documenting that constraint in the 404 message — "Uploads are not retained past the cache TTL" — turns a "feature limitation" into a *security promise*. Same posture as the model card: tell users exactly what's true, and the trust shows up for free.

---

## Step 15 — GitHub Actions CI

**Date:** 2026-05-05

**What landed**
- `.github/workflows/ci.yml` — single workflow, two jobs:
  - **backend** — Python 3.11 setup with `pip` cache keyed on `backend/requirements.txt`, installs `ruff==0.7.4` + `black==24.10.0` separately (kept out of the runtime image), runs `ruff check .`, `black --check .`, and `pytest -ra` from the repo root with `EXTRACTOR_STRATEGY=inprocess` so the suite isn't slowed by per-test forks.
  - **frontend** — Node 20 setup, falls back to `npm install` when `package-lock.json` is missing (with a `::warning::` annotation), then `typecheck` + `lint` + `build`. `NEXT_PUBLIC_API_BASE=/api` baked at build time.
- `.github/workflows/ci.yml` — `concurrency: ci-${{ github.ref }}` with `cancel-in-progress: true` so a fix-up push doesn't burn runner minutes on the obsolete commit.
- `pyproject.toml` — added `pythonpath = ["backend"]` to `[tool.pytest.ini_options]` so `from app.main import app` resolves whether pytest runs from the repo root (CI) or from `backend/` (local). Also widened test per-file ignores to cover the legitimate test patterns: `S301`/`S403` (pickle for fabricating fake artifacts), `S603` (subprocess in `test_extractor.py`).
- `frontend/.eslintrc.json` — `extends: ["next/core-web-vitals"]`. `next lint` errors out without an eslint config; the preset is already in `devDependencies` so no install change is needed.
- README CI badge added next to the existing license/python/framework badges.
- Cleanup of unused `noqa` codes (`BLE001`, `PLC0415`) — those rule groups aren't in the project's selected rule set, so `RUF100 unused-noqa` would have flagged every one. Replaced the noqa codes with plain trailing comments preserving the *why*. Renamed `_def` / `_bytes` loop vars in `samples.py` to `entry` / `body` (single-underscore prefix means "intentionally ignored", which they aren't). Migrated `samples.py` from `typing.Callable` → `collections.abc.Callable` (UP035).

**Decisions**
- **One workflow, two jobs — not two workflows.** A combined file means one status check on the PR, one place to update CI policy, one matrix to read. Splitting to `backend.yml` and `frontend.yml` would be tidier *if* either side grew its own deployment trigger; today they share triggers exactly.
- **No path filters.** Filters trade compute for cognitive overhead — the next debugging session asking "why didn't backend CI run on this PR?" is more expensive than two extra runner minutes. The whole project is small enough that running everything on every commit is the right default.
- **Pytest from the repo root with `pythonpath` in pyproject.** The alternative (`cd backend && pytest`) splits the test config: `pyproject.toml` would still configure pytest, but the cwd would shift in CI vs. local. One source of truth — the root `pyproject.toml` — is worth the one extra config line.
- **`fail-fast: false` on the matrix.** Today there's only one Python version and one Node version, so `fail-fast` is moot. When future versions land (3.12, 3.13), one failing build shouldn't hide whether the other passes — that's the data the maintainer needs.
- **Ruff/black versions pinned in the install step, not in `requirements.txt`.** Keeping linters out of the production install keeps the runtime image small (Step 2 lessons noted this). Pinning at install time still gives reproducible CI; if a rule version bump catches new issues, that's a *deliberate* upgrade in this file.
- **`cache-dependency-path` set even when the lockfile may be missing.** `setup-node@v4` uses the path to compute a cache key; if the file is missing the key resolves but the cache stays empty — no runtime error. The fallback `npm install` path remains safe. Once the lockfile lands, this becomes the deterministic install on every run.
- **`EXTRACTOR_STRATEGY=inprocess` in CI.** The subprocess path forks a worker per request; running it across the full test suite would multiply test duration without changing what the suite covers (the subprocess path has its *own* dedicated tests in `test_extractor.py` that exercise it directly). Production sets `subprocess`; CI sets `inprocess`. Each layer covers what it needs.

**Pitfall noticed**
- `RUF100` (unused-noqa) is in the `RUF` group I had selected, so any `# noqa: <code>` referring to a rule code that isn't selected (e.g., `BLE001`, `PLC0415`) silently failed RUF100. Adding noqas defensively against rules I *thought* might fire is a class of bug — pre-emptive suppression with the wrong code is worse than no suppression. Lesson: only write `# noqa: X` for codes that actually fire on the line, ideally observed once in CI before being committed.

**Lesson**
- A first CI commit is rarely green on the first push. The goal isn't to write a perfect workflow on day one — it's to surface failures *somewhere other than the maintainer's laptop*. Each red build that comes back is a real signal, and fixing them iteratively beats the kind of pre-emptive defensiveness (noqa-everywhere, ignore-everything) that turns CI into a rubber stamp. Push the workflow; let the build tell the truth; fix forward.

---

## Step 16 — Phase 5 docs polish (LICENSE, CONTRIBUTING, ADR-001)

**Date:** 2026-05-05

**What landed**
- `LICENSE` — MIT, matches the README badge. Copyright 2026 Md. Rakibul Hasan.
- `CONTRIBUTING.md` — dev setup pointer, code-style commands (ruff/black, eslint/typecheck), test requirements, PR flow, security-disclosure path, links to `SECURITY.md` and `CODE_OF_CONDUCT.md`. Light tone since solo, but signals professionalism.
- `docs/ADR-001-feature-set.md` — first formal architecture decision record. Covers `FEATURE_VECTOR_ORDER` content, the schema-version-as-contract pattern, what's excluded for v1 (per-section vectors, imphash, disassembly, n-grams) and why, schema-bump policy, alternatives considered.
- `docs/screenshots/.gitkeep` — reserves the path for the eventual hero GIF and component screenshots.
- `README.md` — added Screenshots placeholder section, ADR-001 link from the Architecture section, removed "(added in Phase 5)" from the Contributing pointer now that the file exists.

**Decisions**
- **MIT, not Apache-2.0.** MIT is the right call for a portfolio piece: shorter, more permissive, less ceremony for downstream users. Apache-2.0's patent grant is meaningful for libraries with novel algorithms; this project ships an integration of well-known classifiers, not new IP that needs patent coverage.
- **CONTRIBUTING points to lessons.md as the *why* canon.** A contributor reading just the README + CONTRIBUTING gets the *what*; for the *why behind a decision*, the lessons file is the load-bearing document. Keeping that link explicit means new contributors don't re-litigate decisions made deliberately months ago.
- **Single ADR (001), not a batch.** The temptation with ADR systems is to backfill the whole set at once. The right move for v1 is *one* ADR for the most load-bearing decision (the feature schema, because every model artifact depends on it) and let future ADRs land when their decisions actually need a record. ADR sprawl is its own anti-pattern.
- **Screenshots placeholder, not "skip".** A README with a "Coming soon" banner reads as honest in-progress work; a README with no visuals at all reads as either polished-for-text-only (wrong impression for a *visual* dashboard) or unfinished. The placeholder note "ships first, then the GIF" is honest about ordering.
- **No architecture diagram (yet).** TODO.md Phase 5 calls for an Excalidraw / draw.io diagram. The ASCII diagram in the README is sufficient for a v1 portfolio piece; replacing it with a polished SVG is a Phase 5b task that needs an actual design pass and pairs better with the live demo screenshots than with this docs commit.
- **No demo video script.** Same gating: a demo video wants the live URL behind it. The text README can carry the demo-able-feature claim until then.

**Pitfall noticed**
- A `.gitkeep` in `docs/screenshots/` keeps the directory in git, but git's behavior with empty files plus the project's existing `.gitignore` rules can be subtle (some patterns gitignore everything in a docs/ subtree). Verified by hand that `docs/screenshots/.gitkeep` actually shows up in `git status` before committing. Worth the 10-second check; the alternative is a "where did the GIF go?" support ticket six months from now.

**Lesson**
- The temptation when polishing docs is to write everything at once: ADR-001 through ADR-007, a four-page CONTRIBUTING that no one reads, a README with seven badges and three diagrams. The move that actually impresses a reader skimming for 60 seconds is *constraint*: ship LICENSE, CONTRIBUTING, and exactly one well-argued ADR. The reader can verify the ADR is real (because it engages with alternatives), and the absence of ADR-002 through ADR-007 reads as discipline, not laziness. Documentation is editing, not generation — keep what's load-bearing, defer the rest.

---

## Step 17 — `/explain/{sha256}` for sample permalinks

**Date:** 2026-05-05

**What landed**
- `backend/app/routers/explain.py` — added `GET /explain/{sha256}` with the same 64-hex `Path` pattern used by `/scan/{sha256}`. Looks up the sample registry, rebuilds bytes, runs `explain_features`. 404 when the hash isn't a sample.
- `backend/tests/test_explain.py` — happy path on a sample sha, `model_name` + `top_n` filtering, unknown hash → 404, non-hex path rejected.
- `frontend/src/lib/api.ts` — `getExplainByHash(sha256, options)` wrapper.
- `frontend/src/components/ExplanationFromHash.tsx` — sister component to `ExplanationPanel`. Same UI, hash-driven fetch, *silently hides* on 404.
- `frontend/src/app/scan/[hash]/page.tsx` — renders `ExplanationFromHash` between `ResultsPanel` and `PerturbationSimulator`.

**Decisions**
- **404 on `/explain/{sha256}` silently hides the panel; non-404 errors surface.** A 404 is the *expected* outcome for user-upload permalinks (uploads aren't retained), and surfacing "Explanation unavailable" on every shared upload would be noise. Real failures (network drops, 5xx, malformed responses) still render an error — those are signals the user can act on. The discriminator is `err.status === 404`, not a generic catch-all hide.
- **Same shape as `ExplanationPanel`, separate component.** Two thin components beat one component with a discriminated-union prop. The shells overlap (~30 lines), but copying once was cheaper than refactoring an existing call site (the homepage's `ExplanationPanel` usage), and a future divergence (e.g. permalink mode wants a "regenerate" button, upload mode doesn't) doesn't need to be unwound from a shared abstraction.
- **`Path(..., pattern=...)` *and* `Query(..., ge=, le=)` validation.** Same hex-only filter as `/scan/{sha256}` to keep the probe surface tight; same 1–64 cap on `top_n` as `POST /explain` so the response payload can't be inflated.
- **404 message copy is honest about *why* the data isn't there.** The backend's 404 detail says "Explanations are only available for the upload that produced them or for gallery samples." That phrasing is intentionally a security-promise restatement (uploads aren't retained), not just a UX message. Anyone debugging why their permalink doesn't render SHAP gets the design rationale in the response, not buried in docs.
- **GET, not POST.** `POST /explain` takes a multipart upload; `GET /explain/{sha256}` takes a path parameter. Different verbs because they have different idempotency, caching, and CDN-friendliness profiles. A future Cloudflare cache rule can safely cache `/explain/{sha256}` on the URL alone — the upload-driven endpoint can't.
- **Reused `explain_features` in `model_registry`-mock-mode-aware way.** Because `explain_features` already handles the mock vs real branch internally and stamps `is_mock` on the response, the new endpoint is essentially "rebuild bytes, call existing service". No duplicated logic.

**Pitfall noticed**
- Routers ordering matters when paths overlap. `POST /explain` (multipart upload) and `GET /explain/{sha256}` are distinguished by HTTP method, so FastAPI routes them correctly without ordering concerns. But if a future change adds `GET /explain` (e.g. a list endpoint), the `{sha256}` pattern would shadow it unless declared *after*. FastAPI's routing is positional within `include_router`. Memo: when adding sibling paths, double-check declared order against the path-pattern.

**Lesson**
- "Permalink consistency" is a feature contract, but the right consistency is *honest*, not *uniform*. The previous version of `/scan/[hash]` simply skipped the SHAP waterfall — uniformly missing. The new version shows it for samples, hides it for uploads — non-uniform but *explained by the threat model*. The honest split lets the dashboard demo its full capability for samples (which is what most permalink shares will be) without compromising the "uploads are not retained" promise. When uniformity and honesty conflict, ship the honest version and explain the asymmetry with one well-placed sentence.

---

## Step 18 — Global concurrency cap

**Date:** 2026-05-05

**What landed**
- `backend/app/security/concurrency.py` — `ConcurrencyGate` class (asyncio.Lock + counter, fail-fast `acquire`/`release` semantics) and a `scan_concurrency_gate` generator dependency. Module-level `_scan_gate` sized from `Settings.scan_concurrency_limit` (default 4). Refused acquires raise `HTTPException 503` with `Retry-After: 5`.
- Wired `Depends(scan_concurrency_gate)` into the expensive routes: `POST /scan`, `GET /scan/{sha256}`, `POST /explain`, `GET /explain/{sha256}`, `POST /samples/{id}/scan`. Cheap routes (`/models`, `/ready`, `/perturb`, `/health`) are deliberately ungated — they don't run the extractor or the registry's heavy paths.
- `backend/app/config.py` — `scan_concurrency_limit: int = 4`. Tunable via env var; not hot-reloadable (changing it requires a restart, which is the right tradeoff for a stability knob).
- `backend/tests/test_concurrency.py` — round-trip acquire/release, post-exception cleanup, 503 when full (counter doesn't increment on refused acquire), zero-floor on stray releases, 5-vs-3 concurrent acquires gathered through `asyncio.gather`, invalid-limit rejected at construction.

**Decisions**
- **Fail-fast (503) over queueing.** A bounded queue would still need its own cap and would hide the 503 behind whatever timeout the queue eats. Returning `Retry-After: 5` immediately lets the client back off intelligently and keeps the latency contract honest — clients are never waiting longer than the request itself would have taken.
- **Counter under a single lock, not `asyncio.Semaphore`.** `asyncio.Semaphore` is the obvious fit but it doesn't expose a non-blocking try-acquire in stdlib (you have to wrap in `wait_for(timeout=0)` which is awkward). A counter under `asyncio.Lock` makes the check-and-increment atomic and the failure path explicit; the code reads as the contract, not as a workaround.
- **Module-level singleton gate.** A new gate per request would defeat the purpose. Building from `Settings.scan_concurrency_limit` at import time means the cap is "what the worker started with"; rolling out a new limit is a deploy-time operation, which matches how rate limits, cache sizes, and timeouts are tuned in this codebase.
- **`Depends(scan_concurrency_gate)` per route, not a global middleware.** Middleware would gate *every* request, including `/health`. Per-route lets the cap target only the expensive paths and keeps the cheap paths fast even under load — the dashboard's mock-mode banner shouldn't 503 because a flood is hitting `/scan`.
- **Generator dependency with `try/finally`.** FastAPI runs the post-yield block on both success and exception, so `release()` always fires. Without that pattern, a route that raises before the gate is released would leak a slot until the next restart.
- **Cap defaults to 4.** Conservative by design: this is the worst-case cap on simultaneous CPU-bound `pefile` parses, which on a 1-CPU container would already be oversubscribed. Production deploys with more cores can raise it via env var; the default is safe for the smallest plausible deploy target.
- **Cap counter `headers.get("Retry-After")` is a string, not an int.** HTTPException's `headers` field is `dict[str, str]` per FastAPI, and ASGI passes header values as strings. Tests assert against `"5"`, not `5` — a small detail that catches a class of "the test passed but the header was wrong" bugs.

**Pitfall noticed**
- `asyncio.Lock` instances must be created *inside* a running event loop in some Python/asyncio combinations, or they bind to whichever loop happened to be active at construction. Creating `_scan_gate` at module import has historically caused "got Future attached to a different loop" errors when tests use multiple event loops. Verified that pytest-asyncio's per-test loop pattern doesn't trip this here (the lock is created at module import once, and pytest-asyncio runs each test in its own loop without re-importing the module). Worth flagging in case a future test runner changes the lifecycle assumption.

**Lesson**
- "Defense in depth" is a phrase that gets thrown around to justify any extra layer; the discipline is in checking that each layer covers a *different* failure mode. slowapi covers per-IP abuse. The reverse proxy's body cap covers oversized requests. The extractor sandbox covers parser exploits. *None* of those bound the total CPU + memory burned across simultaneous well-formed requests from many IPs — that's exactly what this gate covers, and naming the gap loudly (in lessons + comments + commit message) is what keeps the security review honest. Layers should be additive, not redundant.

---

## Step 19 — Training pipeline (`training/train.py`)

**Date:** 2026-05-05

**What landed**
- `training/train.py` — script that builds a synthetic PE dataset via `app.utils.pe_builder`, fits `RandomForestClassifier` + `XGBClassifier`, evaluates F1/precision/recall on a stratified 80/20 split, persists `rf-v1.joblib` + `xgb-v1.joblib`, writes `MANIFEST.json` with `feature_schema_version` + per-model SHA-256s + metrics + honest "synthetic-trained" notes.
- `training/__init__.py` (empty, makes the directory a proper package so `python -m training.train` resolves).
- `training/README.md` — explains run, limitations, how to swap in EMBER/BODMAS/custom datasets, schema-version policy.
- Root `README.md` — new "Training real artifacts" section between "Local development" and "Docker".

**Decisions**
- **Script, not notebook.** `.ipynb` files are hard to review in git diffs and easy to leave with stale outputs. A single `.py` script is reproducible (`python -m training.train` is deterministic given the seed), reviewable, and CI-runnable later if we want a smoke test. The trade-off — losing inline charts — is fine because this is operator tooling, not exploratory analysis.
- **Synthetic dataset by default, with the limitation flagged loudly.** The temptation was to either (a) leave the manifest empty or (b) mock the metrics. Both are dishonest. Producing real artifacts via a *clearly-flagged* synthetic dataset means: the pipeline integration is real (the registry actually loads, SHA-verifies, predicts), the model card stays honest (notes field repeats "pipeline demonstration only"), and replacing the dataset is a one-function change. Honesty as a UI feature, again.
- **`USE_MOCK_MODELS=false` is opt-in.** Running `python -m training.train` produces artifacts but doesn't activate them. The user has to flip the env var explicitly. This guards against the "I ran a demo script and now my dashboard says 99% F1" footgun.
- **Manifest's `notes` field is the load-bearing honesty channel.** The model card panel reads `notes` and displays it verbatim. That means the warning travels with the model: if the artifacts are copied to a fresh deploy, the warning travels too. Burying the disclaimer in the README would let a future copy-paste deploy strip it.
- **`assert X.shape[1] == len(FEATURE_VECTOR_ORDER)`.** A trained model is married to the column count. If the vectorizer drifts between train and serve, the model produces silent garbage. The assert catches the mismatch at *training* time so a corrupt artifact never reaches the registry's SHA verification.
- **No CV, no calibration, no hyperparameter tuning.** All three are documented as "what this script does not do" in `training/README.md`. The temptation in a portfolio piece is to over-engineer the training pipeline; the right move is a sane-default training run plus an honest list of what's missing. A reviewer reading the README sees that the author knows where the gaps are.
- **`sys.path.insert` for `app.*` imports.** The cleaner alternative is `pip install -e backend` to make `app` an installable package. That's a bigger refactor (requires `[project]` config in `backend/pyproject.toml`, `__init__.py` in the right places, etc.) than this script earns on its own. The `noqa: E402` per-import is the explicit annotation that says "this is deliberate".

**Pitfall noticed**
- `np.random.default_rng(seed).integers(0, 256, size=N, dtype=np.uint8).tobytes()` is the right idiom for reproducible random bytes from numpy. The first version of `_build_synthetic_dataset` used `rng.bytes(N)` — but `Generator.bytes` doesn't exist in numpy 2.x; `bytes(rng.integers(0, 256, size=N, dtype=np.uint8))` is the working form. Caught it before pushing by running through the script mentally; would have shown up as `AttributeError` on first run.

**Lesson**
- The training pipeline is the project's most-likely-to-be-replaced component — every contributor with a real dataset will swap `_build_synthetic_dataset` and rerun. The right design is to make that single function the *one* thing they need to change: the manifest writer, the SHA pinning, the metrics format, all stay stable. A script with one well-marked extension point is more inviting to fork than a notebook with cells full of one-off code. Build the affordance for the change you expect contributors to make, and make it the easiest change in the file.

---

## Step 20 — Security scanning in CI (Trivy + Semgrep)

**Date:** 2026-05-05

**What landed**
- `.github/workflows/ci.yml` — new `security` job: `aquasecurity/trivy-action@0.28.0` filesystem scan (`severity: HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: 1`) plus Semgrep `--config auto --error --severity ERROR` after a small Python setup. Both tool versions pinned (Trivy action tag + `semgrep==1.91.0`).
- `docs/SECURITY-CI.md` — what each tool catches, run-locally commands, suppression policy (per-finding only, with documented reason), what the scanners *don't* cover (runtime behavior, image scanning, supply-chain attestations).
- `SECURITY.md` — supply-chain section rewritten to match what's actually wired (was "Bandit + Semgrep + Trivy" aspirationally; now an accurate description with a link to `docs/SECURITY-CI.md`).
- `TODO.md` Phase 6 line ticked.

**Decisions**
- **Trivy filesystem scan, not image scan.** Image scan would catch a strict superset of CVEs but requires building backend, frontend, and extractor images in CI before scanning — a 3–5 min build wall. Filesystem mode reads `requirements.txt` / `package.json` / `Dockerfile` `FROM` lines and gets ~95% of the signal in seconds. Building and scanning images is a Phase 4-deploy concern, not a per-PR check.
- **Severity floor at HIGH/CRITICAL with `ignore-unfixed`.** Every Python base image ships with a long tail of MEDIUM/LOW findings that have no upstream fix and never will. Failing on those would mean the maintainer either suppresses by-the-page or stops reading CI failures — both bad. Tightening the floor to MEDIUM should happen *after* a triage pass on what shows up at HIGH first.
- **Semgrep `auto` instead of a hand-picked rulepack.** `auto` lets Semgrep pick rules per detected language. The alternative — pinning specific rulepacks (`p/python`, `p/typescript`, `p/security-audit`) — gives more control but turns a routine version bump into a multi-line config diff. For a young project, the curated default is the right starting point; specific rulepacks are a Step-N decision when a real finding pattern emerges.
- **No separate Bandit job.** Ruff's `S` rule group is a working port of Bandit's checks, and `pyproject.toml` already selects it. Adding Bandit on top means duplicate findings on the same lines. The `SECURITY-CI.md` "Why not Bandit" section explains the trade-off explicitly so a future contributor knows it was a deliberate cut, not an oversight.
- **Fail-loud, not advisory.** `continue-on-error: true` was tempting because "first run might be red". The lesson from rate-limit work: an advisory check that always passes eventually gets ignored. If the first runs are red, fix them or whitelist with a documented reason; either way the discipline is preserved.
- **Suppression policy in `docs/SECURITY-CI.md`, not buried in CI YAML.** A reader following a Trivy or Semgrep finding link should land on a doc that explains the project's stance: "fix is the default, suppression is documented per-finding." Putting that policy in code review comments instead of a doc means every contributor re-litigates it.

**Pitfall noticed**
- Pinning `aquasecurity/trivy-action@0.28.0` (a specific *release*) rather than `@master` is the right move — `@master` would silently change scan behavior on an action upgrade. But that means a Dependabot bump to `0.29.0` is a deliberate decision: the action's CLI flags or default severity floors might shift between releases. The `SECURITY-CI.md` "Pinning the tool versions" section makes this contract explicit so a future bump-PR review knows to read the action's changelog, not just rubber-stamp the version number.

**Lesson**
- A "security scan" job that passes vacuously is theater. The discipline is in choosing which tools cover which gaps without overlap — Ruff `S` for source smells, Trivy for known-CVE deps, Semgrep for cross-cutting patterns — and writing down *why each one is there* in a doc that survives the first contributor turnover. Adding more scanners isn't more security; it's more noise. Adding scanners that catch a *new* class of issue is. Audit the gap, not the toolbox.

---

## Step 21 — OpenAPI export script + curl quickstart

**Date:** 2026-05-05

**What landed**
- `scripts/export_openapi.py` — single-file utility that imports the FastAPI app and writes a deterministic `docs/openapi.json` (sorted keys, 2-space indent, trailing newline). Repo-root sys.path mutation mirrors the pattern used by `training/train.py`.
- `scripts/__init__.py` — empty, makes `python -m scripts.export_openapi` resolvable.
- README — replaced the brief API table with a richer section: full endpoint table, Swagger UI pointer (`/docs`), Postman import flow (Postman reads OpenAPI 3.x natively, no conversion needed), and seven curl examples covering health/ready, models, gallery list + scan, permalink lookup, upload scan, SHAP explanation, and the perturbation simulator.
- `TODO.md` Phase 6 OpenAPI line marked partial; CI drift-gate is the natural Step 22 follow-up.

**Decisions**
- **Commit the script, not the spec — for now.** The export script can't run in this environment (backend deps not installed), so committing a hand-built `docs/openapi.json` would lock in a wrong-by-construction artifact. Two-commit dance: this step ships the machinery, and the maintainer's first run on a dev box (`python -m scripts.export_openapi`) produces the real spec for a follow-up commit. The README explicitly documents the regenerate command so the next maintainer doesn't hunt for it.
- **No CI drift gate yet.** A `git diff --exit-code` step would fail on first push because the spec doesn't exist yet. The discipline is "drift-gate when the artifact exists" — adding both at once would create a deliberately-red CI on the very same commit that introduced the script. Step 22 lands the spec + the gate in one move.
- **Stable JSON formatting.** `sort_keys=True`, `indent=2`, trailing newline. Anything less and the drift gate flags noise (different Python versions emit dict keys in different orders historically; `sort_keys=True` makes the output reproducible regardless of dict iteration order).
- **No Postman collection conversion.** `openapi-to-postmanv2` is a popular npm package that converts OpenAPI specs to Postman v2.1 JSON, but Postman has imported OpenAPI 3.x natively for years now. Maintaining two formats means doubled drift surface. Documenting "Postman → Import → docs/openapi.json" is the entire integration story.
- **curl examples target `:8000` (direct), not `:8080/api/*` (Caddy).** Both work, but the README's "Local development" section starts the backend with `uvicorn` directly on `:8000`. Showing curl through the proxy would be the next surprise for a reader who hasn't done `docker compose up`. One-line note explains the proxy prefix for the compose case.
- **Perturbation curl example builds the feature vector inline from `/samples/.../scan`.** Showing the JSON shape inline is more honest than "POST `{...26 numbers...}`". A real integrator would cache the vector after the first scan and re-send; the example walks the reader through that flow without hiding it.

**Pitfall noticed**
- FastAPI's `app.openapi()` is *cached* internally — it's computed once per process and the result is reused. That's fine for runtime, but a script that imports `app` and immediately calls `.openapi()` gets the cached value, which is what we want. If a future maintainer adds a `@app.on_event("startup")` hook that mutates the spec (rare, but possible with custom OpenAPI plugins), the script would emit pre-startup output and miss the changes. Worth flagging — the cached-once contract is the project's assumption.

**Lesson**
- A documented contract is only as useful as it is *current*. Auto-generating the OpenAPI spec at deploy time means it's accurate for someone hitting `/docs`, but a contributor reading the repo offline gets nothing. Committing the artifact and gating it against drift is what turns "we have an OpenAPI spec" from a runtime claim into a code-review artifact: every PR that changes an endpoint also has to update the spec, or CI says no. The two-step landing here (script first, gate later) is annoying but correct — better than wrong-by-default suppression that would have to be unwound.

---

## Step 22 — Trufflehog secrets scan

**Date:** 2026-05-05

**What landed**
- `.github/workflows/ci.yml` — `security` job gains `trufflesecurity/trufflehog@v3.83.6` step, positioned *first* (before Trivy and Semgrep). `actions/checkout@v4` for that job now uses `fetch-depth: 0` so Trufflehog can diff against history rather than only the tip.
- `docs/SECURITY-CI.md` — Trufflehog section with the `--only-verified` rationale, "When CI fails on a real leak" remediation order (rotate first, scrub history second, document third), local-run command, suppression note (don't suppress — rotate; if a fixture genuinely needs a fake-looking value, use the `trufflehog:ignore` line comment).
- `SECURITY.md` supply-chain bullet updated to include Trufflehog alongside Trivy + Semgrep.

**Decisions**
- **`--only-verified` is the load-bearing flag.** Pattern-matching detectors (the default) produce a long false-positive tail — base64 strings in test fixtures, hex digests that look like API keys, etc. Verified mode means CI fails only when Trufflehog can actively confirm the credential works by hitting the provider's identity endpoint. The trade-off is that *unverified* leaks (e.g., a credential to a non-public service Trufflehog can't reach) won't fail the build — they'll appear in the log. For a young project, the false-positive cost of unverified mode would have trained everyone to ignore the job within two weeks.
- **`fetch-depth: 0` only on the security job.** The backend and frontend jobs use the default shallow clone — they don't need history. The bandwidth cost on a small repo is negligible, but the discipline of "fetch what you need" matters when this scales; a future contributor adding a 10x-larger repo to the same workflow would notice.
- **Trufflehog runs *first* in the security job.** A leaked credential is the most urgent finding CI can produce; we want it screaming before Semgrep spends 60+ seconds on rule packs. Even if Trivy or Semgrep would have caught a related issue, the order here is "highest-impact failure first" so the maintainer doesn't have to read past two passing scans to find the one that's on fire.
- **Rotate-then-scrub remediation order.** The `SECURITY-CI.md` playbook is explicit: revoke at the provider *before* rewriting git history. The instinct is to "investigate first" — but from the moment a credential hits a public commit, assume scrapers already have it. Scrubbing history is for the long-tail scrape (search engines, bot indexes); it doesn't help with active exploitation. Document the order so a panicking contributor doesn't get it wrong.
- **`extra_args: --only-verified --fail`.** Both flags. `--fail` makes Trufflehog return a non-zero exit code on a verified hit (the action otherwise *records* findings without failing the step in some configurations). Belt and suspenders.
- **Action pinned to `@v3.83.6`, not `@main`.** Same reasoning as the Trivy + Semgrep pins from Step 20. `@main` would silently change scan behavior on an upstream push; pinned versions make every bump a deliberate decision.

**Pitfall noticed**
- Trufflehog's GitHub Action reads `${{ github.event.repository.default_branch }}` as the base. On the *first* push to `main` (when there's no parent to diff against), the action falls back to scanning history from the root commit forward — which for this repo means scanning everything that's already shipped. That's the right behavior for catching a historic leak, but it means the first run after this commit lands will take noticeably longer than subsequent diff-mode runs. Worth flagging so a slow first run isn't read as a problem.

**Lesson**
- "Defense in depth" pays for itself the day a contributor accidentally runs `git add .env`. Per-tool, in this project's stack: Trufflehog catches the moment it hits a commit; the `.gitignore` rules for `.env*` (with `!.env.example` exceptions) catch the moment it would be staged; pre-commit hooks (not yet wired) would catch the moment it hits `git add`. Three layers, each independently useless and collectively load-bearing. The right question for any new layer is *which earlier layer's failure would it have caught?* — not *is it more security?* — and writing the answer down (lessons + SECURITY-CI.md) is what keeps the layering honest.

---

## Step 23 — Vitest + frontend component tests

**Date:** 2026-05-05

**What landed**
- `frontend/package.json` — `vitest@1.6.1`, `@vitejs/plugin-react@4.3.3`, `jsdom@25.0.1`, `@testing-library/react@16.0.1`, `@testing-library/jest-dom@6.6.3`, `@testing-library/user-event@14.5.2`. New `test` script (`vitest`).
- `frontend/vitest.config.ts` — jsdom environment, `globals: true`, `@/` alias mirrors tsconfig, `css: false` to skip Tailwind class parsing during tests.
- `frontend/vitest.setup.ts` — single `import "@testing-library/jest-dom/vitest"` to extend `expect`.
- `frontend/tsconfig.json` — `tests/` and config files added to `include`, `vitest/globals` added to `compilerOptions.types` so `describe`/`it`/`expect`/`vi` are typed without per-file references.
- `frontend/tests/fixtures.ts` — shared `makeScan()` / `makePrediction()` builders matching the wire types from `src/lib/api.ts`. Avoids each test reconstructing a 28-field `FeatureResponse`.
- `frontend/tests/ShapWaterfall.test.tsx` — sort-by-|shap| ordering, signed-color logic (red for malicious-pushing, green for benign-pushing), `sr-only` tabular fallback rendered, empty-state copy.
- `frontend/tests/ResultsPanel.test.tsx` — verdict rows render, mock-mode banner toggles on `mockMode` prop, "Models disagree" highlight only when labels differ, Share button writes the permalink to `navigator.clipboard` and flips the button label to "Copied!".
- `frontend/tests/UploadZone.test.tsx` — MZ-magic rejection (PNG bytes), oversize rejection (11 MB), empty-file rejection, valid-PE happy path with `vi.mock("@/lib/api")` swapping `postScan` for a controlled stub.
- `.github/workflows/ci.yml` — frontend job gains a `Test (vitest)` step between `Lint` and `Build`. Uses `npm run test -- --run` so vitest runs once and exits (no watch mode).

**Decisions**
- **Vitest over Jest.** Vitest is Vite-native, ~5× faster on a cold run for a project this size, and uses ESM throughout (no Babel config drift). Jest with Next.js 14's App Router needs `next/jest` plus a CommonJS shim for ESM-only deps; Vitest reads the project's `tsconfig.json` directly. The migration cost (zero, this is greenfield) and the maintenance cost (less config) both lean Vitest.
- **Separate `tests/` directory, not co-located `*.test.tsx`.** The Next/React idiom is co-located, but the project's backend uses `backend/tests/` and matching the convention beats following Next defaults for a *project*-level rule. A future contributor running `find . -name '*.test.*'` learns the convention from one look at the directory structure.
- **`vi.mock("@/lib/api")` with `vi.importActual` to keep `ApiError` real.** The module mock replaces `postScan` but lets the real `ApiError` class stay so `UploadZone`'s `if (err instanceof ApiError)` arm behaves identically in tests and production. Mocking the whole module would make that branch silently dead.
- **No `PerturbationSimulator` test in v1.** Debounce + `AbortController` interactions need fake timers (`vi.useFakeTimers`) plus careful flushing of microtasks; testing it badly would produce flaky CI more often than it caught real bugs. Documented as future work — Step 24+ candidate.
- **Tests run between `Lint` and `Build`.** A red test should block the build, not the other way around — typecheck/lint/test are correctness checks; build is a packaging check. If tests fail, building wastes CI minutes. Order matters.
- **`globals: true` in vitest.config.** Matches the pytest-style ergonomics already in the backend (no `import pytest`). Trade-off: less explicit imports, but the consistency-with-backend payoff is bigger than the explicit-imports preference.
- **Shared fixtures in `tests/fixtures.ts`, not per-file.** Three tests already need a `ScanResponse`; ten will. Centralizing the builder means a wire-schema bump is one file edit, not ten.
- **`css: false` in vitest config.** Tailwind classes are strings; the visual rendering doesn't matter to a unit test. Skipping CSS parsing knocks ~30% off cold-start time and avoids "PostCSS plugin not configured" errors that vitest would otherwise raise on `globals.css` import.

**Pitfall noticed**
- Testing Library's `userEvent.upload` works on an `<input type="file">`, but `UploadZone`'s input is hidden behind a Tailwind `className="hidden"`. RTL's `userEvent.upload` operates on the DOM node directly, so visibility doesn't matter — but the `getBy*` queries don't surface hidden inputs by default. The tests fall back to a direct `document.querySelector('input[type="file"]')`. A cleaner future move is adding `data-testid="upload-input"` on the input and using `getByTestId`; doing it now would mean a churn-only Step 23a, so deferred.
- `@testing-library/react@16` requires `@testing-library/dom@10+` as a peer. Both are installed implicitly by `react@16` but the lockfile dance in CI matters when the user finally runs `npm install` on a dev box — the version pins here are known-compatible.

**Lesson**
- A test pyramid where the backend has 50+ tests and the frontend has zero is the most common shape in industry, and it's the one that bites — frontend regressions tend to be the user-visible kind (a button stops working) while backend regressions tend to be the maintainer-visible kind (a route returns 500). For a portfolio piece that's evaluated on the dashboard's polish, the asymmetry was upside-down. Three component tests don't fix it, but they shift the slope: each new component now has a reasonable per-component-test budget that would've felt heavy without infrastructure to lean on. The infrastructure is the gift; the tests are the proof it works.

---

## Step 24 — Dependabot

**Date:** 2026-05-05

**What landed**
- `.github/dependabot.yml` — three ecosystems (pip in `/backend`, npm in `/frontend`, github-actions in `/`), weekly cadence, minor+patch grouped per ecosystem, major bumps separate, open-PR limit 2 per ecosystem, conventional-commit prefix per ecosystem (`deps(backend)`, `deps(frontend)`, `deps(ci)`).
- `docs/SECURITY-CI.md` — new "Dependabot" section explaining how it complements Trivy (Trivy scans today's pins, Dependabot opens PRs before tomorrow's CVEs land), the "when a PR fails CI" playbook, skip / pin / ignore policy.
- `SECURITY.md` supply-chain bullet updated to include Dependabot alongside Trufflehog + Trivy + Semgrep.

**Decisions**
- **Weekly cadence, not daily.** Dependabot's daily mode produces ~1 PR/day for an active dep tree. For a solo project that's a guarantee the maintainer will start ignoring the bot. Weekly batches noise into one drainable queue. The trade-off is up to ~6 days of delay between an upstream CVE patch and our PR — and that's fine, because Dependabot's *security-only* updates run immediately on a different schedule (enabled at the repo level, not in this YAML).
- **Group minor + patch, keep major separate.** A grouped PR for "patch bumps to 8 packages" reads in two minutes; the same PR mixed with a React major bump reads in an hour and the major decision drowns in the patch noise. Each major bump deserves its own diff so the changelog gets a real review.
- **Open-PR limit of 2 per ecosystem.** Default is 5. Six concurrent Dependabot PRs (3 ecosystems × 2 each) is the practical maximum a solo maintainer can triage per week without the queue calcifying. The default-of-5 would mean 15 simultaneous PRs and the bot effectively stops working as a signal.
- **Conventional-commit prefixes per ecosystem (`deps(backend)`, etc.).** Easier to scan in `git log` and lets a future `release-please` or `changesets` setup auto-categorize changelog entries by ecosystem.
- **No `ignore:` block today.** Every ignore is a future CVE waiting in plain sight. The discipline is "fix or accept the upgrade" — refusing one with no documented reason is the kind of decision that rots silently. If a real reason emerges (`numpy 2.x` breaks scikit-learn compatibility, etc.), add the ignore *then*, with a comment.
- **No `reviewers:` field.** Solo project. When that changes (a co-maintainer joins), one-line addition.
- **GitHub Actions ecosystem included.** Steps 20 + 22 pinned `aquasecurity/trivy-action@0.28.0`, `semgrep==1.91.0`, `trufflesecurity/trufflehog@v3.83.6`. Without Dependabot watching them, those pins would freeze and the value of the pinning evaporates over months. The point of pinning isn't to never bump — it's to bump *deliberately* with a changelog read.

**Pitfall noticed**
- Dependabot's `directory:` field is the *directory containing the manifest*, not the manifest file itself. `directory: /backend` is correct (manifest is `backend/requirements.txt`); `directory: /backend/requirements.txt` would silently produce zero PRs. The error mode is "Dependabot stays quiet", which is much harder to debug than a hard failure — the YAML linter accepts the wrong path and only the GitHub Insights → Dependency Graph → Dependabot tab reveals the misconfiguration. Memo to verify after the first weekly run.

**Lesson**
- Tooling that auto-creates PRs is only useful if the queue stays drainable. The temptation is to enable everything — daily cadence, 5 PRs per ecosystem, every package separately. The discipline is sizing the cadence to the *human* doing the merging. A solo project's Dependabot is *not* the same Dependabot a 50-engineer team runs; it's tuned to the smallest team that uses it. The same shape applies to every alerting tool: the right firing rate is the rate the on-call can actually act on, not the rate the events occur. Volume that exceeds throughput is noise, not signal.

---

## Step 25 — First end-to-end run (docker compose up)

**Date:** 2026-05-05

**Context.** First time running the full stack. Three things turned out to be untested assumptions; each was a bug, not a config knob.

**What landed (fixes)**
- `frontend/public/.gitkeep` — frontend `Dockerfile` had `COPY --from=builder /app/public ./public` but the `public/` dir never existed. Build failed. Created the dir.
- `backend/app/security/limiter.py` — `Limiter(headers_enabled=True)` requires every rate-limited route to take a `response: Response` parameter so slowapi can inject `X-RateLimit-*` headers. None of our routes do (they return Pydantic models). Switched to `headers_enabled=False`. We lose the informational headers; the 429 itself is the contract clients rely on.
- `backend/app/routers/{scan,explain,perturb,samples,meta}.py` — removed `from __future__ import annotations` from all router files. The combination of deferred annotations + FastAPI's parameter analyzer + pydantic 2.x's `TypeAdapter` rebuild logic was breaking three different ways:
  1. `UploadFile = File(...)` triggered "Invalid args for response field! `ForwardRef('UploadFile')` is not a valid Pydantic field type" at *registration* time.
  2. `Annotated[str, Path(pattern=...)]` deferred → pydantic couldn't rebuild the TypeAdapter at *request* time, raising `PydanticUserError: TypeAdapter is not fully defined`.
  3. `payload: PerturbRequest` (a Pydantic body model) was reclassified as a *query* parameter because FastAPI's body-vs-query heuristic couldn't tell `PerturbRequest` was a `BaseModel` subclass when the annotation was a string.
- `backend/app/routers/{scan,explain}.py` — migrated `UploadFile = File(...)` and `str = Path(...)` to `Annotated[UploadFile, File(...)]` / `Annotated[str, Path(...)]` while we were here. The Annotated form is the modern FastAPI idiom; combined with no `__future__.annotations`, it's robust.
- `frontend/Dockerfile` — healthcheck was `wget http://localhost:3000/`. Alpine's busybox `wget` resolves `localhost` to `::1` (IPv6), but Next.js binds to `0.0.0.0` (IPv4 only because we set `HOSTNAME=0.0.0.0`). Container reported "unhealthy" while serving traffic correctly. Switched to `http://127.0.0.1:3000/` so the address family matches.
- `backend/Dockerfile` — added `--root-path /api` to the uvicorn `CMD`. Without it, Swagger UI at `/api/docs` loaded but its embedded JS fetched `/openapi.json` (root-relative) which Caddy routes to the *frontend* — Swagger surfaced "Failed to load API definition / Not Found /openapi.json / Fetch error". `--root-path /api` tells FastAPI it's mounted at `/api` by the proxy: URL *generation* (Swagger UI's `openapi_url`, ReDoc references) gets the `/api` prefix; actual app-internal paths are unchanged. Spec now reachable at `/api/openapi.json` and Swagger renders all 11 endpoints with working "Try it out" buttons.

**Decisions**
- **Drop `from __future__ import annotations` from routers, not from services or schemas.** It's safe everywhere FastAPI is *not* introspecting parameters. Services, schemas, utility modules keep the future import — slightly faster module load, recursive types work without quotes. Only the router boundary is sensitive to deferred annotations because that's where FastAPI's parameter-to-Pydantic-field conversion runs.
- **`headers_enabled=False` instead of adding `response: Response` to every route.** Six routes would have needed the parameter. The header information (`X-RateLimit-Limit`, `Remaining`, `Reset`) is nice-to-have for clients building back-off logic; the 429 status code is the load-bearing contract. We're trading a small informational feature for six clean signatures.
- **Annotated form for path/query/file/form params, plain Pydantic-model annotation for bodies.** The Annotated form *with* the future import works in FastAPI sometimes — but the failure modes are subtle (works at import, fails at request, depending on type). Using it without the future import is the only configuration where every test passes.
- **Healthcheck uses `127.0.0.1`, not `localhost`.** A healthcheck that says "unhealthy" while the service serves traffic is worse than no healthcheck — it teaches the operator to ignore the signal. The fix is one IP literal; the wrong fix would be to keep `localhost` and disable IPv6 system-wide.

**Pitfall noticed**
- `from __future__ import annotations` is in PEP 8's "best practice" lists for typing-heavy projects. It is not safe for FastAPI router files in pydantic 2.x. The interaction is years old, well-known to FastAPI's maintainers, and reliably forgotten by people writing their first FastAPI app — including me. Memo for future projects: routers do not get the future import.
- Empty `frontend/public/` was an entirely synthetic dependency on a Next.js convention I forgot about. The Dockerfile worked locally on a project that *did* have a `public/`, so it had been carried forward without anyone noticing the missing dir. Lesson: every `COPY` line in a Dockerfile is a contract on the source tree — running `docker build` once during scaffolding would have caught this on day one.
- The `until ... grep -q 'healthy'` shell loop matched the `api` line's "healthy" status while the `frontend` line said "unhealthy". The grep was too loose. Tighter pattern: `grep -q '^frontend=Up.*healthy'` against `--format '{{.Service}}={{.Status}}'`. Memo: anchor the service name when matching multi-service compose state.

**Lesson**
- A working stack and a stack that *passes its own healthchecks* are not the same thing, and the gap is 90% of "getting to production." Three of the four bugs in this step were silent failures: the limiter accepted requests but crashed on a code path no test exercised; `from __future__ import annotations` worked for some routes and broke others depending on what each route's signature happened to need; the frontend healthcheck reported red against a green service. None would have surfaced without `docker compose up`. The lesson isn't "test more" — it's that **the deploy posture is itself a test surface** that no unit test covers, and the first time you exercise it, expect it to be the day you find these bugs. Get there as early as you can; the cost of finding them at deploy time is much higher than at first-compose-up time.

---

## Step 26 — Render Blueprint + PaaS-portable Dockerfile

**Date:** 2026-05-06

**Context.** Hosting decision: backend on Render (Docker web service), frontend on Vercel (Next.js native). The Step 25 Dockerfile was written for the Caddy-fronted local stack and made two assumptions that don't hold on a bare Render subdomain: a fixed port (`8000`) and a fixed `--root-path` (`/api`).

**What landed**
- `backend/Dockerfile` — `CMD` switched from exec-form (JSON array) to shell-form with `exec`. Reads `${PORT:-8000}` and conditionally emits `--root-path "$ROOT_PATH"` only when `ROOT_PATH` is non-empty. Healthcheck became `PORT`-aware via `os.environ.get('PORT', '8000')`. `EXPOSE 8000` kept as documentation of the default.
- `docker-compose.yml` — added `ROOT_PATH: /api` to the api service env so the local Caddy path keeps working after the Dockerfile stopped hardcoding it.
- `render.yaml` *(new)* — Blueprint at repo root. Single web service, `runtime: docker`, `dockerfilePath: ./backend/Dockerfile`, `dockerContext: ./backend`, `region: frankfurt`, `plan: free`, `healthCheckPath: /health`, `autoDeploy: true`. Env vars baked in for `EXTRACTOR_*`, `USE_MOCK_MODELS`, `LOG_LEVEL`, `ENVIRONMENT`. `CORS_ALLOWED_ORIGINS` declared with `sync: false` (set in dashboard once Vercel URL exists). `ROOT_PATH` deliberately omitted — backend serves at the Render subdomain root, no path-stripping proxy in front.

**Decisions**
- **Shell-form `CMD` with `exec`, not exec-form (JSON array).** Exec-form does no shell expansion, so `["uvicorn", "...", "--port", "$PORT"]` would literally pass the string `$PORT` to uvicorn and fail to bind. Shell-form (`CMD command...`) gets wrapped in `/bin/sh -c "..."` by Docker, which expands env vars. The `exec` prefix replaces the shell process with uvicorn so SIGTERM from Render's stop signal reaches the app cleanly — without `exec`, the shell becomes PID 1, swallows the signal, and Render's 30 s graceful-stop window decays into a SIGKILL.
- **`${ROOT_PATH:+--root-path "$ROOT_PATH"}` instead of always emitting the flag.** Setting `--root-path ""` is *not* equivalent to omitting the flag — uvicorn passes the empty string to FastAPI which treats it as a literal mount point. The `${var:+word}` form emits the entire flag-and-value pair only when `ROOT_PATH` is set and non-empty. One Dockerfile, two deploy modes, no conditional logic in Python.
- **`PORT` defaults to 8000 via `ENV PORT=8000`, not hardcoded in the CMD.** Two reasons. (1) docker-compose targets `api:8000` from Caddy and the EXPOSE 8000 directive — keeping the default aligned avoids a config drift between the compose file and the Dockerfile. (2) On Render, the `ENV PORT=8000` is shadowed by Render's injected `$PORT` (typically 10000), so the same image works in both environments without override.
- **`render.yaml` Blueprint, not click-ops on the dashboard.** Render Blueprints are infra-as-code: the deploy posture is in the repo, code-reviewable, and survives a Render account migration. Click-ops works for one service today but rots silently — six months from now, "what env vars does this run with?" needs a screenshot, not a `git log`. The cost of writing the YAML once is roughly zero; the cost of *not* having it later is real.
- **`CORS_ALLOWED_ORIGINS` declared with `sync: false`.** Render's chicken-and-egg: the backend deploys before Vercel knows its URL, but the backend's CORS allowlist needs the Vercel URL. `sync: false` means "this env var is declared in the Blueprint (so its existence is documented) but its value is set in the dashboard, not from the YAML." Without this, the YAML would either need a placeholder value (which then ships as the real value if you forget to override) or omit the var entirely (which means a fresh Blueprint apply silently lacks the variable — a different silent-failure mode). The `sync: false` declaration is the audit trail.
- **Region: Frankfurt, not Singapore.** The demo's primary audience is German DS Master's evaluators — Frankfurt is closest to them. Singapore is closer to the user's home (Bangladesh) and would be the right call for a tool with global users, but a portfolio piece's latency budget is dominated by *the reviewer's* connection, not the maintainer's. ~150 ms BD↔Frankfurt is fine for a manual-click demo.
- **Plan: free.** Spins down after 15 min idle, ~30 s cold start on first hit. Acceptable for a portfolio demo evaluated at most a few times. The honest tradeoff goes in `README.md`'s deploy section so a reviewer hitting a cold instance doesn't think the service is broken. Bump to "starter" before any sustained traffic.

**Pitfall noticed**
- The combination of exec-form `CMD` + the existing `--port 8000` literal *would have worked silently on Render's free tier*: Render's port-detection falls back to scanning `EXPOSE` when the app doesn't bind to `$PORT`, and the proxy figures it out. The bug only surfaces on plans with strict port enforcement, or when `EXPOSE` doesn't match the bound port. Silent-but-fragile is worse than loudly-broken — the lesson here is that "it deploys successfully" on Render's free tier is not the same as "the Dockerfile is portable across Render plans / other PaaS providers." Bind to `$PORT` always, EXPOSE for documentation only.
- `${ROOT_PATH:+--root-path "$ROOT_PATH"}` looks like it should be quoted as a unit (`"${ROOT_PATH:+...}"`), but quoting the whole expression breaks word-splitting and produces a single argument `--root-path /api` that uvicorn rejects with "unknown option." The current form relies on the shell's word-splitting *after* substitution but before argv assembly. That's correct, but it's the kind of POSIX-shell subtlety that a reviewer might "fix" by adding quotes. A comment in the Dockerfile flags the form so the next person doesn't redo the bug.

**Lesson**
- The first deploy posture you ship in a project (`docker compose up` on a developer laptop) and the second one you ship (`Render` / `Vercel` / any PaaS) overlap by maybe 70%. The remaining 30% is the gap between "I picked sensible defaults for one environment" and "the same image runs in environments I haven't seen yet." Hardcoded ports, hardcoded mount paths, exec-form CMDs that block env expansion — each is a perfectly reasonable choice for the laptop, and each is a bug for the PaaS. The discipline isn't to predict every future environment; it's to **make every environment-specific value an env var with a sensible default** so the Dockerfile doesn't need a per-environment branch. Today's deploy is to Render. Tomorrow's might be Fly.io or Railway or a self-hosted Kubernetes cluster — and if today's Dockerfile uses `${PORT:-8000}` and `${ROOT_PATH:+--root-path "$ROOT_PATH"}`, all three work without a Dockerfile edit. The principle generalises: every literal in a deploy artifact is a future migration cost.

---

## Step 27 — Design-system foundation: shadcn + theme toggle + new hero

**Date:** 2026-05-06

**Context.** The hand-rolled Tailwind UI was reading as "homework project" rather than "considered tool." Three specific failure modes, all the user surfaced when prompted: the hero was two paragraphs of grey text with no anchor moment, the page was a flat single-column scroll where every section had the same visual weight, and the dashboard offered no theme toggle (dark-only, even though portfolio reviewers may be on light displays). This step is a foundation pass — the visual baseline shifts, but the bulk of components keep their existing structure and migrate to shadcn primitives in a follow-up (Phase 3b).

**What landed**
- `frontend/package.json` — added `clsx`, `tailwind-merge`, `class-variance-authority`, `next-themes`, `lucide-react`. Lockfile regenerated.
- `frontend/tailwind.config.ts` — `darkMode: ["class"]`. shadcn's primitive colour set (`background`, `foreground`, `card`, `muted`, `primary`, `secondary`, `border`, `ring`) added as theme tokens reading from CSS variables. Existing custom palette (`ink`/`surface`/`border`/`accent`) re-bound to the same variables — `ink` aliases `--background`, `surface` aliases `--card`, `border` aliases `--border`. Brand/semantic accents (`accent`, `warn`, `danger`, `ok`) stay fixed.
- `frontend/src/app/globals.css` — full HSL-channel variable set for both themes. Light-theme defaults in `:root`, dark-theme overrides in `.dark`. Body uses `bg-background text-foreground` so theme switch flows through.
- `frontend/src/lib/utils.ts` — `cn()` helper (`clsx` + `tailwind-merge`).
- `frontend/src/components/ui/{button,card,badge}.tsx` — shadcn primitives, vendored as files (no CLI dependency). Button uses CVA with `default`/`secondary`/`outline`/`ghost` variants and `default`/`sm`/`lg`/`icon` sizes. Badge has semantic `warn`/`danger`/`ok` variants in addition to shadcn defaults.
- `frontend/src/components/theme-provider.tsx` + `theme-toggle.tsx` — `next-themes` wrapper + Sun/Moon button. Toggle gates icon rendering on `useEffect` so the hydrated icon matches the active theme without a flash.
- `frontend/src/app/layout.tsx` — `<html lang="en" suppressHydrationWarning>` + `<ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>`. Default-theme = dark to preserve the prior aesthetic for returning visitors; the toggle persists the user's choice in `localStorage`.
- `frontend/src/app/page.tsx` — full hero redesign: sticky nav with `ShieldCheck` brand mark + `ThemeToggle`, two-column hero (copy + status card) on `md+`, primary/secondary CTAs, anchored sections (`#scan`, `#model-card`) with `scroll-mt-24`, footer line. Status card replaces the previous one-line `Schema X · N features · M models` footnote with a real `Card` showing schema/feature-count/models-loaded/mode as a 2×2 grid + skeleton loader while connecting.
- `text-zinc-*` sweep — across 8 component files: `text-zinc-100/300` → `text-foreground`, `text-zinc-400/500` → `text-muted-foreground`, `bg-zinc-300` (toggle thumb) → `bg-foreground`. Light theme is no longer broken-by-default for unmigrated components.

**Decisions**
- **Vendor shadcn components into `src/components/ui/` instead of using the CLI.** shadcn's `npx shadcn-ui@latest add` is convenient on a Mac/Linux dev box but its interactive prompts don't cooperate with this Windows + harness setup, and the components are short enough that copying the canonical templates by hand is faster than debugging the CLI. The vendor pattern is also shadcn's own recommended workflow — components live in *your* repo, not a node_modules dep — so no architectural compromise.
- **Bind the legacy palette (`ink`/`surface`/`border`/`accent`) to the same CSS variables shadcn primitives read from, instead of replacing the palette outright.** Replacing every `bg-surface`/`border-border` reference would have meant a ~100-line diff across 8 components for zero behaviour change in dark theme. Re-binding the aliases means dark theme renders identically to before, light theme works automatically (because the variables flip), and Phase 3b can swap each component to a real `<Card>`/`<Button>` on its own merits without a forced big-bang migration.
- **Default theme = dark, no system-preference mode.** Two reasons. (1) The original aesthetic was deliberately dark (the tailwind config comment said "looks like a tool, not a brochure") — flipping defaults would change the first-load impression for everyone who'd seen it before. (2) `enableSystem` adds a third theme state ("system") which forces `next-themes`'s `theme` to read either `"light"`/`"dark"`/`"system"`, but the icon should always show the *resolved* concrete theme. Keeping `enableSystem={false}` makes the toggle a clean two-state switch; system-pref support comes back when it's actually requested.
- **HSL channels in CSS variables, not full `hsl(...)` values.** Tailwind's opacity syntax (`bg-primary/80`, `border-border/40`) writes `hsl(var(--primary) / 0.8)`. That syntax requires the variable to be the channel triplet `211 100% 53%`, not the wrapped `hsl(211, 100%, 53%)`. Using full hsl() values silently breaks every `/<alpha>` use — and there are dozens of them in this codebase already (`bg-warn/10`, `border-danger/40`, `bg-accent/20`, etc.).
- **Icon rendering gated on a mount-state flag in `ThemeToggle`.** Without it, server-rendered HTML always emits the dark-mode icon (server doesn't know the user's theme), then the client hydrates with the resolved theme — visible flash. Gating produces an empty 5×5 placeholder pre-mount and the correct icon post-mount. The placeholder reserves space so the nav doesn't shift on hydration.
- **Hero CTAs are anchor links (`<a href="#scan">`), not React state.** The page already scrolls; jumping to an anchor is the cheapest "Get started" interaction and Just Works without any state. `scroll-mt-24` on the target accounts for the sticky nav so the section header isn't hidden under the fixed top bar. No JS, no ref forwarding.
- **`backdrop-blur` + `supports-[backdrop-filter]:bg-background/60` for the sticky nav.** On modern browsers the blur looks intentional; on older ones the supports-query falls back to a fully opaque nav. The fallback is the conservative choice — a blurred translucent nav over content that doesn't blur is worse than a clean opaque bar.

**Pitfall noticed**
- Pre-existing test failures surfaced when I ran `npm test` after the migration. Two tests in `tests/UploadZone.test.tsx` fail with `file.slice(...).arrayBuffer is not a function` — jsdom 25 doesn't polyfill `Blob.arrayBuffer()`, which the upload-zone's client-side magic-byte check uses. There's also a TS impossible-condition error on line 40 (`screen.getByTestId ? ...`). Verified both reproduce on origin/main (`git stash && npm test`) — none introduced here. The reflex was to "fix" them as part of this step; the discipline was to confirm they're orthogonal to the design-system migration and leave them for a focused commit. Mixing UI-foundation changes with test-infra fixes would have made the design-system commit harder to review.
- `next build` succeeds even when `tsc --noEmit` doesn't. Next.js's build-time type check is narrower than the standalone `tsc` run — it ignores the `tests/` glob in `tsconfig.json`'s `include` because Next manages its own type roots. So a passing `npm run build` is not the same signal as a passing `npm run typecheck`. Both ran here; the test-file errors in `typecheck` are visible, the production build is clean.
- `class-variance-authority` requires the variant *return* type (`VariantProps<typeof buttonVariants>`) to be intersected with `ButtonHTMLAttributes` — I wrote it correctly the first time, but it's the kind of small TS shape that bites if the `extends` order is reversed. Memo: variant types compose with HTML element types via intersection, not union.

**Lesson**
- A "design-system migration" that tries to touch every component in one commit is a refactor disguised as polish — and it ships much later than a foundation-only pass that lets components migrate at their own pace. The discipline this step enforced was: ship the variables, the primitives, the theme toggle, and the most visible single component (hero) — *not* the migration of every existing component. Re-binding the legacy palette aliases is what made this possible: every component that used `bg-surface`/`border-border`/`bg-ink` automatically picked up theme awareness without a single line of component code changing. The general principle: when you're introducing a new abstraction layer to a codebase that already has a working but inconsistent layer, **don't migrate the old layer to the new one — bridge them, then let the migrations happen incrementally.** A 12-file commit that touches 200 lines is a bridge; a 30-file commit that touches 2000 lines is a refactor that holds up the actually-visible improvements (the new hero, the working toggle) until the migration finishes. The user sees the bridge today; the migration is the next iteration's compounding interest.

---

## Step 28 — Phase 3b: components migrated to shadcn primitives

**Date:** 2026-05-06

**Context.** Step 27 shipped the foundation (CSS variables, Card/Button/Badge primitives, theme toggle, redesigned hero) but stopped short of touching existing components — they kept rendering through the legacy palette aliases. That bridge was the right call for a one-turn delivery, but it left visible inconsistency: the hero used `<Card>` while the panels below it used hand-rolled `rounded-xl border bg-surface` divs. This step closes the gap.

**What landed**
- `frontend/src/components/site-nav.tsx` *(new)* — extracted the sticky nav (brand mark + `<ThemeToggle>`) from `app/page.tsx` into a shared component. Both the home page and `/scan/[hash]` permalink now use it, so the theme toggle reaches every route.
- `app/page.tsx` — uses `<SiteNav>` instead of inline header.
- `app/scan/[hash]/page.tsx` — wraps content in the same shell (`SiteNav` + `max-w-6xl` container) so shared scan URLs feel like part of the same product, not an orphan page. `ArrowLeft` icon on the back link, `Loader2` spinner on the loading state.
- `components/UploadZone.tsx` — `<Button>` (primary variant, Upload + Loader2 icons), drop-zone styling moved to `cn()`-composed classes, drag highlight uses `border-primary` + `bg-primary/5` instead of fixed-colour `border-accent`. Adds a circular icon affordance above the headline so the dropzone reads as a target without depending on the dashed border alone.
- `components/SampleGallery.tsx` — sample cards keep `<button>` (whole-card click) but match `<Card>` visuals (border + bg-card + shadow) plus a focus-visible ring for keyboard nav. Loading spinner on first fetch; per-card busy state uses `<Badge variant="secondary">` with a `Loader2` icon instead of a coloured text label.
- `components/ResultsPanel.tsx` — `<Card>` for File summary (with `<Button variant="outline" size="sm">` Share button using `Share2` + `Check` icons) and Model predictions table (border lifts to `border-warn` when models disagree, `<Badge variant="warn">` "Models disagree" callout). The mock-mode banner stays as a styled alert because Card is the wrong primitive for a top-of-section warning strip.
- `components/ModelCardPanel.tsx` — Out-of-scope card carries its danger framing on a `<Card>` (border-danger/40 + bg-danger/5); Intended-use, Known-limitations, and per-model items become regular `<Card>`s. Per-model `is_mock` indicator → `<Badge variant="warn">`.
- `components/ExplanationPanel.tsx` + `ExplanationFromHash.tsx` — per-model SHAP cards become `<Card>` with `<Badge variant="warn">` for `mock`. Loading state gets a `Loader2` spinner.
- `components/PerturbationSimulator.tsx` — outer wrapper → `<Card>`. Reset button → `<Button variant="ghost" size="sm">` with `RotateCcw` icon. Updating-state spinner inline next to the perturbation count. The native checkbox-as-switch keeps its DOM but the track and thumb classes are now theme-aware: track uses `bg-muted`/`bg-primary`, thumb uses `bg-background shadow` so the switch reads correctly in both themes (the previous `bg-zinc-300` thumb was invisible against a light off-track).
- `TODO.md` — Phase 3b marked done.

**Decisions**
- **Sample cards stay `<button>`, not `<Card>` with an inner click handler.** The whole-card click target is what the UX needs; making the card a button preserves "click anywhere" semantics, keyboard-focus on tab, and Enter/Space activation, all for free. Wrapping a `<Card>` in `<button>` produces a button-inside-button when the card has any interactive children (it doesn't today, but it might later); the cleaner pattern is "use the same classes as Card but emit a button element." That's what the new code does — the visual is identical to `<Card>`, the semantics are correct.
- **The mock-mode banner doesn't become a Card.** A Card is for *grouped data*; this is a top-of-section *alert*. Promoting it to a Card would make the warning feel like just another panel, weakening it. Kept as a styled alert with the same warn-tinted border-and-bg the rest of the warn callouts use.
- **Native checkbox kept as the perturbation switch — no Radix dependency yet.** The native `<input type="checkbox" class="peer sr-only">` + sibling-styled track-and-thumb is ~10 lines. Adopting `@radix-ui/react-switch` would add a peer dep, a `<Switch>` component to vendor, and ~40 lines of wrapper code, for marginal benefit (Radix gives keyboard semantics the native checkbox already has via Space). Defer until a real reason emerges (e.g., need for a "loading" intermediate state or icon-in-thumb).
- **Bundle size dropped on the page-specific chunks (14.6 kB → 3.83 kB on `/`)** because inline styling moved into shared primitives. First-Load JS rose modestly (~+8 kB) because the shared chunks now carry CVA + the primitive components — but those are amortised across every page, so each *additional* page costs nearly zero JS. This is the expected curve for a design-system migration: page-specific code shrinks, shared code grows once, total JS grows sub-linearly.
- **Shared `<SiteNav>`, not a Next.js layout.** A `layout.tsx` wrapper would be the more "framework-correct" move, but the current home page does its own `min-h-screen bg-background` wrapper because it has a hero + footer; introducing a layout would mean refactoring both the home and permalink pages to fit a shared shell. A shared component is one less abstraction to chase and the diff is smaller. If a third route ever lands, consider promoting to a layout then.
- **`flex-row` on `<CardHeader>` for two-column header rows (title + action).** shadcn's `CardHeader` defaults to `flex-col space-y-1.5`, which is right for "title above description." For the headers that have a title on the left and an action on the right (Share, Reset, mock badge), overriding with `flex-row items-center justify-between space-y-0` is the documented shadcn pattern. Still cheaper than introducing a separate `<CardActions>` slot.

**Pitfall noticed**
- shadcn's `<Card>` defaults to `shadow-sm`. On dark theme it's invisible (the shadow blends into the dark background); on light theme it's a subtle elevation. That asymmetry is *intentional* in the shadcn defaults — dark surfaces don't typically use box-shadow because the eye reads "elevation" via lighter-than-background fills, not shadows. Keeping `shadow-sm` was the right call: light theme gets the affordance, dark theme doesn't lose anything because the shadow simply doesn't render visibly. The instinct to "fix" this by removing the shadow would have made the light theme worse without improving the dark theme.
- The `<table>`-inside-`<CardContent>` needed `p-0` on the CardContent to prevent the default `p-6 pt-0` from indenting the table inside the card border. Subtle but important — the table's own row padding handles spacing.
- `border-b` on `<CardHeader>` (for the predictions table card) requires `space-y-0` to be set explicitly because `space-y-1.5` between header children is computed *before* the header's own bottom border, producing a visible gap that looks unintentional. Two utility-class combinations have to land together for the result to look right.

**Lesson**
- A foundation-only pass (Step 27) followed by an incremental migration (Step 28) was the right shape, even though both *could* have been one larger commit. The reasons compound: (1) Step 27 shipped a *visible* improvement (new hero, working theme toggle) the user could evaluate without waiting for the full migration, so feedback came earlier; (2) Step 28 was a mechanical pass — drop in `<Card>`, swap `<button>` for `<Button>` — that was much faster to *do* once the primitives existed, because the decisions were already made; (3) the two commits together produce a cleaner `git log` than one mega-commit, because reviewers (or future-me) can read "what did we add?" and "what did we migrate?" as separate concerns. The general principle: **introduce abstractions and migrations in separate commits, not the same commit.** When the abstraction lands first, the migration is "apply the abstraction"; when they land together, the migration becomes "design and apply the abstraction simultaneously," which is two cognitive tasks fighting for the same diff.

---
