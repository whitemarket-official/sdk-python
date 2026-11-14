# Owner decisions on the v0.1 open questions (2026-11-14)

Answers to `docs/plans/2026-11-13-sdk-v0.1.md` "Open questions". Items marked **SPEC + PHP first** change shared
behaviour: they go to `docs/SDK_SPEC.md` and the PHP reference SDK (in a PHP session, CLAUDE.md rule 18), then
here. This repository never edits the sister repositories.

| # | Question | Decision | Where |
|---|---|---|---|
| 1 | Install `uv` | Installed. Developers choose `uv` or `pip` (no poetry): `uv.lock` + hash-pinned `requirements-*.txt`, `make install PM=uv\|pip` | this repo |
| 17 | JWT expiry | A past `exp`, or an `exp` within the 5 min margin, counts as expired: refresh before sending, no extra 401 round trip | **SPEC 3.1 + PHP first**, then Python |
| 18 | Query attempt budget across the 401 replay | One budget per call: the replay uses one of the `max_attempts`; total sends of a query <= `max_attempts` (+ the token exchange); a replay after a 401 on the last attempt still happens once | **SPEC 1.4 + PHP first**, then Python |
| 26 | Cancellation (`CancelledError` / `KeyboardInterrupt`) during `market_buy` | Keep: propagates at once, no reconciliation; README tells callers to persist `custom_id` and check `deals.get(custom_id)` (Python idiom; recorded in DEVIATIONS) | this repo, no change |
| 29 | Reconciliation accepts a found deal only with the same `customId` | Adopt (Python has it): a mismatch or null `customId` is a failed lookup, attempts continue | **SPEC 3.3 + PHP** |
| V1 r5 | Batch row identity checked before money/wear decode | Adopt (Python has it): an identity mismatch makes the chunk Unknown even when the product cannot be decoded | **SPEC 3.5 rules 3/7 + PHP** |
| 22 | Every request forces `follow_redirects=False` and no client auth, also through an injected client | Adopt (Python has it) "where the HTTP client allows a per-request override"; PHP records a DEVIATIONS row if PSR-18 cannot | **SPEC 1.3 + PHP** |
| 23 | Live WebSocket client | Replace `centrifuge-python` with an own minimal Centrifugo JSON protocol client over `websockets` (declared directly, extra `live`), as PHP did; drop the workarounds | this repo (SPEC 3.11 already allows it) |
| 31 | Agent may edit Makefile/tools/pyproject/.github and run `make *` without a prompt | Ask before Edit/Write of `Makefile`, `tools/**`, `pyproject.toml`, `.github/**`; `make *` stays allowed | this repo done; **PHP: same rule** (its build files) |
| 33 | Schema `@example` trade URLs | Owner verified 2026-11-14: the example trade URLs are no longer valid; they are public doc examples. No scrubbing. Accepted-limitations row in DEVIATIONS so reviews stop flagging it | this repo done; **PHP: same row** in its DEVIATIONS "Accepted limitations" |
