#!/usr/bin/env bash
# Regression tests for the Stop hook reuse-check.sh.
#
# Why: a hook that never fires looks exactly like a working one.
# Every case runs in a TEMPORARY git repository: the real project is not touched,
# and the session marker is written there too.
#
# Run from anywhere (only bash, git, jq, python3):
#   bash .claude/hooks/reuse-check-test.sh
# Exit code: 0 when every case passes, 1 otherwise.

set -u

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reuse-check.sh"
[ -f "$HOOK" ] || { echo "missing $HOOK"; exit 1; }

fail=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

setup_repo() { # recreates a clean repo with one commit
  rm -rf "$tmp/repo"
  mkdir -p "$tmp/repo/src/whitemarket"
  git -C "$tmp/repo" init -q
  git -C "$tmp/repo" config user.email test@example.invalid; git -C "$tmp/repo" config user.name test
  git -C "$tmp/repo" config commit.gpgsign false
  echo "seed" >"$tmp/repo/README.md"
  printf '"""Package."""\n' >"$tmp/repo/src/whitemarket/__init__.py"
  git -C "$tmp/repo" add -A >/dev/null
  git -C "$tmp/repo" commit -qm seed
}

# mk <path> <ClassName>... : a module defining the given classes (appends if it exists)
mk() {
  local f="$tmp/repo/$1"; shift
  mkdir -p "$(dirname "$f")"
  for c in "$@"; do printf '\n\nclass %s:\n    pass\n' "$c" >>"$f"; done
}

run() { # $1=session $2=stop_hook_active(true|false) -> prints the hook's stdout
  printf '{"session_id":"%s","stop_hook_active":%s}' "$1" "$2" \
    | CLAUDE_PROJECT_DIR="$tmp/repo" bash "$HOOK" 2>/dev/null
}

chk() { # $1=want(BLOCK|PASS) $2=label $3=grep pattern inside the reason (optional)
  local out got
  out="$(run "${SESSION:-s1}" false)"
  got=PASS; [ -n "$out" ] && got=BLOCK
  if [ "$got" != "$1" ]; then
    printf '  FAIL  want=%-5s got=%-5s %s\n' "$1" "$got" "$2"; fail=$((fail+1)); return
  fi
  if [ -n "${3:-}" ] && ! printf '%s' "$out" | grep -qF -- "$3"; then
    printf '  FAIL  BLOCK without "%s" %s\n' "$3" "$2"; fail=$((fail+1)); return
  fi
  printf '  ok    %-5s %s\n' "$got" "$2"
}

echo "== N new classes of the same role: every role =="
n=0
for role in Mapper Builder Parser Decoder Client Store Validator Factory; do
  n=$((n + 1))
  setup_repo; mk "src/whitemarket/market/listing.py" "Listing${role}"; mk "src/whitemarket/deals/deal.py" "Deal${role}"
  SESSION=r$n chk BLOCK "2 new *${role}" "${role} (x2)"
done

echo "== Python specifics =="
setup_repo; mk src/whitemarket/mappers.py ListingMapper DealMapper
SESSION=p1 chk BLOCK "2 new *Mapper in ONE module" "Mapper (x2)"

setup_repo
printf 'class TokenStore(Protocol):\n    pass\n\n\nclass InMemoryTokenStore(TokenStore):\n    pass\n' >"$tmp/repo/src/whitemarket/store.py"
SESSION=p2 chk BLOCK "base class + subclass forms (Protocol, inheritance) are detected" "Store (x2)"

setup_repo; printf '    class InnerParser:\n        pass\nclass OuterParser:\n    pass\n' >"$tmp/repo/src/whitemarket/nested.py"
SESSION=p3 chk BLOCK "indented (nested) class counts" "Parser (x2)"

setup_repo; printf '# class FakeParser: in a comment\nx = "class OtherParser:"\n' >"$tmp/repo/src/whitemarket/notes.py"
mk src/whitemarket/real.py RealParser
SESSION=p4 chk PASS "class words in comments/strings are not definitions"

setup_repo; mk src/whitemarket/a.py MapperRegistry ParserOptions
SESSION=p5 chk PASS "role word as a prefix, not a suffix"

echo "== Boundaries =="
setup_repo; mk src/whitemarket/market/listing.py ListingMapper
SESSION=a1 chk PASS "1 new *Mapper"

setup_repo; mk src/whitemarket/market/listing.py ListingMapper; mk src/whitemarket/deals/deal.py DealParser
SESSION=a2 chk PASS "2 new classes of different roles"

setup_repo; mk src/whitemarket/a.py AParser; mk src/whitemarket/b.py BParser; mk src/whitemarket/c.py CParser
SESSION=a3 chk BLOCK "3 new *Parser in different modules" "rule 11"

setup_repo; mk src/whitemarket/errors.py AuthError RateLimitError
SESSION=a4 chk PASS "2 new *Error (role excluded on purpose)"

setup_repo; mk src/whitemarket/_generated/market_list.py MarketListClient; mk src/whitemarket/_generated/deal_list.py DealListClient
SESSION=a5 chk PASS "new classes under _generated are ignored"

setup_repo; mk src/whitemarket/_sync/market.py MarketClient; mk src/whitemarket/_sync/deals.py DealsClient
SESSION=a6 chk PASS "new classes under _sync (generated mirror) are ignored"

setup_repo; mk src/whitemarket/_generated/x.py MarketListMapper; mk src/whitemarket/market.py ListingMapper
SESSION=a7 chk PASS "one generated + one hand-written Mapper is not a pair"

setup_repo; mk tests/unit/test_market.py FakeMarketClient; mk tests/unit/test_deals.py FakeDealsClient
SESSION=a8 chk PASS "new classes in tests/ are ignored"

echo "== Modified files: only new class statements count =="
setup_repo
mk src/whitemarket/factories.py AFactory BFactory
git -C "$tmp/repo" add -A >/dev/null; git -C "$tmp/repo" commit -qm add >/dev/null
printf '\n# touch\n' >>"$tmp/repo/src/whitemarket/factories.py"
SESSION=m1 chk PASS "editing a module with 2 existing *Factory"

setup_repo
mk src/whitemarket/factories.py AFactory
git -C "$tmp/repo" add -A >/dev/null; git -C "$tmp/repo" commit -qm add >/dev/null
mk src/whitemarket/factories.py BFactory; mk src/whitemarket/other.py CFactory
SESSION=m2 chk BLOCK "2 new classes added (one into an existing module)" "Factory (x2)"

setup_repo; mk src/whitemarket/a.py AFactory; mk src/whitemarket/b.py BFactory
git -C "$tmp/repo" add -A >/dev/null
SESSION=m3 chk BLOCK "staged (added, not committed) files count as new"

echo "== Repository without commits =="
rm -rf "$tmp/repo"; mkdir -p "$tmp/repo"; git -C "$tmp/repo" init -q
mk src/whitemarket/a.py AFactory; mk src/whitemarket/b.py BFactory
git -C "$tmp/repo" add -A >/dev/null
SESSION=e1 chk BLOCK "staged files before the first commit count as new"

echo "== Gates =="
setup_repo; mk src/whitemarket/a.py AFactory; mk src/whitemarket/b.py BFactory
out1="$(run g1 false)"; out2="$(run g1 false)"
if [ -n "$out1" ] && [ -z "$out2" ]; then echo "  ok    PASS  a repeat in the same session does not block"
else echo "  FAIL  session marker does not work (1='${out1:0:20}' 2='${out2:0:20}')"; fail=$((fail+1)); fi

if [ -f "$tmp/repo/var/claude/reuse-check-done" ] && grep -qx '\*' "$tmp/repo/var/claude/.gitignore" 2>/dev/null; then
  echo "  ok    STATE marker in var/claude/ with a self-ignoring .gitignore"
else echo "  FAIL  marker not in var/claude/ or .gitignore missing"; fail=$((fail+1)); fi

out3="$(run g2 true)"
if [ -z "$out3" ]; then echo "  ok    PASS  stop_hook_active=true does not block"
else echo "  FAIL  stop_hook_active is ignored"; fail=$((fail+1)); fi

setup_repo; mk src/whitemarket/a.py AFactory
out4="$(printf '{"session_id":"g3","stop_hook_active":false}' | CLAUDE_PROJECT_DIR="$tmp/nonexistent" bash "$HOOK" 2>/dev/null)"
if [ -z "$out4" ]; then echo "  ok    PASS  outside a git repository exits quietly"
else echo "  FAIL  fired outside a repository"; fail=$((fail+1)); fi

echo "== Mutations: the cases above must turn red on a broken hook =="
# A green test that is also green on a broken implementation checks nothing.
# Each mutation edits a COPY of the hook in the temp dir; the original is untouched.
MUT="$tmp/mutant.sh"
mut_chk() { # $1=want(BLOCK|PASS) $2=label $3=sed expression
  sed "$3" "$HOOK" >"$MUT"
  if cmp -s "$HOOK" "$MUT"; then printf '  FAIL  mutation did not apply: %s\n' "$2"; fail=$((fail+1)); return; fi
  local got=PASS
  [ -n "$(printf '{"session_id":"m%s","stop_hook_active":false}' "$RANDOM" \
    | CLAUDE_PROJECT_DIR="$tmp/repo" bash "$MUT" 2>/dev/null)" ] && got=BLOCK
  if [ "$got" = "$1" ]; then printf '  ok    %-5s %s\n' "$got" "$2"
  else printf '  FAIL  want=%-5s got=%-5s %s\n' "$1" "$got" "$2"; fail=$((fail+1)); fi
}

setup_repo; mk src/whitemarket/a.py AListingFactory; mk src/whitemarket/b.py BListingFactory
mut_chk PASS "duplicate threshold 2->99 silences detection" "s/>= 2 { print/>= 99 { print/"

setup_repo; mk src/whitemarket/errors.py AuthError RateLimitError
mut_chk BLOCK "Error added to ROLES starts being caught" "s/|Validator|Factory'/|Validator|Factory|Error'/"

setup_repo; mk src/whitemarket/_sync/market.py MarketClient; mk src/whitemarket/_sync/deals.py DealsClient
mut_chk BLOCK "dropping the _sync exclusion catches the generated mirror" "s# ':(exclude,glob)src/whitemarket/_sync/\*\*'##"

setup_repo; mk src/whitemarket/a.py AFactory
git -C "$tmp/repo" add -A >/dev/null; git -C "$tmp/repo" commit -qm add >/dev/null
mk src/whitemarket/a.py BFactory; mk src/whitemarket/b.py CFactory
mut_chk PASS "ignoring added lines of tracked files misses a class added to an existing module" 's/^  git diff "\$BASE" -U0/  true || git diff "$BASE" -U0/'

echo
[ "$fail" -eq 0 ] && { echo "RESULT: all cases passed"; exit 0; }
echo "RESULT: failed cases: $fail"; exit 1
