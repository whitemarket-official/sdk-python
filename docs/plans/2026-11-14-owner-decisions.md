# Owner decisions on the v0.1 open questions (2026-11-14)

Answers to `docs/plans/2026-11-13-sdk-v0.1.md` "Open questions". Items marked **SPEC + PHP first** change shared
behaviour: they go to `docs/SDK_SPEC.md` and the PHP reference SDK (in a PHP session, CLAUDE.md rule 18), then
here. This repository never edits the sister repositories.

| # | Question | Decision | Where |
|---|---|---|---|
| 1 | Install `uv` | Installed. Developers choose `uv` or `pip` (no poetry): `uv.lock` + hash-pinned `requirements-*.txt`, `make install PM=uv\|pip` | this repo |
| 17 | JWT expiry | A past `exp`, or an `exp` within the 5 min margin, counts as expired: refresh before sending, no extra 401 round trip | **SPEC 3.1 + PHP first**, then Python |
