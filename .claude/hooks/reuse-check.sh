#!/usr/bin/env bash
# Stop hook: catches a systemic defect of AI-generated code named by reviewers:
# "a factory per method". Within one task, N classes of the same role
# (Mapper/Parser/Validator/...) are created instead of one abstraction with
# parameters. A reviewer then has to merge them by hand (CLAUDE.md rule 11).
#
# The trigger is DETERMINISTIC (git diff, not the model's memory). The answer is
# interactive: the hook does not decide whether it is duplication, it forces the
# agent to say "why not one" out loud before declaring the work done.
#
# Scope: NEW class definitions (`class XxxMapper...`) in hand-written
# src/**/*.py: added lines of tracked files (git diff HEAD, or against the empty
# tree before the first commit) plus every line of
# untracked files. Python keeps several classes per module, so the unit is the
# class statement, not the file name. Excluded: src/whitemarket/_generated/
# (one class per operation by design) and src/whitemarket/_sync/ (a generated
# mirror of _async/, it would double every class). Tests, docs, configs and
# classes that already existed are ignored.
#
# Not ported from the source repo: the "provider naming" signal (backend
# integration modules). Its SDK counterpart, rule 12 "API names only at the
# boundary", is a review item in clean-code-review.
#
# Loop-safe: stop_hook_active + marker (session|kind), once per session per kind.
# State: var/claude/reuse-check-done (git-ignored through var/claude/.gitignore).

set -u

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" 2>/dev/null || exit 0

input="$(cat 2>/dev/null || true)"
case "$input" in *'"stop_hook_active": true'*|*'"stop_hook_active":true'*) exit 0 ;; esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Diff base: HEAD, or the empty tree before the first commit (staged files count as new).
BASE="$(git rev-parse -q --verify HEAD 2>/dev/null || git hash-object -t tree /dev/null 2>/dev/null)"

PY=(':(glob)src/**/*.py' ':(exclude,glob)src/whitemarket/_generated/**' ':(exclude,glob)src/whitemarket/_sync/**')

# The role list is narrow on purpose: only roles where N of them almost always
# means copy-pasted logic. Deliberately NOT included: Error, Exception, Event,
# Enum, Input, Result, Request, Response, Operation, Model: one per API
# type/operation is normal.
ROLES='Mapper|Builder|Parser|Decoder|Client|Store|Validator|Factory'
CLASS_RE='^[[:space:]]*class[[:space:]]+[A-Za-z_][A-Za-z0-9_]*('"$ROLES"')[[:space:]]*[(:]'

# "path<TAB>ClassName" for every new class definition.
new_classes="$( {
  git diff "$BASE" -U0 --no-color -- "${PY[@]}" 2>/dev/null | awk '
    /^\+\+\+ / { file = substr($0, 7); next }
    /^\+/      { print file "\t" substr($0, 2) }'
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    awk -v file="$f" '{ print file "\t" $0 }' "$f" 2>/dev/null
  done < <(git ls-files --others --exclude-standard -- "${PY[@]}" 2>/dev/null)
} | awk -F '\t' -v re="$CLASS_RE" '
    $2 ~ re {
      line = $2
      sub(/^[ \t]*class[ \t]+/, "", line)
      sub(/[ \t]*[(:].*$/, "", line)
      print $1 "\t" line
    }' | sort -u )"

[ -z "$new_classes" ] && exit 0

# --- Signal: N new classes of the same role -----------------------------------
dup_roles="$(printf '%s\n' "$new_classes" | cut -f2 \
  | grep -oE "(${ROLES})\$" \
  | sort | uniq -c | awk '$1 >= 2 { print $2 }')"

dup_report=""
for role in $dup_roles; do
  entries="$(printf '%s\n' "$new_classes" | awk -F '\t' -v r="${role}\$" '$2 ~ r { printf "    %s (%s)\n", $2, $1 }')"
  dup_report="${dup_report}
  ${role} (x$(printf '%s\n' "$entries" | grep -c .)):
${entries}"
done

[ -z "$dup_report" ] && exit 0

# --- Gate: once per session per signal kind -----------------------------------
state_dir="var/claude"
done_file="$state_dir/reuse-check-done"
session="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$session" ] && session="nosession"

kind="dup"
if [ -f "$done_file" ] && grep -qxF "${session}|${kind}" "$done_file" 2>/dev/null; then
  exit 0
fi

mkdir -p "$state_dir" 2>/dev/null
[ -f "$state_dir/.gitignore" ] || printf '*\n' >"$state_dir/.gitignore" 2>/dev/null
printf '%s|%s\n' "$session" "$kind" >>"$done_file"
if [ "$(wc -l <"$done_file" 2>/dev/null || echo 0)" -gt 100 ]; then
  tail -n 50 "$done_file" >"${done_file}.tmp" 2>/dev/null && mv "${done_file}.tmp" "$done_file"
fi

reason="WARN: CLAUDE.md rule 11: the diff has several NEW classes of the same role:
${dup_report}

This is exactly the pattern that comes back from review: \"a factory per method with its own set of check and parse methods\" instead of one abstraction. BEFORE claiming readiness, read these classes side by side and answer OUT LOUD for each group one of two:
  (a) I merge them into one abstraction with parameters (or a Protocol + one implementation), and do it;
  (b) I keep them apart because <a concrete difference that outweighs the common part>.
Silently leaving N of them is not allowed. In doubt: option (a).
"

printf '{"decision":"block","reason":%s}\n' \
  "$(printf '%s' "$reason" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$reason")"
exit 0
