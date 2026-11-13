---
name: release-notes
description: >
  User-facing summary of what changed, in plain words, for CHANGELOG.md, a GitHub release or a PR description: what
  SDK users get, what breaks, how to migrate. Triggers: "/release-notes", "write the changelog entry", "release notes",
  "summarize the changes for users" (and the same in Russian or Ukrainian). Call ONLY on the user's request, at the end
  of a task or before a release.
---

# Release notes

The result of a task for someone who uses the SDK but does not read its code. Source: the session context (what was asked, what was done) plus the git diff for completeness. Output goes **to the chat**; `CHANGELOG.md` is edited only if the user asks.

## 1. Collect facts (silently)

```bash
git status --short
git diff HEAD --stat                       # or: git diff <last-tag>...HEAD --stat for a release
git diff HEAD -- src/ ':!src/whitemarket/_generated/**' ':!src/whitemarket/_sync/**' pyproject.toml schema/CHANGES.md
git describe --tags --abbrev=0             # last release, if any
```

Read only the hunks needed to understand user-visible behaviour, not the whole diff. The sync client mirrors the async one; describe a change once and say it applies to both.

## 2. Classify each change

| Section (Keep a Changelog) | What goes there |
|---|---|
| **Breaking** | removed/renamed public symbol, changed signature or return type, keyword-only change, tightened validation, changed default, raised minimum Python, dropped an extra, changed exception class for a case (CLAUDE.md rule 16) |
| Added | new high-level method, model field, option, event type, extra, generated operation from a schema sync |
| Changed | behaviour change that is not breaking (better retry timing, new log fields) |
| Deprecated | symbols still present, to be removed (emit `DeprecationWarning`); name the replacement |
| Fixed | bug fixes, from the user's point of view |
| Security | anything from `secure-coding` / `/security-review` that users should know (redaction, TLS, dependency advisory) |

In doubt whether it breaks: it breaks. Every breaking item shows `before -> after` and a migration snippet. Version bump: breaking -> major (minor while `0.x`), Added -> minor, Fixed only -> patch. State the proposed version in one line.

## 3. Language rules

- SDK user terms: method names as users call them (`client.buying.buy_cheapest(...)`, `await client.deals.statuses(...)`), option names, exception classes, extras (`pip install "whitemarket-sdk[live]"`). No internal module names, file paths, `path:line`, test names, rule numbers.
- One sentence per item. No filler. Do not invent behaviour the diff does not have.
- Server-side facts that affected the code (open questions from `docs/WHITEMARKET_API.md` section 11) are listed under "Notes" (SDK_SPEC 11).
- Parity: if the change must be mirrored in sister SDKs, one line after the notes, to the user, not in the notes.

## 4. Output format

```markdown
## [<version>] - <YYYY-MM-DD>

### Breaking
- `client.deals.statuses()` now returns `list[DealStatus]` instead of `dict[str, str]`.
  Before: `statuses = client.deals.statuses(ids)` -> `statuses[deal_id]`. After: `for s in client.deals.statuses(ids): ...`

### Added
- ...

### Fixed
- ...

### Notes
- ...
```

Drop empty sections. No secrets, IPs, personal data or real account data in examples; use placeholders (`os.environ["WHITEMARKET_PARTNER_TOKEN"]`).
