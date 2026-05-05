"""Train RF + XGBoost on a synthetic PE dataset matching FEATURE_VECTOR_ORDER.

Quick start (from repo root):

    cd backend && pip install -r requirements.txt && cd ..
    python -m training.train

Outputs:

    artifacts/rf-v1.joblib
    artifacts/xgb-v1.joblib
    artifacts/MANIFEST.json

Once the artifacts exist, set ``USE_MOCK_MODELS=false`` (env or .env) and
restart the backend; the model registry will SHA-verify each pickle
against MANIFEST.json before loading and will refuse to start if any
hash fails.

Limitations
-----------

The default dataset is **synthetic** — generated programmatically via
``app.utils.pe_builder`` with random section payloads + header jitter.
Models trained on it will:

    - Severely overfit the synthetic distribution.
    - Generalize poorly to real malware/benign PE distributions.
    - Produce SHAP attributions that reflect synthetic patterns, not
      real causal signal.

The point of this script is to exercise the **full pipeline** end-to-end:
feature extraction → train → eval → persist → manifest. Replacing the
dataset is a one-function change — see ``_build_synthetic_dataset`` and
the README.

Real datasets the loader could feed in here:

    - **EMBER 2018**:  https://github.com/elastic/ember
    - **BODMAS**:      https://whyisyoung.github.io/BODMAS/
    - **Custom**:      a directory of harmless OSS Windows binaries (e.g.
                       7-Zip, Notepad++, ProcessHacker) for benign + a
                       license-cleared malicious set you've vetted.

Each option needs a (X, y) producer that yields the same column order as
``FEATURE_VECTOR_ORDER`` and labels 0 = benign, 1 = malicious.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"

# Add backend/ to sys.path so the `app.*` imports below resolve regardless
# of how the script is invoked. This script is a deploy/operator tool, not
# library code, so munging sys.path here is the simpler path than turning
# `backend/` into an installable package.
sys.path.insert(0, str(REPO_ROOT / "backend"))

import joblib  # noqa: E402  — sys.path manipulation above
import numpy as np  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.metrics import f1_score, precision_score, recall_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

from app.services.pe_features import (  # noqa: E402
    FEATURE_SCHEMA_VERSION,
    FEATURE_VECTOR_ORDER,
    extract_features,
)
from app.utils.pe_builder import build_minimal_pe  # noqa: E402


# --- Dataset --------------------------------------------------------------


def _build_synthetic_dataset(
    n: int = 2000,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate (X, y) where X has FEATURE_VECTOR_ORDER columns.

    Half "benign-like" (low-entropy NOP-sled section, varied size).
    Half "malicious-like" (high-entropy random payload, varied size).

    Real datasets give the model far more signal than this; the synthetic
    classes here mostly differ by entropy + size, which is what the
    trained models will key on. Don't read prediction quality on real
    samples as evidence of either model family's capability.
    """
    rng = np.random.default_rng(seed)
    rows: list[list[float]] = []
    labels: list[int] = []

    half = n // 2
    for i in range(n):
        is_malicious = i >= half
        if is_malicious:
            payload_size = int(rng.integers(1024, 8192))
            payload = bytes(rng.integers(0, 256, size=payload_size, dtype=np.uint8))
        else:
            payload_size = int(rng.integers(64, 4096))
            payload = b"\x90" * payload_size

        pe_bytes = build_minimal_pe(section_payload=payload)
        features = extract_features(pe_bytes)
        rows.append(features.to_vector())
        labels.append(1 if is_malicious else 0)

    X = np.asarray(rows, dtype=float)
    y = np.asarray(labels, dtype=int)
    assert X.shape[1] == len(FEATURE_VECTOR_ORDER), (
        f"vectorizer drift: produced {X.shape[1]} cols vs "
        f"FEATURE_VECTOR_ORDER {len(FEATURE_VECTOR_ORDER)}"
    )
    return X, y


# --- Training -------------------------------------------------------------


def _fit_and_eval(model, X_train, y_train, X_test, y_test) -> dict[str, float]:
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    return {
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
    }


def _save_artifact(model, path: Path) -> str:
    joblib.dump(model, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Main -----------------------------------------------------------------


def main() -> None:
    print(f"[train] building synthetic dataset (schema {FEATURE_SCHEMA_VERSION})")
    X, y = _build_synthetic_dataset()
    print(f"        X.shape={X.shape}  y.shape={y.shape}  malicious_frac={y.mean():.2f}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    print("[train] fitting RandomForestClassifier")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        random_state=42,
        n_jobs=-1,
    )
    rf_metrics = _fit_and_eval(rf, X_train, y_train, X_test, y_test)
    rf_path = ARTIFACTS_DIR / "rf-v1.joblib"
    rf_sha = _save_artifact(rf, rf_path)
    print(f"        metrics={rf_metrics}")
    print(f"        artifact={rf_path.name}  sha256={rf_sha[:16]}…")

    print("[train] fitting XGBClassifier")
    xgb = XGBClassifier(
        n_estimators=200,
        max_depth=8,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
    )
    xgb_metrics = _fit_and_eval(xgb, X_train, y_train, X_test, y_test)
    xgb_path = ARTIFACTS_DIR / "xgb-v1.joblib"
    xgb_sha = _save_artifact(xgb, xgb_path)
    print(f"        metrics={xgb_metrics}")
    print(f"        artifact={xgb_path.name}  sha256={xgb_sha[:16]}…")

    notes = (
        "Trained on a synthetic PE dataset generated by app.utils.pe_builder. "
        "Pipeline-demonstration only — not for real malware detection. Replace "
        "the dataset in training/train.py before relying on these predictions."
    )

    manifest = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "models": [
            {
                "id": "rf-v1",
                "family": "random_forest",
                "filename": "rf-v1.joblib",
                "sha256": rf_sha,
                "trained_at": _now_iso(),
                "training_dataset": "synthetic-pe-builder-v1",
                "metrics": rf_metrics,
                "paper_citation": "(synthetic — pipeline demonstration)",
                "notes": notes,
            },
            {
                "id": "xgb-v1",
                "family": "xgboost",
                "filename": "xgb-v1.joblib",
                "sha256": xgb_sha,
                "trained_at": _now_iso(),
                "training_dataset": "synthetic-pe-builder-v1",
                "metrics": xgb_metrics,
                "paper_citation": "(synthetic — pipeline demonstration)",
                "notes": notes,
            },
        ],
    }

    manifest_path = ARTIFACTS_DIR / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n[train] manifest: {manifest_path}")
    print("[train] to load these artifacts, set USE_MOCK_MODELS=false and restart.")


if __name__ == "__main__":
    main()
