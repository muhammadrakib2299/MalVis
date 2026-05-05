# MalVis — Build TODO

> Target ship date: 3 weeks from start. Live URL + demo video before German DS Master's application (Aug 2026).

---

## Phase 0 — Decisions to make first

- [ ] **Trained models** — confirm location of `.pkl` / `.joblib` files for RF + XGBoost from the published paper. If not saved → add a `training/` notebook that re-trains from the original dataset (EMBER / BODMAS / your own) and pickles the artifacts.
- [ ] **Frontend framework** — Next.js (recommended, matches Combosoft stack) vs Vite + React (lighter SPA). Default plan below assumes Next.js.
- [ ] **PE feature extractor** — pick a library: `pefile` (pure Python, simple) vs `LIEF` (richer, multi-format). Default: `pefile` for v1.
- [ ] **Hosting** — Railway / Fly.io / Render for backend; Vercel for frontend. Pick before Phase 4.
- [ ] **Dataset license** — confirm you can publicly link to the dataset used in the paper, or document how a user supplies their own.
- [ ] **Sandbox approach for the parser** — pick one: (a) separate container with `--network=none --read-only`, (b) gVisor runtime, (c) Firecracker microVM. Default: (a) for v1; document in `SECURITY.md`.
- [ ] **Sample binaries for the live demo** — pick 3–5 hash-pinned PEs the public can scan without supplying their own (EICAR test file, harmless OSS executables, license-cleared known-malicious sample if available). Without this the live demo is a dead-end for casual visitors.

## Phase 1 — Repo + skeleton (Day 1)

- [ ] `git init`, add `.gitignore` (Python, Node, models, .env, datasets)
- [ ] Create folder structure:
  ```
  backend/
    app/
      main.py
      models/            loaded artifacts go here at runtime
      routers/           scan.py, explain.py, perturb.py
      services/          pe_features.py, model_registry.py, shap_runner.py
      schemas/           pydantic request/response models
    tests/
    Dockerfile
    requirements.txt
  frontend/              Next.js app
  notebooks/             training + experimentation
  artifacts/             trained model pickles (gitignored)
  docker-compose.yml
  .github/workflows/ci.yml
  ```
- [ ] Add `requirements.txt`: fastapi, uvicorn, scikit-learn, xgboost, shap, lime, pefile, pydantic, python-multipart, joblib, numpy, pandas, slowapi (rate limiting)
- [ ] Add `pyproject.toml` with ruff + black config
- [ ] Create empty FastAPI `main.py` with `/health` endpoint, verify `uvicorn` boots
- [x] Add `SECURITY.md` describing the threat model and controls (already drafted)
- [ ] Add `CODE_OF_CONDUCT.md` (Contributor Covenant, drop-in)
- [ ] Add `.github/SECURITY.md` symlink or copy so GitHub surfaces the policy

## Phase 2 — Backend core (Days 2–5)

- [x] **Feature extraction** — `services/pe_features.py`:
  - [x] Parse PE header with `pefile`
  - [x] Extract feature vector matching the schema your paper used (header fields, section entropy, imports, etc.)
  - [x] Unit test with 2–3 sample PE files (use harmless test binaries — Windows `notepad.exe` copy, etc.) — using a programmatic minimal-PE builder rather than shipping a binary fixture, see `tests/fixtures/pe_builder.py`
- [x] **Model registry** — `services/model_registry.py`:
  - [x] Load RF, XGBoost (and optional ANN) at startup — *real loader implemented; mock predictors active by default until trained pickles land (Phase 0 blocker)*
  - [x] Singleton pattern, lazy load
- [ ] **Endpoints** — `routers/`:
  - [x] `POST /scan` — accepts PE upload (multipart), returns predictions from all models + confidence — *predictions wired through registry; mock-mode flagged honestly in response metadata*
  - [ ] `POST /explain` — returns SHAP values for a given file (waterfall-ready format)
  - [ ] `POST /perturb` — accepts a perturbation spec (e.g. "flip import X"), returns prediction delta
  - [x] `GET /models` — lists available models + metadata (paper citation, F1, training date) — *also exposes `feature_order` so the frontend doesn't hardcode the schema*
- [ ] **Security hardening** (non-negotiable — see `SECURITY.md`):
  - [ ] 10 MB upload cap enforced at reverse proxy *before* FastAPI sees the request
  - [x] Magic-byte (`MZ`-prefix) check — reject anything else with `400` before the parser runs
  - [x] Never write the binary to persistent disk; process in memory or per-request tmpfs
  - [x] Per-IP rate limiting via `slowapi` (10/min, 100/day), global concurrency cap on `/scan` — *10/min limit applied to `/scan`; global concurrency cap still TODO*
  - [ ] Run feature extraction in a separate container: `--network=none --read-only`, non-root, dropped caps, `no-new-privileges`, 512 MB / 1 CPU / 30 s limits
  - [x] CORS locked to the official frontend origin
  - [x] Loader refuses any model pickle whose SHA-256 is not in a signed manifest — *enforced in `_load_real`; tested in `test_model_registry.py::test_real_loader_refuses_sha_mismatch`*
- [ ] **SHA-256 hash cache** — LRU (≤1000 entries, 1 h TTL) mapping `hash → cached prediction`; instant return on repeat scans, big perceived-speed win
- [~] **Tests** — pytest covering each endpoint with fixtures, including malformed-PE and rate-limit cases — *`/scan` happy path, malformed PE, oversize, garbage all covered; rate-limit + remaining endpoints to follow*

## Phase 3 — Frontend dashboard (Days 6–10)

- [ ] `npx create-next-app@latest frontend --ts --tailwind --app`
- [ ] Pages / components:
  - [ ] **Upload zone** — drag-and-drop PE file, progress state, error toasts
  - [ ] **Results panel** — multi-model comparison table (RF vs XGBoost vs ANN): prediction, confidence, latency
  - [ ] **SHAP waterfall** — D3.js component, top-N features driving the decision
  - [ ] **Feature importance bar chart** — global vs per-prediction view toggle
  - [ ] **Adversarial perturbation simulator** — sliders/toggles to flip features, live re-prediction, side-by-side delta
  - [ ] **Model metadata card** — paper link, dataset, training F1/precision/recall
  - [ ] **Model card panel** — honest limitations, known failure modes, "do NOT use for production triage" disclaimer, calibration plot. Lines up with EU AI Act / NIST AI RMF expectations
  - [ ] **"Try a sample" gallery** — 3–5 pre-vetted, hash-pinned binaries one click away, so visitors without a PE on hand can still see the demo
  - [ ] **Disagreement view** — when RF and XGBoost disagree, surface it prominently with a side-by-side SHAP-diff (this is the most interesting case and the most demo-able)
  - [ ] **"Why this feature matters" tooltips** on every PE feature in the SHAP plot, pulling explainability through to feature-meaning, not just feature-weight
  - [ ] **Shareable result URLs** — `/scan/{hash}` deep link so users can share specific results
  - [ ] **Accessibility pass** — alt text on D3 charts, keyboard nav, tabular fallback view of SHAP values
- [ ] API client wrapper (`lib/api.ts`) with typed responses
- [ ] Loading + error states everywhere
- [ ] Mobile-responsive (Tailwind breakpoints)

## Phase 4 — Containerization + deploy (Days 11–13)

- [ ] **Backend Dockerfile** — multi-stage, non-root user, slim base
- [ ] **Frontend Dockerfile** — `next build` output mode `standalone`
- [ ] **docker-compose.yml** — backend + frontend + reverse proxy (Caddy or nginx) for local dev
- [ ] Deploy backend to Railway/Fly.io, point frontend env var at it
- [ ] Deploy frontend to Vercel
- [ ] Custom subdomain on devrakib.com → `malvis.devrakib.com`
- [ ] Add `robots.txt`, basic OG image for sharing
- [ ] **Cloudflare WAF** in front of the public endpoints — bot-fight mode + rate-limit rules; free tier covers everything we need

## Phase 5 — Documentation + polish (Days 14–17)

- [ ] **README.md** — already drafted; update with:
  - [ ] Live demo URL
  - [ ] Architecture diagram (Excalidraw / draw.io)
  - [ ] Screenshot / GIF of the dashboard
  - [ ] "Built on" link to the published paper
- [ ] **Architecture decision record** — `docs/ADR-001-feature-set.md` explaining feature choices vs paper
- [ ] **CONTRIBUTING.md** — light, since it's a solo project but signals professionalism
- [ ] **MIT or Apache-2.0 LICENSE**
- [ ] **Demo video** — 90 seconds, screen recording, Loom or YouTube unlisted, embedded in README
- [ ] **Animated GIF / screencast** in the README hero — capture the moment Phase 3 lands, don't wait for full polish; this is the single highest-leverage portfolio asset
- [ ] Pin repo on GitHub profile, add topics: `cybersecurity`, `xai`, `shap`, `malware-detection`, `fastapi`, `nextjs`

## Phase 6 — Stretch goals (post-launch, if time)

- [ ] **REST API key auth** + rate limiting (positions it as SIEM-integrable)
- [ ] **OpenAPI spec** export + Postman collection
- [ ] **Batch scan** endpoint accepting ZIP of PEs
- [ ] **Model versioning** — A/B compare model v1 vs v2 in UI
- [ ] **Telemetry** — Plausible or PostHog (privacy-friendly) to track usage for the application essay
- [ ] **Blog post** on devrakib.com — "Productionizing my malware paper" — strong essay material
- [ ] **GitHub Actions CI** — lint + test on every PR
- [ ] **Counterfactual explanations** via [DiCE](https://github.com/interpretml/DiCE) — "the smallest change that flips the verdict." More analyst-actionable than SHAP alone
- [ ] **YARA rule export** — given a SHAP-explained malicious verdict, generate a draft YARA rule from the top features. Closes the loop from "ML found it" to "your rule engine can find it." Killer feature for SOC users
- [ ] **MITRE ATT&CK tagging** — map detected behaviors (process injection, persistence, etc.) to ATT&CK technique IDs. Instant credibility with blue teams
- [ ] **MLflow** for model versioning + experiment tracking (local file backend is fine — demonstrates ML-engineering maturity)
- [ ] **LLM-generated narrative explanation** — Claude API turns SHAP output into human-readable prose ("imports `VirtualAllocEx` and `WriteProcessMemory`, commonly used for process injection — T1055"). Strict grounding on SHAP values, no free-form hallucination
- [ ] **Bounded adversarial attack automation** — FGSM-style on tabular features, capped to N-feature perturbations, returns the smallest flip. Strongest single demo moment for the application essay
- [ ] **Streaming SHAP** — server-sent events, render the waterfall as values arrive; feels magical
- [ ] **Trivy + Bandit + Semgrep** in CI — being a security tool that scans itself is a clean talking point
- [ ] **OpenTelemetry → Grafana Cloud free tier** + **Sentry** for the frontend — real telemetry, gives you usage data for the application essay

---

## Application-prep checklist (parallel to build)

- [ ] Update CV with live MalVis URL once Phase 4 ships
- [ ] Add MalVis to LinkedIn featured projects
- [ ] Mention in motivation letter as evidence of "research → product" capability
- [ ] Reference MalVis in scholarship applications (DAAD, Deutschlandstipendium)

---

## Open questions / blockers

- [ ] Are the trained pickles available, or do we need to retrain?
- [ ] Which dataset citation goes in the README (paper-original vs public benchmark)?
- [ ] Do you want the adversarial simulator to support automated attacks (e.g., FGSM-style on tabular features) or only manual feature flips?
