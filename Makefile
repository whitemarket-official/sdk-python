# One entry point for humans, agents and CI (CLAUDE.md "Commands").
# Noisy targets keep the full log in var/qc/<target>.log and print only errors and a summary; VERBOSE=1 prints everything.
# The exit code is the truth.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# uv is not required: a plain venv + pip (CLAUDE.md). CI and the matrix containers may override VENV.
PYTHON ?= python3
VENV ?= .venv
PY := $(VENV)/bin/python
BIN := $(VENV)/bin
INSTALL_EXTRAS ?= dev,exports,live

# ariadne-codegen lives in its own venv: its ruff requirement conflicts with the ruff pin of the dev extra.
CODEGEN_VENV ?= .venv-codegen

# Every CPython in bugfix or security status (https://devguide.python.org/versions/, checked 2026-11-13).
PY_VERSIONS := 3.11 3.12 3.13 3.14 3.15

QC := tools/qc-filter.sh

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

## --- dependencies -------------------------------------------------------------

.PHONY: install
install: ## Create the venv and install the package editable with the dev, exports and live extras
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e '.[$(INSTALL_EXTRAS)]'

.PHONY: install-codegen
install-codegen: ## Create the isolated codegen venv (ariadne-codegen, extra "codegen")
	@test -x $(CODEGEN_VENV)/bin/python || $(PYTHON) -m venv $(CODEGEN_VENV)
	$(CODEGEN_VENV)/bin/python -m pip install --quiet --upgrade pip
	$(CODEGEN_VENV)/bin/python -m pip install --quiet -e '.[codegen]'

## --- checks -------------------------------------------------------------------

.PHONY: check
check: fmt-check lint types coverage codegen-check audit ## Everything CI runs

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

.PHONY: coverage
coverage: ## Unit tests with the coverage gate (fail_under in pyproject.toml, generated code excluded)
	@$(QC) coverage $(BIN)/pytest tests/unit --cov --cov-report=term-missing \
		--cov-report=xml:var/qc/coverage.xml

.PHONY: mutation
mutation: ## Mutation tests (mutmut, config in pyproject.toml; results: .venv/bin/mutmut browse)
	@$(QC) mutation $(BIN)/mutmut run

.PHONY: audit
audit: ## Known vulnerabilities in the installed dependencies (the local editable package is skipped)
	@mkdir -p var/qc
# The exact pins of the venv, without the editable SDK itself; --strict fails if any of them cannot be audited
# (`--skip-editable` would count the SDK as a skipped dependency and fail --strict).
	@$(QC) audit bash -c 'set -e; $(PY) -m pip freeze --exclude-editable > var/qc/audit-requirements.txt; \
		$(BIN)/pip-audit --strict --no-deps --disable-pip --progress-spinner off -r var/qc/audit-requirements.txt'

.PHONY: build
build: ## Build sdist + wheel into dist/ and check the metadata
	@rm -rf dist
	@$(QC) build bash -c 'set -e; $(PY) -m build --outdir dist .; $(BIN)/twine check --strict dist/*'

## --- codegen ------------------------------------------------------------------

CODEGEN_NODE := cd tools/codegen && npm ci --silent --no-audit --no-fund && node

.PHONY: schema
schema: ## Fetch the partner schema by introspection
	cd tools/codegen && npm ci --silent --no-audit --no-fund && node fetch-schema.mjs

# Hook points for P1 (ADR 0001): the Python generated layer (ariadne-codegen in $(CODEGEN_VENV)) into
# src/whitemarket/_generated and the sync variant (tools/unasync.py: _async -> _sync). Both are added to `codegen`
# and to `codegen-check` (regenerate into var/codegen-check, then diff -r).
.PHONY: codegen
codegen: ## Regenerate operations and fragments from the committed schema
	@$(CODEGEN_NODE) generate-operations.mjs

.PHONY: codegen-check
codegen-check: ## Regenerate into var/codegen-check and fail on any diff
	@rm -rf var/codegen-check && mkdir -p var/codegen-check
	@$(QC) codegen-check bash -c '$(CODEGEN_NODE) generate-operations.mjs --out-dir ../../var/codegen-check \
		&& cd ../.. && diff -r graphql/operations var/codegen-check/graphql/operations \
		&& diff -r graphql/fragments var/codegen-check/graphql/fragments'

## --- runtime matrix -----------------------------------------------------------

# Each version runs in the official image as the host user, with its own venv inside the container (the host .venv
# is not touched) and without the pytest cache in the bind mount.
MATRIX_RUN = set -e; $(PYTHON) -m venv /tmp/venv; /tmp/venv/bin/python -m pip install --quiet --upgrade pip; \
	/tmp/venv/bin/python -m pip install --quiet -e ".[test,exports,live]"; \
	/tmp/venv/bin/python -m pytest -p no:cacheprovider tests/unit

.PHONY: matrix
matrix: ## Unit tests on every supported Python version in Docker (python:<v>-slim)
	@for v in $(PY_VERSIONS); do \
		echo "=== Python $$v"; \
		docker run --rm -u "$$(id -u):$$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
			-v "$(CURDIR)":/app -w /app python:$$v-slim bash -c '$(MATRIX_RUN)' || exit 1; \
	done

## --- agent tooling ------------------------------------------------------------

.PHONY: hooks-test
hooks-test: ## Regression tests of the .claude hooks
	@bash .claude/hooks/hooks-test.sh && bash .claude/hooks/hooks-test-agent-guard.sh \
		&& bash .claude/hooks/suppress-check-test.sh && bash .claude/hooks/reuse-check-test.sh
