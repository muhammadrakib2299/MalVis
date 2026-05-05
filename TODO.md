# MalVis — Build TODO

> Target ship date: 3 weeks from start. Live URL + demo video before German DS Master's application (Aug 2026).

---

## Phase 0 — Decisions to make first

- [ ] **Trained models** — confirm location of `.pkl` / `.joblib` files for RF + XGBoost from the published paper. If not saved → add a `training/` notebook that re-trains from the original dataset (EMBER / BODMAS / your own) and pickles the artifacts.
- [ ] **Frontend framework** — Next.js (recommended, matches Combosoft stack) vs Vite + React (lighter SPA). Default plan below assumes Next.js.
- [ ] **PE feature extractor** — pick a library: `pefile` (pure Python, simple) vs `LIEF` (richer, multi-format). Default: `pefile` for v1.
- [ ] **Hosting** — Railway / Fly.io / Render for backend; Vercel for frontend. Pick before Phase 4.
- [ ] **Dataset license** — confirm you can publicly link to the dataset used in the paper, or document how a user supplies their own.

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
- [ ] Add `requirements.txt`: fastapi, uvicorn, scikit-learn, xgboost, shap, lime, pefile, pydantic, python-multipart, joblib, numpy, pandas
- [ ] Add `pyproject.toml` with ruff + black config
- [ ] Create empty FastAPI `main.py` with `/health` endpoint, verify `uvicorn` boots

## Phase 2 — Backend core (Days 2–5)

- [ ] **Feature extraction** — `services/pe_features.py`:
  - [ ] Parse PE header with `pefile`
  - [ ] Extract feature vector matching the schema your paper used (header fields, section entropy, imports, etc.)
  - [ ] Unit test with 2–3 sample PE files (use harmless test binaries — Windows `notepad.exe` copy, etc.)
- [ ] **Model registry** — `services/model_registry.py`:
  - [ ] Load RF, XGBoost (and optional ANN) at startup
  - [ ] Singleton pattern, lazy load
- [ ] **Endpoints** — `routers/`:
  - [ ] `POST /scan` — accepts PE upload (multipart), returns predictions from all models + confidence
  - [ ] `POST /explain` — returns SHAP values for a given file (waterfall-ready format)
  - [ ] `POST /perturb` — accepts a perturbation spec (e.g. "flip import X"), returns prediction delta
  - [ ] `GET /models` — lists available models + metadata (paper citation, F1, training date)
- [ ] **Validation** — file size limit (e.g. 10MB), MIME/magic-byte check, reject non-PE files cleanly
- [ ] **Tests** — pytest covering each endpoint with fixtures

## Phase 3 — Frontend dashboard (Days 6–10)

- [ ] `npx create-next-app@latest frontend --ts --tailwind --app`
- [ ] Pages / components:
  - [ ] **Upload zone** — drag-and-drop PE file, progress state, error toasts
  - [ ] **Results panel** — multi-model comparison table (RF vs XGBoost vs ANN): prediction, confidence, latency
  - [ ] **SHAP waterfall** — D3.js component, top-N features driving the decision
  - [ ] **Feature importance bar chart** — global vs per-prediction view toggle
  - [ ] **Adversarial perturbation simulator** — sliders/toggles to flip features, live re-prediction, side-by-side delta
  - [ ] **Model metadata card** — paper link, dataset, training F1/precision/recall
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
- [ ] Pin repo on GitHub profile, add topics: `cybersecurity`, `xai`, `shap`, `malware-detection`, `fastapi`, `nextjs`

## Phase 6 — Stretch goals (post-launch, if time)

- [ ] **REST API key auth** + rate limiting (positions it as SIEM-integrable)
- [ ] **OpenAPI spec** export + Postman collection
- [ ] **Batch scan** endpoint accepting ZIP of PEs
- [ ] **Model versioning** — A/B compare model v1 vs v2 in UI
- [ ] **Telemetry** — Plausible or PostHog (privacy-friendly) to track usage for the application essay
- [ ] **Blog post** on devrakib.com — "Productionizing my malware paper" — strong essay material
- [ ] **GitHub Actions CI** — lint + test on every PR

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
