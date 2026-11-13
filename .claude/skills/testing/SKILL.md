---
name: testing
description: >-
  Testing rules for the WhiteMarket Python SDK (pytest + pytest-asyncio + respx). Read BEFORE writing or changing
  tests, and whenever a task involves new functionality or a bug fix (CLAUDE.md rule 0b): test structure, input matrix
  with boundaries, parametrize with spec-like ids, HTTP fakes at the httpx boundary, fixtures, deterministic
  time/random, async and sync clients both covered, mutation-minded checks, debugging test failures.
---

# Testing

**The goal is not a green run but confidence the code is correct.** A test written "to pass" is worse than none: it creates false coverage. Write tests as if you were trying to **break your own code**.

Stack: pytest, pytest-asyncio, respx (httpx mocking), coverage; mutmut for mutation testing. Requirements come from `docs/SDK_SPEC.md` section 7. Library APIs below are recalled for the versions current at the time of writing; before relying on an unusual feature or config key, check the docs of the version pinned in `pyproject.toml` (CLAUDE.md rule 14).

## References

- [`references/parametrize.md`](references/parametrize.md): `pytest.mark.parametrize`, ids, `pytest.param`, fixtures, `pytest.raises`.
- [`references/http-fakes.md`](references/http-fakes.md): respx and `httpx.MockTransport`, recording requests, queued responses, transport errors.
- [`references/async-and-sync.md`](references/async-and-sync.md): pytest-asyncio, testing the async core and the generated sync facade, injected clock/sleeper.
- [`references/configuration.md`](references/configuration.md): pytest / coverage configuration in `pyproject.toml`, strictness flags.

## Rules (each one is mandatory)

**1. A test must fail on broken code.** After it goes green, break the implementation once (`>` -> `>=`, return early, drop a guard, return `None`) and watch it go red; then restore. Does not go red -> the test checks nothing. `make mutation` (mutmut) does this at scale; the manual check is still required for every new test.

**2. Input matrix, not one happy path.** For every unit of logic:
- **Happy path**: a typical valid input.
- **Boundaries**: exactly at the limit and +-1. SDK limits: `deals.statuses` chunking 300/301/600/601 ids; comment 255/256 chars and forbidden characters; lifetime 59/60/31536000/31536001; `set_lifetime_for_all` 599/600; `custom_id` 100/101 chars; retry attempts max/max+1.
- **Equivalence classes**: one representative per class, no ten cases meaning the same.
- **Negative / invalid**: `None`, empty string/list, wrong type (where the public API accepts `object`/untyped input), over the limit, unknown id, malformed JSON, missing field.
- **Server data specials**: unknown enum value / event type (must not raise), money and wear as decimal strings (`"0.07"`, `"0"`, many decimals) mapped to `Decimal` exactly, 64-bit ids beyond 2^53 kept as `str`, `paint_index` string vs number, null floats in exports, Doppler phases sharing a name hash.
- **Transport specials**: every HTTP status of the SDK_SPEC 1.4 / 1.5 tables, `Retry-After` in seconds and as HTTP-date, `httpx.ConnectError` / `httpx.ReadTimeout` before and after the request was sent, 401 -> refresh -> replay, a second 401, gzip body, body over the size limit, cross-host 3xx.
- **Time**: token expiring exactly at the safety margin, JWT without `exp`, clock skew, naive vs aware datetimes.

**3. Parametrize the matrix.** One `@pytest.mark.parametrize` test with readable ids beats ten copy-paste functions. Ids read as a spec: `"301 ids -> two requests"`, `"503 on mutation -> no retry"` (via `pytest.param(..., id=...)` or `ids=`).

**4. Behaviour, not implementation.** Assert observable results: returned models, raised exception class and category, the requests that hit the transport (method, URL, headers, `operationName`, variables). Do not assert private functions or call counts unless the count *is* the behaviour (exactly one `auth_token` call under concurrency, exactly one request for a mutation on 503).

**5. No tautologies.** A double that repeats the implementation, or an assertion on the value the test itself stubbed, is FORBIDDEN (CLAUDE.md rule 0b). `unittest.mock.patch` of our own function followed by an assert that it was called is the typical form. If an honest test cannot be written, stop and tell the user what blocks it.

**6. Red first for every bug.** Write the test that reproduces the bug, see it fail on the current code, then fix. A test that passes on the old code does not catch the regression.

**7. Fixtures over mocks of our own code.** Never mock or patch SDK classes and functions (mappers, transport, token store, paginator). Use the real object with a fake at the **outer boundary**:
- HTTP: respx routes or an `httpx.MockTransport` handler injected into the real `httpx.Client` / `httpx.AsyncClient` the SDK uses. Reuse the project's existing fake helpers (`tests/` conftest / helpers module); do not write a new one per test (CLAUDE.md rule 11).
- Responses: JSON fixtures in `tests/fixtures/`, synthetic or from the public partner docs, scrubbed (CLAUDE.md "Data policy"). No real tokens, ids of real accounts, trade URLs, IPs.
- Token store: the in-memory implementation. Logging: pytest's `caplog` (for redaction tests).
- Live: a local fake SSE / fake Centrifugo WS server, never the real endpoint.

**8. Deterministic time and randomness.** Clock, sleeper, jitter source and UUID generator are injected; tests pass fixed implementations. No `time.sleep` / `asyncio.sleep` with real durations, no `datetime.now()` / `time.time()` / `uuid.uuid4()` inside the SUT without the injected source, no order dependence between tests. Retry tests assert the computed delays through the fake sleeper instead of waiting.

**9. Isolation.** No shared mutable state between tests, no module-level mutable state, no reliance on test order; clients created per test and closed (context manager or fixture with teardown). Environment variables via `monkeypatch.setenv`, never mutated globally.

**10. Both clients.** Every behaviour is exercised through the async core **and** the generated sync facade (`AsyncWhiteMarketClient` / `WhiteMarketClient`): parametrize over both where the shape allows, otherwise a thin sync smoke test per method. A bug in the code generation of `_sync/` is a real bug.

**11. Live tests are opt-in.** Integration tests against the real API run only when `WHITEMARKET_PARTNER_TOKEN` is set (skip otherwise via a marker), are read-only, and never print the token or raw responses.

In doubt: **fewer doubles, more cases.**

## Structure and naming

- Files `tests/**/test_*.py`; test functions `test_<behaviour>`: `test_reconciles_from_deal_history_when_item_not_found`, not `test_buy`.
- Mirror the package: `src/whitemarket/_async/buying.py` -> `tests/unit/test_buying.py`. Live/integration tests in their own directory and marker.
- Arrange-Act-Assert; one act per test; several asserts are fine when they verify one behaviour.
- Plain `assert` with exact values (`assert result == Decimal("0.07")`, never comparing money through `float`). Exceptions: `with pytest.raises(ErrorClass, match=...)` around the act only, then assert attributes (`category`, `retry_after`, `custom_id`) on `excinfo.value`.
- Fixtures in `conftest.py` only when shared by several modules; otherwise local to the module.
- Generated code (`src/whitemarket/_generated/`) is not unit-tested directly; a codegen smoke test executes a few operations through the HTTP fake (SDK_SPEC P1).

```python
import httpx
import pytest
import respx

from tests.helpers import deal_statuses_response, sequential_ids


@pytest.mark.parametrize(
    ("ids", "expected_requests"),
    [
        pytest.param(300, 1, id="300 ids -> one request"),
        pytest.param(301, 2, id="301 ids -> two requests"),
        pytest.param(600, 2, id="600 ids -> two requests"),
        pytest.param(601, 3, id="601 ids -> three requests"),
    ],
)
async def test_statuses_split_ids_into_batches_of_300(
    respx_mock: respx.MockRouter, async_client, ids: int, expected_requests: int
) -> None:
    route = respx_mock.post(GRAPHQL_URL).mock(side_effect=deal_statuses_response)

    await async_client.deals.statuses(sequential_ids(ids))

    assert route.call_count == expected_requests
```

(Names like `async_client`, `GRAPHQL_URL`, `tests.helpers` are illustrative; use the project's real fixtures.)

## Running

```bash
make test K=<expr>      # fast loop: pytest -k <expr>
make coverage           # full suite + 85 % gate (part of quality-checks)
make mutation           # mutmut, on demand
```

Large output goes through `qc-runner`; logs in `var/qc/<target>.log`.

## Reviewing tests

Cite the issue and the fix inline, do not lecture: `patch("whitemarket._async.mapper.map_deal") -> use the real mapper with a fixture`, `float(price) == 0.07 -> price == Decimal("0.07")`.
