# Security policy

MalVis accepts user-uploaded Windows PE files over the public internet. We treat every uploaded binary as potentially malicious and isolate it accordingly. This document describes our threat model, the controls we apply, and how to report a vulnerability.

---

## Threat model

The high-risk surfaces in MalVis are:

1. **The PE parser.** Both `pefile` and `LIEF` have a history of crashes and (rarely) memory-safety issues on malformed inputs. A crafted PE could exploit a parser bug.
2. **The `/scan` endpoint.** Open to the internet, accepts executables. Targets for: resource exhaustion (parser bombs, oversized uploads), denial of service, and abuse as an oracle for adversarial-ML probing.
3. **User-uploaded content.** Binaries may contain proprietary, copyrighted, or sensitive code. Users trust MalVis not to retain or leak them.
4. **The model artifacts.** Pickled scikit-learn / XGBoost models are arbitrary code on `joblib.load`. Only models we built and signed are loaded.

Out of scope for v1: dynamic analysis, sandboxed execution of the uploaded binary, multi-tenant separation between authenticated users.

---

## Controls

### Process isolation

The feature-extraction worker is a standalone program (`app/extractor_worker.py`) that reads PE bytes from stdin, writes a single JSON document to stdout, and exits. It runs out-of-process from the API in two stacked layers:

1. **OS-level (every deployment, including local dev).** The API spawns the worker via `SubprocessExtractor`, which applies a wall-clock timeout, `RLIMIT_AS` (memory), `RLIMIT_CPU`, and `RLIMIT_CORE=0` (no core dumps containing upload bytes). Set `EXTRACTOR_STRATEGY=subprocess` to enable. Default is `inprocess` for unit tests where the cost of forking per request is unjustified.
2. **Container-level (production).** A second container built from `backend/Dockerfile.extractor` runs the same worker with:
   - No network egress (`--network=none`).
   - Read-only root filesystem (`--read-only`), per-request `tmpfs` scratch (`--tmpfs=/tmp:size=16m,mode=1700`).
   - Non-root user (UID 10001), all Linux capabilities dropped (`--cap-drop=ALL`), `--security-opt=no-new-privileges`.
   - Resource limits: `--memory=512m --cpus=1` plus a 30 s wall-clock timeout from the API caller.
   - Container image contains only `pefile` and the worker — no FastAPI, no scikit-learn, no SHAP.

A pefile crash takes down the worker, never the API. A successful exploit of pefile gets the attacker a process with no network, no filesystem, no capabilities, and a 30-second life expectancy.

### Input validation

- Hard 10 MB upload cap, enforced at the reverse proxy before FastAPI sees the request.
- Magic-byte check: anything not starting with `MZ` is rejected with `400` before the parser runs.
- The binary is never written to persistent disk — it lives in memory or in the per-request tmpfs only.
- Per-IP rate limit: 10 requests/minute, 100 requests/day. Global concurrency cap on `/scan`.

### Data handling

- Only the SHA-256 of the upload is logged. Binary contents are never persisted.
- An in-memory LRU (≤1000 entries, 1 h TTL) maps SHA-256 → cached prediction. The original bytes are discarded once features are extracted.
- No third-party telemetry receives binary content, filenames, or extracted features tied to a hash.
- Hash lookups against external threat-intel services are **opt-in**, never default.

### Network

- HTTPS only; HSTS preloaded.
- Cloudflare WAF in front of the public endpoints with bot-fight mode and rate-limit rules.
- CORS restricted to the official frontend origin.

### Supply chain

- Backend dependencies pinned via `requirements.txt` + hash-checking mode (`pip install --require-hashes`).
- Container images scanned with Trivy on every push; high-severity findings block release.
- Python source scanned with Bandit and Semgrep in CI.
- Model pickles produced by us, stored with a manifest that records SHA-256 + training run ID. Loader refuses any pickle whose hash is not in the manifest.

---

## Responsible use

- MalVis is a research and educational tool. It is **not** a substitute for endpoint protection, EDR, or formal incident response.
- Do not upload binaries you are not authorized to analyze.
- Do not rely on MalVis verdicts as the sole basis for production triage decisions. The model card lists known limitations and failure modes.

## What MalVis does **not** do

- We never execute uploaded binaries. All analysis is static.
- We do not share uploaded content with third parties.
- We do not retain uploaded binaries after a request completes.

---

## Reporting a vulnerability

Please email **security@devrakib.com** with:

- A description of the issue and its impact.
- Steps to reproduce, including a minimal sample if possible.
- Your name or handle for credit (optional).

We aim to acknowledge within 48 hours and to ship a fix for high-severity issues within 14 days. Please do not file public GitHub issues for security vulnerabilities — coordinate via email first.

We do not currently run a paid bug-bounty program, but we will publicly credit reporters (with consent) in the release notes of the patched version.
