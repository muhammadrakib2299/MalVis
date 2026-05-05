# MalVis — Malware Feature Visualization Dashboard

> Interactive web dashboard for explainable malware detection. Upload a Windows PE file, get predictions from multiple ML models, and inspect **why** each model made its call via SHAP and LIME.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-000000?logo=next.js&logoColor=white)](https://nextjs.org/)

**Live demo:** _coming soon_ · **Paper:** _link to your published paper_

---

## Why this project exists

This dashboard is the deployable, interactive companion to a published research paper on malware detection using Random Forest and XGBoost with SHAP/LIME explainability. Static papers and notebooks make it hard for reviewers, collaborators, and security teams to reason about model behavior on real samples — MalVis turns the same models into a tool you can actually use.

Three things it does that a notebook can't:

1. **Live multi-model comparison** — RF vs XGBoost (vs ANN) on the same input, side by side.
2. **Per-prediction explanations** — SHAP waterfall + feature importance, generated on demand.
3. **Adversarial what-if** — perturb individual features and watch the prediction shift in real time.

---

## Features

- **Drag-and-drop PE file upload** with size and format validation
- **Multi-model inference** — Random Forest, XGBoost, optional ANN — with confidence scores
- **SHAP waterfall plots** for any single prediction
- **Global + local feature importance** views with toggle
- **Adversarial perturbation simulator** — flip imports, change section entropy, see prediction delta live
- **REST API** designed for SIEM-style integration (`/scan`, `/explain`, `/perturb`)
- **Containerized** — single `docker compose up` to run locally

---

## Architecture

```
┌─────────────────┐         ┌─────────────────────┐         ┌──────────────────┐
│  Next.js UI     │  HTTPS  │  FastAPI backend    │   in-   │  Trained models  │
│  (Tailwind +    │ ──────► │  + SHAP/LIME runner │ process │  RF / XGBoost /  │
│   D3 viz)       │         │  + PE feature extr. │         │  ANN (joblib)    │
└─────────────────┘         └─────────────────────┘         └──────────────────┘
```

- **Frontend** — Next.js (App Router) + TailwindCSS + D3.js for visualizations
- **Backend** — FastAPI + scikit-learn + XGBoost + SHAP, with `pefile` for PE parsing
- **Models** — pickled artifacts loaded once at startup (singleton registry)
- **Deployment** — Docker images; backend on Railway/Fly.io, frontend on Vercel

---

## Tech stack

**Backend** Python 3.11 · FastAPI · scikit-learn · XGBoost · SHAP · LIME · pefile · pydantic · joblib  
**Frontend** Next.js 14 · TypeScript · TailwindCSS · D3.js · React Query  
**Infra** Docker · docker-compose · GitHub Actions CI · Vercel · Railway

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (optional, for containerized run)

### Local development

```bash
# Clone
git clone https://github.com/<your-username>/malvis.git
cd malvis

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (in a second terminal)
cd frontend
npm install
npm run dev                           # http://localhost:3000
```

Visit `http://localhost:3000`, drop a PE file, see predictions.

### Docker (one-shot)

```bash
docker compose up --build
```

---

## API

| Method | Endpoint     | Description                                                    |
| ------ | ------------ | -------------------------------------------------------------- |
| POST   | `/scan`      | Upload PE file → predictions from all loaded models            |
| POST   | `/explain`   | SHAP values for a given file, formatted for waterfall plotting |
| POST   | `/perturb`   | Apply a perturbation spec, return prediction delta             |
| GET    | `/models`    | List loaded models with metadata (paper, F1, training date)    |
| GET    | `/health`    | Liveness probe                                                 |

Full OpenAPI spec at `/docs` when the backend is running.

---

## Project structure

```
malvis/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/         scan, explain, perturb, models
│   │   ├── services/        pe_features, model_registry, shap_runner
│   │   └── schemas/         pydantic models
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                Next.js app
├── notebooks/               training + experimentation
├── artifacts/               trained model pickles (gitignored)
├── docs/                    architecture decision records
├── docker-compose.yml
└── README.md
```

---

## Roadmap

- [ ] Phase 1 — Backend skeleton + model loading
- [ ] Phase 2 — `/scan`, `/explain`, `/perturb` endpoints
- [ ] Phase 3 — Next.js dashboard with SHAP waterfall + perturbation simulator
- [ ] Phase 4 — Dockerize + deploy live URL
- [ ] Phase 5 — Demo video + documentation polish
- [ ] Phase 6 — REST API auth, batch scan, model versioning

See [`TODO.md`](./TODO.md) for the full breakdown.

---

## Research context

MalVis productionizes the models and findings from a peer-reviewed paper on explainable malware detection. The dashboard lets reviewers and security practitioners interact with the same Random Forest and XGBoost classifiers described in the paper, on arbitrary PE samples, with the same SHAP-based interpretability layer.

> _Citation will be added here once the live demo links back from the paper._

---

## Contributing

This is primarily a portfolio project, but issues and PRs are welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) (added in Phase 5).

---

## License

MIT — see [`LICENSE`](./LICENSE).

---

## Author

**Md. Rakibul Hasan** — [devrakib.com](https://devrakib.com)  
Backend developer at Combosoft · Master's applicant in Data Science (Germany, intake 2026/27)
