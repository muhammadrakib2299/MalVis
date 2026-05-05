# Security CI

The CI workflow ([`ci.yml`](../.github/workflows/ci.yml)) runs three classes of check on every push and PR:

| Job | Tool | What it catches |
|-----|------|-----------------|
| `backend` | `ruff` (with `S` rule group) | Python source-level security smells (bandit-lite). |
| `frontend` | `next lint` (`next/core-web-vitals`) | React/Next.js anti-patterns. |
| `security` | `trivy` (filesystem) | Known CVEs in pinned dependencies and base images. |
| `security` | `semgrep --config auto` | Pattern-based static analysis across Python + TypeScript. |

This document covers the `security` job. The other two are standard linting; their config lives in `pyproject.toml` and `frontend/.eslintrc.json`.

## Trivy

Filesystem mode (`scan-type: fs`, `scan-ref: .`). Trivy reads:

- `backend/requirements.txt` for Python dependencies.
- `frontend/package.json` (and `package-lock.json` when present) for JavaScript dependencies.
- The `FROM` lines in our Dockerfiles for base-image vulnerabilities.
- The whole tree for accidentally-committed secrets and Dockerfile misconfigurations.

We fail the job on **HIGH** or **CRITICAL** severity findings, with `ignore-unfixed: true` — informational findings without an upstream fix would otherwise burn maintenance time on the wrong issues.

### Running locally

```bash
# Once: install Trivy
brew install aquasecurity/trivy/trivy           # macOS
# or follow https://aquasecurity.github.io/trivy/

# Same scan CI runs:
trivy fs --severity HIGH,CRITICAL --ignore-unfixed .
```

## Semgrep

Runs with the [`auto` config](https://semgrep.dev/docs/running-rules#auto-mode) — Semgrep auto-detects the languages in the repo (Python, TypeScript, YAML for the workflows) and pulls the matching public security rule packs. We fail on **ERROR** severity; WARNING/INFO get reported in the job log but don't block.

### Running locally

```bash
pip install semgrep==1.91.0
semgrep --config auto --error --severity ERROR .
```

## Why not Bandit (separately)?

Ruff's `S` rule group is a port of Bandit's checks, and we already select it in `pyproject.toml`. Running Bandit *and* Ruff `S` produces duplicate findings on the same lines — twice the noise, no extra signal. If the Ruff team ever stops syncing the `S` group with Bandit, that decision flips.

## When CI fails

1. **Read the actual finding.** Trivy and Semgrep output the file, line, rule ID, and severity. The rule ID links to a description on their respective registries.
2. **Decide: fix or suppress.** Default is fix. Suppression is for false positives, intentional patterns, or upstream issues with no available fix.
3. **Fix path.** Bump the dependency, refactor the matched code, or update the base image. If the fix is non-trivial, open an issue with the rule ID in the title and ship the fix in a focused PR.
4. **Suppression path.** Suppression should be *narrow* and *justified*:
   - Trivy: per-finding ignore via `.trivyignore` (CVE-by-CVE) — never `ignore-policy` rules that broadly silence categories.
   - Semgrep: inline `# nosemgrep: <rule-id>` comment on the matching line, with a one-line reason. Never wholesale-disable rule packs in config.
   - Ruff `S`: per-line `# noqa: SXXX` with a reason, mirroring the existing pattern. Project-wide ignores live in `pyproject.toml` and need a comment explaining why.

Every suppression is documentation of a deliberate decision. If the reason isn't worth writing down, the suppression isn't worth having.

## Pinning the tool versions

Both tools are version-pinned in `ci.yml` (`trivy-action@0.28.0`, `semgrep==1.91.0`). Bumps are deliberate — a pinned tool is the only way "the same scan that passed yesterday" actually means something. When upgrading, treat the new findings as a real signal, not as "the linter changed its mind."

## What the security job does NOT cover

- **Runtime behavior.** Both tools are static. The threat model in [`SECURITY.md`](../SECURITY.md) — sandboxed extractor, rate limiting, body cap, hash-pinned model loading — is enforced at runtime, not by the scanners.
- **Image scanning.** The current job is filesystem-only. Adding a build-and-scan step for the production Docker images is a future enhancement; today, base-image CVEs are caught from the `FROM` line via Trivy's filesystem scan.
- **Dependency provenance.** SLSA-level supply-chain checks (signed releases, attestations) are out of scope for now.

## Cross-references

- [`SECURITY.md`](../SECURITY.md) — runtime threat model and disclosure policy.
- [`docs/ADR-001-feature-set.md`](./ADR-001-feature-set.md) — schema-version-as-contract pattern, which the loader's SHA-pinning depends on.
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — the actual workflow.
