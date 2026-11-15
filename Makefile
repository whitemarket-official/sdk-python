# One entry point for humans, agents and CI (CLAUDE.md "Commands").
# Noisy targets keep the full log in var/qc/<target>.log and print only errors and a summary; VERBOSE=1 prints everything.
# The exit code is the truth.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Two package managers, one result (CONTRIBUTING "Setup"): PM=uv installs from uv.lock, PM=pip installs from the
# hash-pinned requirements-*.txt exported from it. Default: uv when it is on the PATH, else pip. CI and the matrix
# containers may override VENV.
PYTHON ?= python3
PM ?= $(if $(shell command -v uv 2>/dev/null),uv,pip)
ifeq ($(filter $(PM),uv pip),)
$(error PM must be uv or pip, got '$(PM)')
endif
VENV ?= .venv
PY := $(VENV)/bin/python
BIN := $(VENV)/bin

# ariadne-codegen lives in its own venv: its ruff requirement conflicts with the ruff pin of the dev extra
# (uv.lock holds both, see [tool.uv] conflicts in pyproject.toml).
CODEGEN_VENV ?= .venv-codegen

# Every CPython in bugfix or security status (https://devguide.python.org/versions/, checked 2026-11-13).
PY_VERSIONS := 3.11 3.12 3.13 3.14 3.15

# The extras of each environment. The pip files are `uv export` of the same selection (target `lock`).
DEV_EXTRAS := dev exports live
TEST_EXTRAS := test exports live
CODEGEN_EXTRAS := codegen
UV_EXTRA_ARGS = $(foreach e,$(1),--extra $(e))

QC := tools/qc-filter.sh

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

## --- dependencies -------------------------------------------------------------

# One environment = one lock selection. uv: `uv sync --frozen` (exact, removes extras not in the selection).
# pip: a fresh venv + `--require-hashes` + the editable project without its dependencies.
# $(1) venv, $(2) extras for uv, $(3) requirements file for pip.
define INSTALL_ENV
@if [ "$(PM)" = uv ]; then \
	UV_PROJECT_ENVIRONMENT=$(1) uv sync --frozen --quiet $(call UV_EXTRA_ARGS,$(2)); \
else \
	test -x $(1)/bin/python || $(PYTHON) -m venv $(1); \
	$(1)/bin/python -m pip install --quiet --disable-pip-version-check --require-hashes -r $(3); \
	$(1)/bin/python -m pip install --quiet --disable-pip-version-check --no-deps -e .; \
fi
endef

.PHONY: install
install: ## Create .venv from the lock (PM=uv|pip, default uv if installed) and the codegen venv
	$(call INSTALL_ENV,$(VENV),$(DEV_EXTRAS),requirements-dev.txt)
	@$(MAKE) --no-print-directory $(CODEGEN_STAMP)

.PHONY: install-codegen
install-codegen: ## Create the isolated codegen venv (ariadne-codegen, extra "codegen")
	$(call INSTALL_ENV,$(CODEGEN_VENV),$(CODEGEN_EXTRAS),requirements-codegen.txt)
	@touch $(CODEGEN_VENV)/.installed

## --- lock ---------------------------------------------------------------------

LOCK_EXPORT = uv export --quiet --frozen --format requirements.txt --no-emit-project --no-annotate --no-header
# $(1) output directory
EXPORT_ALL = $(LOCK_EXPORT) $(call UV_EXTRA_ARGS,$(DEV_EXTRAS)) -o $(1)/requirements-dev.txt; \
	$(LOCK_EXPORT) $(call UV_EXTRA_ARGS,$(TEST_EXTRAS)) -o $(1)/requirements-test.txt; \
	$(LOCK_EXPORT) $(call UV_EXTRA_ARGS,$(CODEGEN_EXTRAS)) -o $(1)/requirements-codegen.txt

.PHONY: lock
lock: ## Re-resolve uv.lock from pyproject.toml and regenerate requirements-*.txt (needs uv); upgrade: make lock UPGRADE=1
	uv lock $(if $(UPGRADE),--upgrade)
	$(call EXPORT_ALL,.)

.PHONY: lock-check
lock-check: ## uv.lock and requirements-*.txt match pyproject.toml; the hatchling pin matches the lock (needs uv)
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "lock-check SKIPPED: uv is not installed (CI runs it; brew install uv)"; exit 0; fi; \
	rm -rf var/lock-check && mkdir -p var/lock-check; \
	$(QC) lock-check bash -c 'set -e; uv lock --check; \
		$(call EXPORT_ALL,var/lock-check); \
		for f in dev test codegen; do diff -u requirements-$$f.txt var/lock-check/requirements-$$f.txt || \
			{ echo "requirements-$$f.txt is stale: run make lock"; exit 1; }; done; \
		$(PYTHON) tools/ci/check_build_pin.py'

## --- checks -------------------------------------------------------------------

.PHONY: check
check: lock-check fmt-check lint types coverage codegen-check audit ## Everything CI runs

.PHONY: fmt
fmt: ## Format code (ruff format)
	@$(QC) fmt $(BIN)/ruff format .

.PHONY: fmt-check
fmt-check: ## Check formatting (ruff format --check)
	@$(QC) fmt-check $(BIN)/ruff format --check --diff .

.PHONY: lint
lint: ## Lint (ruff check)
	@$(QC) lint $(BIN)/ruff check --no-fix .

.PHONY: types
types: ## Static types: mypy --strict and pyright strict on src/
	@$(QC) types bash -c 'set -e; $(BIN)/mypy; $(BIN)/pyright --pythonpath $(PY)'

.PHONY: test
test: ## Unit tests; a subset: make test K=expr (pytest -k)
	@$(QC) test $(BIN)/pytest tests/unit $(if $(K),-k '$(K)')

.PHONY: test-memory
test-memory: ## Slow memory-bound streaming tests (tests/memory, about two minutes)
	@$(QC) test-memory $(BIN)/pytest tests/memory -m memory

.PHONY: coverage
coverage: ## Unit tests with the coverage gate (fail_under in pyproject.toml, generated code excluded)
	@$(QC) coverage $(BIN)/pytest tests/unit --cov --cov-report=term-missing \
		--cov-report=xml:var/qc/coverage.xml

# Empty: mutate everything. A git ref (origin/main): only the hand-written src/whitemarket files changed since the
# merge base with it (pull requests); mutants of an earlier run are discarded so the gate sees this run only.
MUTATE_CHANGED ?=

.PHONY: mutation
mutation: ## Mutation tests + score gate (mutmut, config in pyproject.toml; MUTATE_CHANGED=origin/main: diff only)
# mutmut forks the pytest process; on macOS urllib's system proxy lookup (SystemConfiguration, reached through
# httpx.Client()) segfaults in a forked child. A non-empty proxy environment makes urllib skip that lookup.
# The gate (tools/ci/mutation_gate.py) fails below 80 %: (killed + timeout) / (run - no_tests), as minMsi in the PHP SDK.
	@set -e; names=""; \
	if [ -n "$(MUTATE_CHANGED)" ]; then \
		names=$$($(BIN)/python tools/ci/mutation_gate.py names --base "$(MUTATE_CHANGED)"); \
		if [ -z "$$names" ]; then echo "mutation: no hand-written src/ file changed against $(MUTATE_CHANGED); skipped"; exit 0; fi; \
		rm -rf ./mutants; \
	fi; \
	NO_PROXY=127.0.0.1,localhost $(QC) mutation $(BIN)/mutmut run $$names; \
	$(BIN)/python tools/ci/mutation_gate.py gate

.PHONY: audit
audit: ## Known vulnerabilities in the locked dependencies (requirements-dev.txt and requirements-codegen.txt)
	@mkdir -p var/qc
# The exact pins the lock holds for each environment (the dev and codegen sets hold different ruff versions, so they
# are audited separately). The editable SDK is not in these files; --strict fails if a package cannot be audited.
	@$(QC) audit bash -c 'set -e; for f in dev codegen; do \
		$(BIN)/pip-audit --strict --no-deps --disable-pip --progress-spinner off -r requirements-$$f.txt; done'

.PHONY: build
build: ## Build sdist + wheel into dist/ from the locked environment (hatchling pinned), reproducible; twine check
	@rm -rf dist
# --no-isolation: the backend is the locked hatchling (tools/ci/check_build_pin.py keeps it equal to [build-system]).
# SOURCE_DATE_EPOCH (honoured by hatchling) = the commit time, so the same commit gives byte-identical artifacts.
	@SOURCE_DATE_EPOCH=$$(git log -1 --pretty=%ct 2>/dev/null || echo 315532800) \
		$(QC) build bash -c 'set -e; $(PY) -m build --no-isolation --outdir dist .; $(BIN)/twine check --strict dist/*'

## --- codegen ------------------------------------------------------------------

CODEGEN_NODE := cd tools/codegen && npm ci --silent --no-audit --no-fund && node

.PHONY: schema
schema: ## Fetch the partner schema by introspection
	cd tools/codegen && npm ci --silent --no-audit --no-fund && node fetch-schema.mjs

# Python generated layer (ADR 0001): node generator -> operations and fragments, then tools/codegen/generate.sh:
# ariadne-codegen (in $(CODEGEN_VENV)) on the async client -> src/whitemarket/_generated, then tools/unasync.py for
# the sync client and for src/whitemarket/_async -> src/whitemarket/_sync, then ruff format of _sync.
# The codegen venv is created on first use (stamp file, refreshed when pyproject.toml changes).
CODEGEN_STAMP := $(CODEGEN_VENV)/.installed

$(CODEGEN_STAMP): pyproject.toml uv.lock requirements-codegen.txt
	@$(MAKE) --no-print-directory install-codegen
	@touch $@

.PHONY: codegen
codegen: $(CODEGEN_STAMP) ## Regenerate operations, fragments, src/whitemarket/_generated and _sync from the committed schema
	@$(CODEGEN_NODE) generate-operations.mjs
	@PY=$(PY) RUFF=$(BIN)/ruff CODEGEN_VENV=$(CODEGEN_VENV) tools/codegen/generate.sh .

# Regenerates everything into var/codegen-check and fails on any difference with the committed files.
.PHONY: codegen-check
codegen-check: $(CODEGEN_STAMP) ## Regenerate into var/codegen-check and fail on any diff
	@rm -rf var/codegen-check && mkdir -p var/codegen-check
	@$(QC) codegen-check bash -c 'set -e; \
		($(CODEGEN_NODE) generate-operations.mjs --out-dir ../../var/codegen-check); \
		PY=$(PY) RUFF=$(BIN)/ruff CODEGEN_VENV=$(CODEGEN_VENV) tools/codegen/generate.sh var/codegen-check; \
		rc=0; \
		diff -r graphql/operations var/codegen-check/graphql/operations || rc=1; \
		diff -r graphql/fragments var/codegen-check/graphql/fragments || rc=1; \
		diff -r -x __pycache__ src/whitemarket/_generated var/codegen-check/src/whitemarket/_generated || rc=1; \
		diff -r -x __pycache__ src/whitemarket/_sync var/codegen-check/src/whitemarket/_sync || rc=1; \
		exit $$rc'

## --- runtime matrix -----------------------------------------------------------

# Each version runs in the official image as the host user, with its own venv inside the container (the host .venv
# is not touched) and without the pytest cache in the bind mount.
MATRIX_RUN = set -e; $(PYTHON) -m venv /tmp/venv; /tmp/venv/bin/python -m pip install --quiet --disable-pip-version-check --require-hashes -r requirements-test.txt; \
	/tmp/venv/bin/python -m pip install --quiet --disable-pip-version-check --no-deps -e .; \
	/tmp/venv/bin/python -m pytest -p no:cacheprovider tests/unit

.PHONY: matrix
matrix: ## Unit tests on every supported Python version in Docker (python:<v>-slim)
	@for v in $(PY_VERSIONS); do \
		echo "=== Python $$v"; \
		docker run --rm -u "$$(id -u):$$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
			-v "$(CURDIR)":/app -w /app python:$$v-slim bash -c '$(MATRIX_RUN)' || exit 1; \
	done

## --- examples -----------------------------------------------------------------

.PHONY: example
example: ## Run an example against the real API: make example NAME=ws_products_feed (needs WHITEMARKET_PARTNER_TOKEN)
	@test -n "$(NAME)" || { echo "usage: make example NAME=<file in examples/ without .py>"; exit 2; }
	$(PY) examples/$(NAME).py

## --- live smoke ---------------------------------------------------------------

.PHONY: live-smoke
live-smoke: ## Read-only calls against the real API (SDK_SPEC 6.4), needs WHITEMARKET_PARTNER_TOKEN; writes var/live-smoke/report.md; not part of check
	PYTHONPATH=tools $(PY) -m live_smoke

## --- repository hygiene -------------------------------------------------------

# Images pinned by tag and digest (digests checked with `docker pull` + `docker inspect`, 2026-11-14).
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
ACTIONLINT_IMAGE := rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667

.PHONY: secrets-scan
secrets-scan: ## gitleaks over the working tree (findings redacted)
	@$(QC) secrets-scan docker run --rm -v "$(CURDIR)":/repo -w /repo $(GITLEAKS_IMAGE) dir . --redact --no-banner \
		--config /repo/.gitleaks.toml

.PHONY: secrets-scan-history
secrets-scan-history: ## gitleaks over the whole git history (findings redacted)
	@$(QC) secrets-scan-history docker run --rm -v "$(CURDIR)":/repo $(GITLEAKS_IMAGE) git /repo --redact --no-banner \
		--config /repo/.gitleaks.toml

.PHONY: actionlint
actionlint: ## Lint GitHub Actions workflows
	@$(QC) actionlint docker run --rm -v "$(CURDIR)":/repo -w /repo $(ACTIONLINT_IMAGE) -no-color

## --- agent tooling ------------------------------------------------------------

.PHONY: hooks-test
hooks-test: ## Regression tests of the .claude hooks
	@bash .claude/hooks/hooks-test.sh && bash .claude/hooks/hooks-test-agent-guard.sh \
		&& bash .claude/hooks/suppress-check-test.sh && bash .claude/hooks/reuse-check-test.sh \
		&& bash .claude/hooks/shared-docs-sync-test.sh
