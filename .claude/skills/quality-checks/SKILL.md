---
name: quality-checks
description: Use BEFORE claiming Python work is complete or proposing a commit/PR. Mandatory pre-finish workflow = the parts of `make check` in order (types -> lint -> fmt-check -> fmt if needed -> types + lint again -> coverage -> codegen-check -> audit). Cheap read-only static runs FIRST, before the mutating autofix. Each step green before the next; a violation on pre-existing code is suppressed in place with a code, a reason and an issue reference, not refactored. During iteration use the fast loop (make test K=..., make lint, make types), full run once.
---

# Quality checks: mandatory before finishing

Run **in order**, fix **every** error before the next step (CLAUDE.md rule 0). Claiming "done" with red checks is forbidden.

Tools run from `.venv/bin/` (created by `make install`; `uv` is not on the host). Always call them through `make`.

## Full run once; fast loop while working

The full steps 1-8 are needed **once**, before the readiness claim. Running them after every edit is the most expensive way to check yourself: most full runs fail on static analysis and never reach the tests.

While working, use the subset. These may run **inline in the main session**: make targets filter output down to errors and a summary.

```bash
make test K=<expr>      # the relevant tests (pytest -k expression), not the whole suite
make lint               # ruff
make types              # mypy --strict + pyright strict
```

The full output of every filtered target is in `var/qc/<target>.log`: `grep` it instead of re-running; never read it whole into context. `VERBOSE=1 make <target>` disables the filter (for a human debugging, not for the agent).

Rule: **output filtered down to a verdict may run inline; everything else goes to a subagent.** More than ~20 errors or unclear output: hand it to the subagent.

The fast loop does **not** replace the full run.

## Who runs it: the subagent

The full run is done by `Agent(subagent_type: "qc-runner")` (`.claude/agents/qc-runner.md`, sonnet). Prompt: "Run quality-checks steps 1-8". Reason: tool output is resent with every later request of the session.

Subagent contract (CLAUDE.md "Delegation"):

```
Step N (<command>): PASS | FAIL
On FAIL: up to 20 errors as `path:line - message`, the total count,
the last 15 lines of output. Later steps not run.
```

The main session fixes (it has the task context); the re-run is the subagent again. The subagent never edits code. Unclear output or a missing `.venv` is reported as a fact, never as "PASS".

## Step 1: type checking (before autofix)
```bash
make types
```
`mypy --strict` and pyright in strict mode on `src/`. Fix everything. Static goes first because a later step may **change code**; autofixing unchecked code means paying twice.

## Step 2: lint (read-only)
```bash
make lint
```
ruff with the project rule set (incl. `B S UP SIM RUF ASYNC PT`). Fix by hand; if you use ruff's autofix, run it only for a rule you understand and re-read the diff: some fixes are marked unsafe for a reason (they can change behaviour).

## Step 3: format check (read-only)
```bash
make fmt-check
```

## Step 4: autofix (mutating, only if step 3 failed)
```bash
make fmt
```
ruff format. Note **which files** it changed.

## Step 5: static analysis again
```bash
make types
make lint
```
**Only if step 4 changed something**; otherwise steps 1-2 stand.

## Step 6: tests + coverage gate
```bash
make coverage
```
Full pytest run (pytest-asyncio, respx) with the 85 % coverage gate (generated code excluded). A drop below the gate almost always means new code without tests: fix with tests (rule 0b), never by lowering the threshold, adding to `omit`, or a `# pragma: no cover` without a reason and an issue reference.

## Step 7: generated code is in sync
```bash
make codegen-check
```
Dirty: someone edited generated paths (`src/whitemarket/_generated/`, `src/whitemarket/_sync/`, `graphql/operations/`, `graphql/fragments/`) or forgot `make codegen` after changing `src/whitemarket/_async/` or `graphql/overrides/`. Fix by regenerating, never by hand (CLAUDE.md rule 1).

## Step 8: dependencies
```bash
make audit
```
pip-audit: known vulnerabilities; fix by updating the package. An `--ignore-vuln` entry needs a reason and an issue reference on the same or previous line (the `suppress-check` hook enforces it). A module imported but not declared in `pyproject.toml` (shadow / transitive dependency, CLAUDE.md rule 10) is fixed by declaring the package, never by relying on the transitive install.

Only when **all steps** are green is the work ready.

## Pre-existing code

A violation on a symbol that existed before your diff (a stricter rule, a tool upgrade, your addition pushed it over a threshold) is **suppressed in place**, not refactored: a targeted suppression with a **specific code**, a reason and an issue reference on the same or previous line (CLAUDE.md rule 15), plus one line to the user:

```python
value = payload["id"]  # type: ignore[index]  # generated union lacks a discriminator, #12
```

Blanket forms (`# type: ignore`, `# noqa`, `# ruff: noqa`, `# mypy: ignore-errors`) are never acceptable. Check what you actually added:

```bash
git diff HEAD -- <file> | grep -c '^+'
```

Never add new errors to a baseline file or to `per-file-ignores` to make a step green.

## On demand, outside the mandatory run

- `make mutation`: mutation testing (mutmut). Before a PR touching core logic (retry, reconciliation, mapping, validation), or when asked.
- `make matrix`: `make check` over every supported CPython version (nox/tox, Docker). Before a release, or after touching version-sensitive code.
- `make build`: sdist + wheel, `twine check`. Before a release or after touching packaging.
- `make hooks-test`: after touching `.claude/hooks/**`.

## When to skip

Only `.claude/` skills/agents/commands, `*.md`, `docs/` without code blocks that are executed: steps 1-8 may be skipped; say so in one line.
