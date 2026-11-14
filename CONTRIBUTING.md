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

## Make targets

| Goal | Command |
|---|---|
| everything CI runs (`fmt-check lint types coverage codegen-check audit`) | `make check` |
| format / check formatting | `make fmt` / `make fmt-check` |
| lint (ruff) | `make lint` |
| types (`mypy --strict` and pyright strict on `src/` and `examples/`) | `make types` |
| unit tests, one subset | `make test` / `make test K=expr` |
| coverage gate (85 %) | `make coverage` |
| mutation tests | `make mutation` |
| dependency audit | `make audit` |
| build sdist and wheel, `twine check` | `make build` |
| unit tests on every supported Python (Docker) | `make matrix` |
| run an example against the real API | `make example NAME=search_market` |
| read-only live smoke test | `make live-smoke` |

`make live-smoke` calls the real partner API with read-only queries only and needs `WHITEMARKET_PARTNER_TOKEN` in the
environment; it writes a report without any credential. Never paste the token into a command line, a test or
an example.

## Regenerating the generated code

The generated layer follows the partner schema; nothing under `src/whitemarket/_generated/`, `src/whitemarket/_sync/`,
`schema/`, `graphql/operations/` or `graphql/fragments/` is edited by hand.

```bash
make schema          # fetch the partner schema by introspection -> schema/ (and schema/CHANGES.md)
make codegen         # operations + fragments, ariadne-codegen -> _generated, tools/unasync.py -> _sync
make codegen-check   # regenerate into var/codegen-check and fail on any difference
```

`make codegen` runs `ariadne-codegen` in its own venv (`.venv-codegen`, created on first use) and then
`tools/unasync.py`, which turns the async client and `src/whitemarket/_async/` into the sync twin `_sync/`. After editing
anything in `_async/` run `make codegen` so `_sync/` follows. A hand-written selection that must differ from the generated
one goes to `graphql/overrides/`.

## Schema-sync pull requests

The `schema-sync.yml` workflow introspects the partner schema daily. When `schema/` changes it regenerates everything, runs
`make check` and opens (or updates) a PR on the branch `schema-sync/auto` with the label `schema-update`, plus `breaking`
when the diff holds breaking changes; a failing `make check` makes it a draft. The PR never goes to `main` by itself. The
reviewer reads `schema/CHANGES.md`, maps each change to the generated operations and the high-level methods, updates the
hand-written models, mappers, tests and README where needed, decides the SemVer bump (a breaking schema change is a minor
bump while `0.x`) and merges only when `make check` is green.

## Readiness chain

For a change to source files the order is mandatory:

1. implementation, with tests (a bug fix starts with a failing test);
2. clean code review (a new public type, more than 100 added lines of hand-written Python, or anything touching auth,
   money, buying, retry policy or the live protocol);
3. `make check` green;
4. a security check for changes in auth, transport, token storage, live connections, export downloading or CI workflows
   (and a review of the whole branch before a pull request);
5. only then call the work done.

## Rules

- `src/whitemarket/_generated/`, `schema/`, `graphql/operations/`, `graphql/fragments/` are generated: never edit them by
  hand. Regenerate with `make schema` / `make codegen`; `make codegen-check` must stay clean. Hand-written selection
  overrides go to `graphql/overrides/`.
- `src/whitemarket/_sync/` is generated from `src/whitemarket/_async/` by `tools/unasync.py`: change the async code and
  regenerate.
- New behaviour and every bug fix come with tests. A bug fix starts with a failing test. Examples under `examples/` are
  type-checked and compiled by `tests/unit/examples`; a new example needs an entry there.
- A change of the public API is a SemVer matter: an entry in `CHANGELOG.md` (under "Breaking" with `before -> after` when
  it breaks). A deviation from `docs/SDK_SPEC.md` is recorded in `docs/DEVIATIONS.md`.
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
