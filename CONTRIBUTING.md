# Contributing

## Setup

Requirements: a supported CPython (see `requires-python` in `pyproject.toml`), Node.js 22+ (codegen tools), GNU Make,
Docker (only for the runtime-version matrix).

```bash
make install   # .venv + editable install with the dev, exports and live extras
make check     # everything CI runs
```

Run `make help` for all targets. Noisy targets print only errors and a summary; the full log is in `var/qc/<target>.log`
(`VERBOSE=1` shows everything). `make matrix` runs the unit tests on every supported Python version in Docker.

## Rules

- `src/whitemarket/_generated/`, `schema/`, `graphql/operations/`, `graphql/fragments/` are generated: never edit them by
  hand. Regenerate with `make schema` / `make codegen`; `make codegen-check` must stay clean. Hand-written selection
  overrides go to `graphql/overrides/`.
- `src/whitemarket/_sync/` is generated from `src/whitemarket/_async/` by `tools/unasync.py`: change the async code and
  regenerate.
- New behaviour and every bug fix come with tests. A bug fix starts with a failing test.
- Mutations are never retried automatically. Money and wear values are `decimal.Decimal`, never `float`.
- Never commit real tokens, credentials, IP addresses or personal data, including in test fixtures.

## Commit convention

```
type(scope): short title

description

Refs: #<issue>
```

Types: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`, `test`, `perf`, `build`, `ci`.
Breaking change: `type(scope)!:` and a `BREAKING CHANGE:` footer. Branches: `feature/<issue>-<slug>`, `fix/<issue>-<slug>`.
Pull requests target `main`.
