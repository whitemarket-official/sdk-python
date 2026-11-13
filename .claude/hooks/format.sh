#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): formats the edited Python file with
# `ruff format` (configuration in pyproject.toml). Formatting only: no
# `ruff check --fix`, no import sorting beyond what `ruff format` does; lint
# fixes are a deliberate step of quality-checks, not a side effect of an edit.
#
# Wired with "async": true in settings.json, so it runs in the background and
# never delays the edit. Every error is swallowed: the hook must never fail the
# edit, it always exits 0.
#
# Skipped: non-Python files, files outside the repo, generated code
# (src/whitemarket/_generated/ and src/whitemarket/_sync/ are formatted by their
# generators, rule 1), .venv/, and a missing .venv/bin/ruff (before `make install`).

set -u

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_response.filePath // .tool_input.file_path // empty' 2>/dev/null)

[[ -z "$file" ]] && exit 0
case "$file" in
  *.py|*.pyi) ;;
  *) exit 0 ;;
esac

repo_root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

rel="$file"
if [[ "$rel" == /* ]]; then
  [[ "$rel" == "$repo_root"/* ]] || exit 0
  rel="${rel#"$repo_root"/}"
fi
rel="${rel#./}"

case "$rel" in
  src/whitemarket/_generated/*|src/whitemarket/_sync/*|.venv/*) exit 0 ;;
esac

ruff="$repo_root/.venv/bin/ruff"
[[ -x "$ruff" ]] || exit 0

cd "$repo_root" || exit 0
"$ruff" format --quiet "$rel" >/dev/null 2>&1 || true
exit 0
