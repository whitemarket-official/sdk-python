# pytest and coverage configuration

Configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.coverage.*]`). The Makefile targets (`make test`, `make coverage`, `make mutation`) are the only way the agent runs them. Keys below are recalled for pytest 8.x / coverage 7.x; check the pinned versions' docs before adding a key (https://docs.pytest.org/en/stable/reference/reference.html#ini-options-ref , https://coverage.readthedocs.io/en/latest/config.html).

## Strictness worth keeping

```toml
[tool.pytest.ini_options]
addopts = ["--strict-markers", "--strict-config", "-ra"]
xfail_strict = true
filterwarnings = ["error"]
testpaths = ["tests"]
markers = [
    "live: talks to the real API; needs WHITEMARKET_PARTNER_TOKEN, read-only",
]
```

- `--strict-markers`: a typo in a marker name is an error, not a silently unmarked test.
- `--strict-config`: unknown config keys are errors (catches keys copied from another plugin version).
- `xfail_strict = true`: an xfail that starts passing fails the run, so a fixed bug cannot hide.
- `filterwarnings = ["error"]`: warnings (including our own `DeprecationWarning`) fail tests unless a test expects them. A specific `ignore:` entry for a third-party warning needs a reason and an issue reference (suppression rule 15).
- pytest-asyncio mode (`asyncio_mode`) is set once here; see `async-and-sync.md`.

## Coverage

```toml
[tool.coverage.run]
branch = true
source = ["whitemarket"]
omit = ["src/whitemarket/_generated/*"]

[tool.coverage.report]
fail_under = 85
show_missing = true
```

- The 85 % gate is enforced by `make coverage`. Generated code is excluded by design; nothing hand-written is added to `omit` to pass the gate (the `suppress-check` hook flags it).
- `exclude_lines` / `exclude_also` additions and `# pragma: no cover` need a reason and an issue reference; `if TYPE_CHECKING:` blocks are the usual legitimate case.

## Mutation testing (mutmut)

- Run on demand via `make mutation`. Surviving mutants in retry, reconciliation, validation and mapping code are findings: add the missing case to the parametrized matrix.
- `# pragma: no mutate` is a suppression (code-less, so a reason and an issue reference are mandatory).
