# MalVis frontend

Next.js 14 (App Router) + Tailwind CSS dashboard for the MalVis backend.

## Local dev

```bash
cd frontend
cp .env.local.example .env.local   # edit if your backend isn't on :8000
npm install
npm run dev
```

The backend is expected at `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`). Start it from `backend/`:

```bash
cd backend
uvicorn app.main:app --reload
```

## What's wired today

- `UploadZone` — drag-and-drop or file picker, client-side MZ-magic check (saves a round-trip on obvious non-PE), 10 MB cap matching the backend.
- `ResultsPanel` — file summary (SHA-256, size, sections, imports) and a multi-model verdict table. Highlights the row when models disagree.
- Mock-mode banner driven by `/models.mock_mode` so the demo never quietly serves synthetic predictions as real ones.

## Coming next

- SHAP waterfall component (D3 or Recharts) wired to `/explain`.
- Adversarial perturbation simulator (sliders + toggles) wired to `/perturb`.
- Sample-binary gallery so visitors without a PE on hand can still see the demo.
- Accessibility pass: alt text on charts, keyboard nav, tabular fallback for the SHAP view.
