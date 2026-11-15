# Owner decisions on the v0.1 open questions (2026-11-14)

Answers to `docs/plans/2026-11-13-sdk-v0.1.md` "Open questions". Items marked **SPEC + PHP first** change shared
behaviour: they go to `docs/SDK_SPEC.md` and the PHP reference SDK (in a PHP session, CLAUDE.md rule 18), then
here. This repository never edits the sister repositories.

| # | Question | Decision | Where |
|---|---|---|---|
| 1 | Install `uv` | Installed. Developers choose `uv` or `pip` (no poetry): `uv.lock` + hash-pinned `requirements-*.txt`, `make install PM=uv\|pip` | this repo |
| 17 | JWT expiry | A past `exp`, or an `exp` within the 5 min margin, counts as expired: refresh before sending, no extra 401 round trip | **SPEC 3.1 + PHP first**, then Python; SPEC + PHP done 2026-11-14, Python done 2026-11-15 |
| 18 | Query attempt budget across the 401 replay | One budget per call: the replay uses one of the `max_attempts`; total sends of a query <= `max_attempts` (+ the token exchange); a replay after a 401 on the last attempt still happens once | **SPEC 1.4 + PHP first**, then Python; SPEC + PHP done 2026-11-14, Python done 2026-11-15 |
| 26 | Cancellation (`CancelledError` / `KeyboardInterrupt`) during `market_buy` | Keep: propagates at once, no reconciliation; README tells callers to persist `custom_id` and check `deals.get(custom_id)` (Python idiom; recorded in DEVIATIONS) | this repo, no change |
| 29 | Reconciliation accepts a found deal only with the same `customId` | Adopt (Python has it): a mismatch or null `customId` is a failed lookup, attempts continue | **SPEC 3.3 + PHP** |
| V1 r5 | Batch row identity checked before money/wear decode | Adopt (Python has it): an identity mismatch makes the chunk Unknown even when the product cannot be decoded | **SPEC 3.5 rules 3/7 + PHP** |
| 22 | Every request forces `follow_redirects=False` and no client auth, also through an injected client | Adopt (Python has it) "where the HTTP client allows a per-request override"; PHP records a DEVIATIONS row if PSR-18 cannot | **SPEC 1.3 + PHP** |
| 23 | Live WebSocket client | Replace `centrifuge-python` with an own minimal Centrifugo JSON protocol client over `websockets` (declared directly, extra `live`), as PHP did; drop the workarounds | this repo (SPEC 3.11 already allows it) |
| 31 | Agent may edit Makefile/tools/pyproject/.github and run `make *` without a prompt | Ask before Edit/Write of `Makefile`, `tools/**`, `pyproject.toml`, `.github/**`; `make *` stays allowed | this repo done; **PHP: same rule** (its build files) |
| 33 | Schema `@example` trade URLs | Owner verified 2026-11-14: the example trade URLs are no longer valid; they are public doc examples. No scrubbing. Accepted-limitations row in DEVIATIONS so reviews stop flagging it | this repo done; **PHP: same row** in its DEVIATIONS "Accepted limitations" |
| 34 | gitleaks covers only the working tree | Add a full-history `gitleaks git` scan in CI (fetch-depth 0) and `make secrets-scan-history`; anchor `.gitleaks.toml` allowlist paths to the repo root | this repo; **PHP: same** |
| 35 | Mutation testing | Parity with PHP (checked: PHP ci.yml `mutation` job, Infection on every PR for changed lines and full on push to main / manual, infection.json5 `minMsi` 80, `minCoveredMsi` 90): CI `mutation` job, full run on push to main and workflow_dispatch, changed files on PRs where mutmut allows, gate 80 % (score today 83.5 %); covered-score 90 % is a target after killing the survivors (profile/wallet mappers, client constructor) | this repo; PHP already has it |
| 23b | SDK_SPEC 3.11 still names `centrifuge-python` as the Python WS client | Change SDK_SPEC 3.11: Python uses an own minimal Centrifugo JSON client over `websockets` (like PHP) | **SPEC 3.11** |
| 3 | High-level `orders` module (SDK_SPEC 3.7) | 0.2.0, together with PHP: PHP designs the API first, Python mirrors it; 0.1 keeps the generated `order_*` operations and the CHANGELOG known limitation | **PHP first**, then Python 0.2.0 |
| P4-2 | `MutationOutcomeUnknownError(operation, check_hint)` | Remove `check_hint`; the error builds the "where to check" hint from the operation name, (correction: PHP still takes `checkHint` in the constructor) | this repo done (dd98687); **PHP: same change** |
| P4-3 | `WalletTransfer.from_` / `.to` | Keep `from_` / `to` (Python idiom for the keyword `from`) | this repo, no change |
| 27 | Batch chunk answered 401 after the refresh + replay | `NOT_SENT` (server rejected before execution, SDK_SPEC 1.4); a client-thrown exception stays `UNKNOWN`. PHP: make the distinction explicit (server 401 answer vs client exception) | this repo, no change; **PHP: wording/test** |
| 30 | `deals.wait_for(live=...)`: early wake-up rate and clock | Keep: early re-check at most once per 1 s after the poll began; the deadline uses a monotonic clock | this repo, no change; **SPEC 3.4 rules 4/8 + PHP** |
| 6, 11, 12, 2, 19, 20, 21 | Unknown enum pseudo-member; sync total timeout; sync/async store and provider twins; superpowers plugin; `#0` issue placeholder; ijson segfault upstream; re-exported generated enums | All defaults kept. `superpowers`: install from a local terminal (`/plugin install superpowers` is not available over Remote Control). `#0`: replace with a real "suppressions to review" issue after the first push | this repo |

## Still for the backend team (not owner decisions)

- `MarketProductResult.index` base and the maximum batch size of `market_*_multiple`.
- Products CSV export header: does it name the JSON keys?
- Catalogue of `extensions.category` values (which ones are business rejections vs post-commit failures).
- Does a seller deal's product id equal the listed product id (the `sell_*` examples assume it)?
