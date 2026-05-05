# Contributing to MalVis

MalVis is primarily a portfolio project, but issues and pull requests are welcome — bug reports, security findings, additional sample binaries, documentation fixes, and accessibility improvements especially.

## Before you open an issue or PR

- For **security issues**: please email **security@devrakib.com** instead of filing a public issue. See [`SECURITY.md`](./SECURITY.md) for the full policy and the threat model the project commits to.
- For **bugs**: include the failing input (or a minimal repro), the expected behavior, the actual behavior, and the relevant log output. Never include a binary you're not authorized to share — a SHA-256 plus a short description is enough.
- For **features**: open an issue first to discuss fit. The roadmap in [`TODO.md`](./TODO.md) is the source of truth for what's planned; the [`lessons.md`](./lessons.md) file records the *why* behind decisions already made.

## Development setup

The full local-dev story lives in the root [`README.md`](./README.md). Short version:

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Or, end-to-end with Docker:

```bash
cp .env.example .env
docker compose up --build
```

## Code style

- **Python** — `ruff` (lint) and `black` (format). Both read config from the root `pyproject.toml`. Run before pushing:
  ```bash
  ruff check .
  black .
  ```
- **TypeScript / TSX** — Next.js + ESLint with `next/core-web-vitals`. Strict TypeScript is enforced (`tsconfig.json`):
  ```bash
  cd frontend
  npm run typecheck
  npm run lint
  ```
- No prettier yet — Tailwind class ordering follows the convention in existing components.

## Tests

- **Backend** — `pytest` from the repo root or from `backend/`. Tests must pass before opening a PR:
  ```bash
  pytest -ra
  ```
  CI runs the same suite with `EXTRACTOR_STRATEGY=inprocess` (per-test forking would slow it without changing coverage). The subprocess path has its own dedicated tests in `backend/tests/test_extractor.py`.
- **Frontend** — `npm run typecheck && npm run lint && npm run build` is the current CI gate. Component-level tests would be welcome (see TODO).

## Pull requests

- Branch from `main`. Keep PRs focused — one logical change per PR.
- Match the commit-message style in `git log` (short imperative subject + a body explaining *why*, mirroring the `lessons.md` entries).
- Update [`TODO.md`](./TODO.md) and [`lessons.md`](./lessons.md) if your change affects either: TODO for what landed, lessons for the *why* and any pitfalls.
- CI must be green before merge: `.github/workflows/ci.yml` runs ruff/black/pytest and frontend typecheck/lint/build.

## Things to know before touching the data path

- **No binary fixtures in git.** PE samples are built programmatically via `app/utils/pe_builder.py` (used by tests *and* the gallery). If you need a new sample, extend the builder or add a definition in `app/services/samples.py`.
- **The feature schema is a contract.** `FEATURE_VECTOR_ORDER` and `FEATURE_SCHEMA_VERSION` (in `app/services/pe_features.py`) are pinned to model artifacts via the manifest. See [`docs/ADR-001-feature-set.md`](./docs/ADR-001-feature-set.md) before modifying either.
- **Uploads aren't retained.** The cache is in-memory, bounded, TTL'd; the PE bytes never touch disk. Any change that adds disk I/O on the upload path needs a security review.

## Code of Conduct

This project follows the [Contributor Covenant](./CODE_OF_CONDUCT.md). By participating you agree to abide by it.

## License

By contributing you agree your changes are licensed under the [MIT License](./LICENSE).
