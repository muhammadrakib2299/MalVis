# Security CI

The CI workflow ([`ci.yml`](../.github/workflows/ci.yml)) runs three classes of check on every push and PR:

| Job | Tool | What it catches |
|-----|------|-----------------|
| `backend` | `ruff` (with `S` rule group) | Python source-level security smells (bandit-lite). |
| `frontend` | `next lint` (`next/core-web-vitals`) | React/Next.js anti-patterns. |
| `security` | `trufflehog --only-verified` | Active, working credentials in the diff (or full history on `main`). |
| `security` | `trivy` (filesystem) | Known CVEs in pinned dependencies and base images. |
| `security` | `semgrep --config auto` | Pattern-based static analysis across Python + TypeScript. |

This document covers the `security` job. The other two are standard linting; their config lives in `pyproject.toml` and `frontend/.eslintrc.json`.

## Trufflehog

Runs first in the `security` job — a leaked credential is the most urgent finding CI can produce, and we want it screaming before slower scanners spend their minutes.

**`--only-verified`** is the load-bearing flag. Trufflehog can detect the *shape* of dozens of credential formats (AWS keys, Stripe tokens, GitHub PATs, etc.), but pattern matches alone produce a long false-positive tail — random base64 strings in test fixtures, hex digests that look like API keys, etc. With `--only-verified`, a finding fails CI only when Trufflehog can *actively* confirm the credential works by calling the provider's identity endpoint. Unverified hits still appear in the job log for audit, but they don't gate the build.

**`fetch-depth: 0`** in the `actions/checkout` step pulls the full history so Trufflehog can diff a range. Without it, the action falls back to a shallow scan of the tip, which on a large repo would either spam findings or get rate-limited.

### When CI fails on a real leak

The job log will name the file, line, and credential type. Order of operations:

1. **Rotate first.** Revoke the credential at the provider — AWS console, GitHub settings, etc. Until you do, the leaked value is live. *Do not* skip this step to "investigate first": from the moment a credential hits a public commit, assume it's already scraped.
2. **Scrub the history second.** `git rebase -i` to remove the commit, or `git filter-repo` for a deeper rewrite. Force-push only with explicit user authorization. The point of step 1 is that the scrub no longer matters for active exploitation; this step is about removing the fingerprint from the public record.
3. **Document the incident.** A short note in `lessons.md` (or a Linear/issue ticket) so the same path doesn't catch the next contributor.

### Running locally

```bash
# Once: install Trufflehog
brew install trufflehog                                  # macOS
# or follow https://github.com/trufflesecurity/trufflehog

# Same scan CI runs (verified-only, current branch vs. main):
trufflehog git file://. --branch HEAD --only-verified
```

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
   - Trufflehog: in `--only-verified` mode, a finding is by definition a working credential. The "suppression" path is rotate + scrub. Do not add detector exclusions; if a fixture genuinely needs a fake-but-realistic-looking secret, mark it with the `trufflehog:ignore` line comment.
   - Trivy: per-finding ignore via `.trivyignore` (CVE-by-CVE) — never `ignore-policy` rules that broadly silence categories.
   - Semgrep: inline `# nosemgrep: <rule-id>` comment on the matching line, with a one-line reason. Never wholesale-disable rule packs in config.
   - Ruff `S`: per-line `# noqa: SXXX` with a reason, mirroring the existing pattern. Project-wide ignores live in `pyproject.toml` and need a comment explaining why.

Every suppression is documentation of a deliberate decision. If the reason isn't worth writing down, the suppression isn't worth having.

## Pinning the tool versions

All three tools are version-pinned in `ci.yml` (`trufflehog@v3.83.6`, `trivy-action@0.28.0`, `semgrep==1.91.0`). Bumps are deliberate — a pinned tool is the only way "the same scan that passed yesterday" actually means something. When upgrading, treat the new findings as a real signal, not as "the linter changed its mind."

## Dependabot

The `security` job catches known CVEs in *today's* pinned dependencies. Dependabot ([`.github/dependabot.yml`](../.github/dependabot.yml)) opens upgrade PRs *before* tomorrow's CVE drops — they're complementary, not redundant.

| | What it answers |
|---|---|
| **Trivy** | "Do my current pins have a known CVE *right now*?" |
| **Dependabot** | "Are my pins up to date enough that a published CVE won't be in tomorrow's scan?" |

### Configuration

- **Three ecosystems**: pip (`/backend`), npm (`/frontend`), github-actions (`/`).
- **Weekly cadence**. Daily is noise for a project this size; monthly misses upstream patches that drop mid-cycle.
- **Minor + patch grouped, major separate.** A grouped PR with 8 patch bumps reads in 2 minutes; the same PR mixed with a major React upgrade reads in an hour. Major bumps land alone so they get the review they deserve.
- **Open-PR limit: 2 per ecosystem.** Solo project — six open Dependabot PRs across ecosystems is more queue than the maintainer can clear weekly. Two means the queue stays drainable.

### When a Dependabot PR fails CI

Most weeks, "merge as-is" is the right answer for the grouped patch PR. When CI fails:

1. **CVE-fix PRs** (Dependabot labels these "security update"): triage *first*, even if they break tests. The patch is more urgent than the test fix; merge into a feature branch, fix tests there, then merge.
2. **Routine bumps**: read the changelog the PR links to. If a minor bump introduced a behavior change, decide between (a) updating the call sites, (b) pinning at the previous version with a `# Dependabot-skip` comment, or (c) closing the PR with a one-line reason — Dependabot will reopen at the next major bump.
3. **Major bumps in `requirements.txt`** (e.g., FastAPI 0.x → 1.0): always read the migration guide. If the code-change cost is high, close the PR with a note in the closing comment; Dependabot won't reopen until a *newer* major appears.

### Skipping or pinning

- **Skip a single update**: close the PR. Dependabot remembers and won't re-open for the same version.
- **Pin a package permanently**: add to the `ignore` block in `dependabot.yml` with a comment explaining why. Use sparingly — every ignore is a future CVE waiting in plain sight.

## What the security job does NOT cover

- **Runtime behavior.** Both tools are static. The threat model in [`SECURITY.md`](../SECURITY.md) — sandboxed extractor, rate limiting, body cap, hash-pinned model loading — is enforced at runtime, not by the scanners.
- **Image scanning.** The current job is filesystem-only. Adding a build-and-scan step for the production Docker images is a future enhancement; today, base-image CVEs are caught from the `FROM` line via Trivy's filesystem scan.
- **Dependency provenance.** SLSA-level supply-chain checks (signed releases, attestations) are out of scope for now.

## Cross-references

- [`SECURITY.md`](../SECURITY.md) — runtime threat model and disclosure policy.
- [`docs/ADR-001-feature-set.md`](./ADR-001-feature-set.md) — schema-version-as-contract pattern, which the loader's SHA-pinning depends on.
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — the actual workflow.
