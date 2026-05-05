"""Export the FastAPI OpenAPI spec to ``docs/openapi.json``.

Why this is a committed artifact:

  - The spec is the contract the frontend, Postman collections, and
    third-party SIEM integrators read. Auto-regenerating it at every
    deploy is fine for runtime introspection, but a *committed* copy
    means a contributor can ``cat docs/openapi.json`` to see what the
    API looks like without booting the backend.
  - The CI workflow re-runs this script and ``git diff --exit-code``
    against the committed file. A drift means someone changed an
    endpoint without updating the spec — and that's exactly the bug
    we want to catch in review, not after a frontend deploy that
    silently 4xx's.

Quick start (from repo root):

    cd backend && pip install -r requirements.txt && cd ..
    python -m scripts.export_openapi

Output:

    docs/openapi.json   (overwritten in place, deterministic)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SPEC_PATH = DOCS_DIR / "openapi.json"

# Add backend/ to sys.path so the FastAPI app import resolves regardless
# of where the script is invoked from. Same pattern as training/train.py;
# the alternative is `pip install -e backend`, which is more refactor than
# this script earns on its own.
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app  # noqa: E402  — sys.path manipulation above


def main() -> None:
    spec = app.openapi()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Stable formatting: sort keys, 2-space indent, trailing newline.
    # Anything less and the drift gate flags noise instead of real changes.
    SPEC_PATH.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[openapi] wrote {SPEC_PATH.relative_to(REPO_ROOT)}")
    print(f"[openapi] {len(spec.get('paths', {}))} paths · "
          f"OpenAPI {spec.get('openapi', '?')} · "
          f"{spec.get('info', {}).get('version', '?')}")


if __name__ == "__main__":
    main()
