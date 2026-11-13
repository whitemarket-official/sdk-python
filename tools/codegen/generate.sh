#!/usr/bin/env bash
# Python generated layer: ariadne-codegen (async client) + unasync (sync client and sync hand-written code).
# Usage: tools/codegen/generate.sh <out-root>   ("." = the repository, anything else = a scratch tree inside it)
# Run from the repository root. The operation documents and fragments are read from <out-root>/graphql and must
# already be generated there (generate-operations.mjs). Writes <out-root>/src/whitemarket/{_generated,_sync}.
# Environment: CODEGEN_VENV (default .venv-codegen), RUFF (default .venv/bin/ruff).
set -euo pipefail

root="${1:?usage: generate.sh <out-root>}"
venv="${CODEGEN_VENV:-.venv-codegen}"
ruff="${RUFF:-.venv/bin/ruff}"
pkg="$root/src/whitemarket"
stage="$root/var/codegen"

# 1. Stage the documents: only operations/{query,mutation} and fragments (graphql/overrides must not be read twice).
rm -rf "$stage/documents"
mkdir -p "$stage/documents/operations"
cp -R "$root/graphql/operations/query" "$root/graphql/operations/mutation" "$stage/documents/operations/"
cp -R "$root/graphql/fragments" "$stage/documents/fragments"

# 2. ariadne-codegen with the paths of this run (output is deterministic: ariadne formats with `ruff --isolated`).
sed -e "s|^queries_path = .*|queries_path = \"$stage/documents\"|" \
    -e "s|^target_package_path = .*|target_package_path = \"$pkg\"|" \
    tools/codegen/ariadne.toml > "$stage/ariadne.toml"
rm -rf "$pkg/_generated"
mkdir -p "$pkg"
PYTHONPATH=tools/codegen "$venv/bin/ariadne-codegen" --config "$stage/ariadne.toml" > "$stage/ariadne.log" 2>&1 \
    || { cat "$stage/ariadne.log" >&2; exit 1; }

# 3. unasync: the generated async client and base client, then the hand-written async code.
python3 tools/unasync.py \
    --file "$pkg/_generated/client.py" "$pkg/_generated/sync_client.py" \
    --file "$pkg/_generated/async_base_client.py" "$pkg/_generated/base_client.py" \
    --tree src/whitemarket/_async "$pkg/_sync"
# Sorted imports (_sync names sort differently from _async ones) and formatting, as `make fmt` expects.
"$ruff" check --select I --fix --quiet "$pkg/_sync"
"$ruff" format --quiet "$pkg/_sync"
