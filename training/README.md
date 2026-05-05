# Training pipeline

This directory holds the script that produces the trained `.joblib` artifacts the backend's model registry loads. The script is **operator tooling**, not library code — run it once on a real dataset to generate `artifacts/rf-v1.joblib`, `artifacts/xgb-v1.joblib`, and `artifacts/MANIFEST.json`. The backend reads those at startup when `USE_MOCK_MODELS=false`.

## Quick start (synthetic data)

```bash
cd backend && pip install -r requirements.txt && cd ..
python -m training.train
```

Outputs land in `artifacts/` (gitignored — see `.gitignore`).

## Activating the trained models

```bash
# .env at repo root, or env vars in your shell:
USE_MOCK_MODELS=false
```

Then restart the backend. The model registry verifies every pickle's SHA-256 against `MANIFEST.json` before loading; any mismatch (corrupt artifact, hand-edited manifest, schema-version drift) refuses startup. See `app/services/model_registry.py::_load_real`.

## What the default script trains on

The default `_build_synthetic_dataset` generates 2000 PEs from `app/utils/pe_builder.py` — half low-entropy NOP-sleds (treated as benign), half high-entropy random payloads (treated as malicious). This is enough to *exercise the pipeline* but **not** to make real predictions:

- The synthetic distribution is much narrower than real malware/benign distributions.
- The models will overfit features that vary in this synthetic generator (mostly entropy + size).
- SHAP attributions on real PEs may emphasize features the synthetic data doesn't actually teach.

The model card and the `notes` field of each manifest entry both surface this limitation in the running dashboard, so a reviewer never sees "F1 = 0.99" without the asterisk.

## Swapping in a real dataset

Replace `_build_synthetic_dataset(n, seed)` with a loader that yields:

```python
(X, y)
# X: np.ndarray of shape (n_samples, len(FEATURE_VECTOR_ORDER)), dtype=float
# y: np.ndarray of shape (n_samples,), dtype=int  (0 = benign, 1 = malicious)
```

For a real PE dataset, the loader pseudo-code is:

```python
def _load_real(paths_and_labels: list[tuple[Path, int]]):
    rows, labels = [], []
    for path, label in paths_and_labels:
        with path.open("rb") as f:
            features = extract_features(f.read())
        rows.append(features.to_vector())
        labels.append(label)
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int)
```

### Public datasets to consider

| Dataset | Size | License | Notes |
|--------|-------|---------|-------|
| [EMBER 2018](https://github.com/elastic/ember) | ~1.1M | Apache 2.0 | Pre-extracted features in a different schema — you'd need to download raw binaries or rewrite the feature mapping. |
| [BODMAS](https://whyisyoung.github.io/BODMAS/) | ~134k | Research | Similar caveat to EMBER (own feature schema). |
| Custom OSS + sandbox-cleared malicious | tens to hundreds | varies | Feed raw bytes through `extract_features` directly. |

Whatever you choose, the manifest's `training_dataset` and `paper_citation` fields should record what was used so the model card stays honest.

## Schema version

`FEATURE_VECTOR_ORDER` and `FEATURE_SCHEMA_VERSION` (in `backend/app/services/pe_features.py`) are pinned to the manifest. If you change the feature set, bump the schema version in `pe_features.py` *and* re-train + re-pin everything. See [`docs/ADR-001-feature-set.md`](../docs/ADR-001-feature-set.md) for the full schema-bump policy.

## What this script does not do

- **No hyperparameter tuning.** The `n_estimators` / `max_depth` defaults are sane-ish but unmotivated. Tune for your dataset.
- **No cross-validation.** A single 80/20 train/test split. For research-grade numbers, run `cross_val_score` or `StratifiedKFold` and report the mean ± std.
- **No calibration.** Confidence values come straight from `predict_proba`; the model card explicitly says they aren't externally recalibrated.
- **No data validation beyond the schema-length assert.** A loader that emits NaN/Inf or wildly out-of-range values will train silently. Add an input check if your data source isn't trusted.
