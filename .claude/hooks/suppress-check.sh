#!/usr/bin/env bash
# Stop hook: catches silenced checks in the diff. Suppressing an analyser error
# hides the problem just like a guard that only removes a crash (CLAUDE.md rule 15,
# rule 0b "a guard that only hides a failure is not a fix").
#
# Signals:
#   A. An added line with a suppression that lacks a specific code, an issue
#      reference or a reason (reference and reason on the same or the previous
#      line). Suppressions:
#        Python (src/, tests/, tools/, examples/, top-level *.py; not the
#        generated src/whitemarket/_generated/ and src/whitemarket/_sync/):
#          # type: ignore[code]        code required
#          # noqa: CODE                code required (bare `# noqa`, `# ruff: noqa` are blanket)
#          # pyright: ignore[rule]     rule required; `# pyright: basic` is blanket
#          # nosec B123                code required
#          # mypy: ignore-errors       blanket, always reported
#          # mypy: disable-error-code=...
#          # pragma: no cover / no branch / no mutate
#        pyproject.toml: entries under ruff per-file-ignores, additions to ruff
#          `ignore`/`extend-ignore`, coverage `omit`/`exclude_lines`/`exclude_also`,
#          mutmut `do_not_mutate`, mypy `ignore_errors = true` /
#          `ignore_missing_imports = true` / `disable_error_code`, pyright
#          `report* = false|"none"|...`, `typeCheckingMode` below strict,
#          pip-audit `ignore-vuln`.
#        Makefile, .github/workflows/*: pip-audit `--ignore-vuln`.
#      Issue reference: `#<number>` or https://github.com/<owner>/<repo>/issues/<n>.
#      Reason: at least two words besides the tag, its codes, identifiers and the
#      reference, in the comment on the same line or on a comment line directly
#      above. Format:
#        x = payload["id"]  # type: ignore[index]  # generated union lacks a discriminator, #12
#        # Generated union lacks a discriminator, see #12
#        x = payload["id"]  # type: ignore[index]
#   B. Added lines in a baseline file of an analyser (none is configured today;
#      the list catches one if introduced). New violations do not go into a
#      baseline; regeneration is planned, in a separate commit.
#
# ruff format has no per-line ignore worth catching (`# fmt: off` changes layout,
# not findings), so it is not in the list.
#
# The trigger is DETERMINISTIC (git diff against HEAD + untracked files; in a
# repository without commits, against the empty tree). The hook does not decide
# whether a suppression is legitimate; it forces it to be justified or removed.
# Existing suppressions are not touched, only added lines.
#
# Loop-safe: stop_hook_active + marker (session|report hash). A new suppression in
# the same session changes the hash and blocks again; the same set blocks once.
# State: var/claude/suppress-check-done (git-ignored through var/claude/.gitignore).

set -u

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" 2>/dev/null || exit 0

input="$(cat 2>/dev/null || true)"
case "$input" in *'"stop_hook_active": true'*|*'"stop_hook_active":true'*) exit 0 ;; esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Diff base: HEAD, or the empty tree before the first commit (staged files count as added).
BASE="$(git rev-parse -q --verify HEAD 2>/dev/null || git hash-object -t tree /dev/null 2>/dev/null)"

SUPPRESS='#[ \t]*(type:[ \t]*ignore|noqa|ruff:[ \t]*noqa|pyright:[ \t]*(ignore|basic|report)|nosec|mypy:[ \t]*(ignore-errors|disable-error-code)|pragma:[ \t]*no[ \t]+(cover|branch|mutate))'
TICKET='#[0-9]+|https://github[.]com/[^ ]+/issues/[0-9]+'
PY_PATHS=(':(glob)src/**/*.py' ':(glob)src/**/*.pyi' ':(glob)tests/**/*.py' ':(glob)tools/**/*.py'
          ':(glob)examples/**/*.py' ':(glob)*.py'
          ':(exclude,glob)src/whitemarket/_generated/**' ':(exclude,glob)src/whitemarket/_sync/**')
PYPROJECT=pyproject.toml
PYPROJECT_RE='ignore_errors[ \t]*=[ \t]*true|ignore_missing_imports[ \t]*=[ \t]*true|report[A-Za-z]+[ \t]*=[ \t]*(false|"none"|"information"|"warning")|typeCheckingMode[ \t]*=[ \t]*"(off|basic|standard)"|ignore-vuln'
VULN_IGNORE='--ignore-vuln'
VULN_PATHS=(Makefile ':(glob).github/workflows/*')
BASELINES=(mypy-baseline.txt .pyright-baseline.json .basedpyright/baseline.json .secrets.baseline)

# Shared awk helpers: does a line pair carry a specific code, an issue reference and a reason?
AWK_LIB='
function is_comment(s) { return s ~ /^[ \t]*#/ }
function comment_part(s,   i) { i = index(s, "#"); return i ? substr(s, i) : "" }
function code_ok(s) {
  if (s ~ /type:[ \t]*ignore/ && s !~ /type:[ \t]*ignore\[[A-Za-z]/) return 0
  if (s ~ /noqa/ && s !~ /noqa:[ \t]*[A-Z]+[0-9]+/) return 0
  if (s ~ /pyright:[ \t]*ignore/ && s !~ /pyright:[ \t]*ignore\[[A-Za-z]/) return 0
  if (s ~ /pyright:[ \t]*basic/) return 0
  if (s ~ /nosec/ && s !~ /nosec[ \t]+B[0-9]+/) return 0
  if (s ~ /mypy:[ \t]*ignore-errors/) return 0
  return 1
}
function reason_words(s,   t, n, i, w, c, lw) {
  t = s
  gsub(/https?:\/\/[^ \t]+/, " ", t)
  gsub(/type:[ \t]*ignore(\[[^]]*\])?/, " ", t)
  gsub(/pyright:[ \t]*ignore(\[[^]]*\])?/, " ", t)
  gsub(/pyright:[ \t]*[A-Za-z]+([ \t]*=[ \t]*"?[A-Za-z]+"?)?/, " ", t)
  gsub(/ruff:[ \t]*noqa/, " ", t)
  gsub(/noqa(:[ \t]*[A-Z]+[0-9]+([ \t]*,[ \t]*[A-Z]+[0-9]+)*)?/, " ", t)
  gsub(/mypy:[ \t]*[a-z-]+(=[^#]*)?/, " ", t)
  gsub(/pragma:[ \t]*no[ \t]+[a-z]+/, " ", t)
  gsub(/\[[^]]*\]/, " ", t)
  gsub(/[A-Z]+[0-9]+/, " ", t)
  gsub(/#[0-9]+/, " ", t)
  gsub(/[A-Za-z0-9_]+[.:]+[A-Za-z0-9_.:]+/, " ", t)
  n = split(t, w, /[^A-Za-z]+/)
  c = 0
  for (i = 1; i <= n; i++) {
    lw = tolower(w[i])
    if (length(lw) < 3) continue
    if (lw ~ /^(see|issue|issues|todo|fixme|ref|refs|github|http|https|the|and|for|ignore|line|next|type|noqa|nosec|pragma|cover|branch|mutate|pyright|mypy|ruff|file)$/) continue
    c++
  }
  return c
}
function justified(cur, prev,   words) {
  if (!code_ok(cur)) return 0
  if (cur !~ tk && prev !~ tk) return 0
  words = reason_words(comment_part(cur))
  if (is_comment(prev)) words += reason_words(prev)
  return words >= 2
}
'

# --- Signal A: line suppressions ---------------------------------------------
# Tracked: unified diff with one line of context, to see the previous line
# (a reason comment above the suppressed line). Prints `path:line: text`.
scan_diff() { # $1=regex, rest=pathspecs
  local re="$1"; shift
  git diff "$BASE" -U1 --no-color -- "$@" 2>/dev/null | awk -v re="$re" -v tk="$TICKET" "$AWK_LIB"'
    /^\+\+\+ / { file = substr($0, 7); next }
    /^@@/      { split($3, a, ","); line = substr(a[1], 2) + 0; prev = ""; next }
    /^-/       { next }
    /^[+ ]/    {
      text = substr($0, 2)
      if (substr($0, 1, 1) == "+" && text ~ re && !justified(text, prev)) {
        t = text; sub(/^[ \t]+/, "", t); printf "%s:%d: %s\n", file, line, t
      }
      prev = text; line++
    }'
}

scan_file() { # $1=regex $2=file: every line counts as added (untracked file)
  awk -v re="$1" -v tk="$TICKET" -v file="$2" "$AWK_LIB"'
    $0 ~ re && !justified($0, prev) { t = $0; sub(/^[ \t]+/, "", t); printf "%s:%d: %s\n", file, NR, t }
    { prev = $0 }' "$2" 2>/dev/null
}

# pyproject.toml: section-aware. $1=file $2=added line numbers ("ALL" for an untracked file).
scan_pyproject() {
  awk -v added=" $2 " -v tk="$TICKET" -v file="$1" -v pre="$PYPROJECT_RE" -v sq="'" "$AWK_LIB"'
    function is_added(n) { return added == " ALL " || index(added, " " n " ") > 0 }
    function quoted(s) { return index(s, "\"") > 0 || index(s, sq) > 0 }
    {
      line = $0; flag = 0
      if (line ~ /^[ \t]*\[/) { section = line; arr = ""; prev = line; next }
      if (!is_comment(line) && line !~ /^[ \t]*$/) {
        if (arr != "") {
          if (quoted(line)) flag = 1
          if (line ~ /\]/) arr = ""
        } else {
          key = ""
          if (match(line, /^[ \t]*[A-Za-z_-]+[ \t]*=/)) { key = substr(line, RSTART, RLENGTH); gsub(/[ \t=]/, "", key) }
          listkey = (key ~ /^(ignore|extend-ignore)$/ && section ~ /tool\.ruff/) \
                 || (key ~ /^(exclude_lines|exclude_also|omit)$/ && section ~ /tool\.coverage/) \
                 || (key == "do_not_mutate" && section ~ /mutmut/) \
                 || key == "disable_error_code"
          if (listkey) {
            v = line; sub(/^[^=]*=/, "", v)
            if (v ~ /["\047]/) flag = 1
            if (v ~ /\[/ && v !~ /\]/) arr = key
          }
          if (section ~ /per-file-ignores/ && line ~ /=/) flag = 1
          if (line ~ /per-file-ignores[ \t]*=/ && quoted(line)) flag = 1
          if (line ~ pre) flag = 1
        }
      }
      if (flag && is_added(NR) && !justified(line, prev)) {
        t = line; sub(/^[ \t]+/, "", t); printf "%s:%d: %s\n", file, NR, t
      }
      prev = line
    }' "$1" 2>/dev/null
}

added_lines() { # $1=file: line numbers added in the working tree vs BASE
  git diff "$BASE" -U0 --no-color -- "$1" 2>/dev/null | awk '
    /^@@/ { split($3, a, ","); s = substr(a[1], 2) + 0; c = (a[2] == "" ? 1 : a[2] + 0)
            for (i = 0; i < c; i++) printf "%d ", s + i }'
}

tracked="$(scan_diff "$SUPPRESS" "${PY_PATHS[@]}")"
tracked_vuln="$(scan_diff "$VULN_IGNORE" "${VULN_PATHS[@]}")"

untracked=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  untracked="${untracked}$(scan_file "$SUPPRESS" "$f")
"
done < <(git ls-files --others --exclude-standard -- "${PY_PATHS[@]}" 2>/dev/null)
while IFS= read -r f; do
  [ -z "$f" ] && continue
  untracked="${untracked}$(scan_file "$VULN_IGNORE" "$f")
"
done < <(git ls-files --others --exclude-standard -- "${VULN_PATHS[@]}" 2>/dev/null)

pyproject_report=""
if [ -f "$PYPROJECT" ]; then
  if [ -n "$(git ls-files --others --exclude-standard -- "$PYPROJECT" 2>/dev/null)" ]; then
    pyproject_report="$(scan_pyproject "$PYPROJECT" ALL)"
  else
    lines="$(added_lines "$PYPROJECT")"
    [ -n "$lines" ] && pyproject_report="$(scan_pyproject "$PYPROJECT" "$lines")"
  fi
fi

suppress_report="$(printf '%s\n%s\n%s\n%s\n' "$tracked" "$tracked_vuln" "$untracked" "$pyproject_report" | grep -v '^$' || true)"

# --- Signal B -----------------------------------------------------------------
baseline_report="$(git diff "$BASE" --numstat -- "${BASELINES[@]}" 2>/dev/null | awk '$1 > 0 { printf "%s (+%s)\n", $3, $1 }')"
for b in "${BASELINES[@]}"; do
  if [ -n "$(git ls-files --others --exclude-standard -- "$b" 2>/dev/null)" ] && [ -s "$b" ]; then
    baseline_report="${baseline_report:+$baseline_report
}$b (+$(wc -l <"$b" | tr -d ' '), new file)"
  fi
done

[ -z "$suppress_report" ] && [ -z "$baseline_report" ] && exit 0

# --- Gate: once per session per concrete set of findings ----------------------
state_dir="var/claude"
done_file="$state_dir/suppress-check-done"
session="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$session" ] && session="nosession"
digest="$(printf '%s\n%s' "$suppress_report" "$baseline_report" | shasum 2>/dev/null | cut -c1-12)"
key="${session}|${digest}"

if [ -f "$done_file" ] && grep -qxF "$key" "$done_file" 2>/dev/null; then
  exit 0
fi
mkdir -p "$state_dir" 2>/dev/null
[ -f "$state_dir/.gitignore" ] || printf '*\n' >"$state_dir/.gitignore" 2>/dev/null
printf '%s\n' "$key" >>"$done_file"
if [ "$(wc -l <"$done_file" 2>/dev/null || echo 0)" -gt 100 ]; then
  tail -n 50 "$done_file" >"${done_file}.tmp" 2>/dev/null && mv "${done_file}.tmp" "$done_file"
fi

reason=""

if [ -n "$suppress_report" ]; then
  reason="WARN: CLAUDE.md rule 15: new suppressions in the diff without a specific code, an issue reference or a reason:
$(printf '%s\n' "$suppress_report" | head -20 | sed 's/^/    /')

A silenced error hides the problem like a guard that only removes a crash. For each line, one of two:
  (a) remove the suppression and fix the cause (type, decomposition, test);
  (b) the suppression is needed (analyser false positive, generated-code shape, pre-existing code). Then a specific code, a reason and a GitHub issue reference on the same or the previous line: \`x = payload[\"id\"]  # type: ignore[index]  # generated union lacks a discriminator, #12\`, and one line to the user. Blanket forms (bare \`# type: ignore\`, \`# noqa\`, \`# ruff: noqa\`, \`# mypy: ignore-errors\`) are never acceptable.
"
fi

if [ -n "$baseline_report" ]; then
  reason="${reason}
WARN: lines added to an analyser baseline:
$(printf '%s\n' "$baseline_report" | sed 's/^/    /')

New violations do not go into a baseline (CLAUDE.md rule 15). Unless this is a planned regeneration in a separate commit, revert the baseline and fix the violation. If it is planned, tell the user explicitly.
"
fi

printf '{"decision":"block","reason":%s}\n' \
  "$(printf '%s' "$reason" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$reason")"
exit 0
