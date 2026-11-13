# CI and release checklist

Applies to `.github/workflows/**`, `pyproject.toml` (dependencies, extras, build backend), lock/constraints files, release scripts.

### [code] DEPS-1: dependency changes are justified - blocker

```bash
git diff HEAD -- pyproject.toml
```
A new runtime dependency (`[project.dependencies]` or an extra such as `[live]` / `[exports]`) needs an ADR in `docs/decisions/` (CLAUDE.md rule 10). No direct import of a transitive dependency. `make audit` is green. Package name checked for typosquatting on PyPI (exact name, maintainers, release history, repository link).

### [code] DEPS-2: version ranges and pins - warning

Runtime dependencies use compatible lower bounds (no exact `==` pins in a library); dev/CI tooling is pinned (lock or constraints file) so CI is reproducible. `requires-python` matches the supported CPython range (CLAUDE.md).

### [code] GHA-1: actions pinned to full commit SHAs - blocker

```bash
grep -rnE 'uses:\s*[^ ]+@' .github/workflows | grep -vE '@[0-9a-f]{40}'
```
Every hit is a FAIL (local `./` actions excepted). The SHA has a `# vX.Y.Z` comment, verified via `gh api repos/<owner>/<action>/git/ref/tags/<tag>`.

### [code] GHA-2: least-privilege permissions - blocker

Top-level `permissions:` present and minimal (`contents: read` by default); write scopes only on the job that needs them (`id-token: write` only on the publish job).
```bash
grep -LnE '^permissions:' .github/workflows/*.yml
```

### [review] GHA-3: no untrusted code with secrets - blocker

No `pull_request_target` (or `workflow_run`) that checks out PR head code. No `${{ github.event.* }}` interpolated directly into `run:` (pass through `env:`). Secrets only in jobs that need them, never on fork PRs. `actions/checkout` with `persist-credentials: false` unless the job pushes.

### [review] GHA-4: no secrets in logs - blocker

No `echo` of secrets, no `set -x` around secret use, `WHITEMARKET_PARTNER_TOKEN` (repo secret `WM_PARTNER_TOKEN`) only via `env:` into the live smoke step, artifacts do not contain tokens or raw live responses.

### [review] GHA-5: concurrency and triggers - warning

Workflows that push or open PRs (`schema-sync.yml`) have a `concurrency` group; cron and `repository_dispatch` triggers cannot be fired with attacker-controlled payload into a shell.

### [review] REL-1: release provenance - blocker for the release workflow, warning otherwise

Releases are built from a protected tag by the release workflow, never from a local machine (a hook blocks `twine upload` / `uv publish` for the agent). PyPI upload uses **trusted publishing** (OIDC, `id-token: write`, no long-lived API token in secrets) from a job in a protected `release` environment; build and publish are separate jobs, the publish job only downloads the built artifacts. Attestations / provenance are produced where the publishing action supports it (verify the input name in the action's docs for the pinned version, CLAUDE.md rule 14). `twine check` (or `make build`) passes; CHANGELOG lists breaking changes.

### [code] SECRET-HISTORY-1: no secret anywhere in branch history - blocker

```bash
git log -p main..HEAD | grep -inE '(token|secret|password|bearer|api[_-]?key)\s*[:=]\s*["'\''][^"'\'']{12,}' | head -50
```
A secret removed in a later commit is still in history: rotate it and tell the user.
