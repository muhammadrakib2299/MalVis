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
