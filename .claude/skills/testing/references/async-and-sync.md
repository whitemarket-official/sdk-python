# Async core, sync facade, deterministic time

Business logic is written once in `src/whitemarket/_async/`; `src/whitemarket/_sync/` is generated from it by `tools/unasync.py` (`make codegen`). Tests cover both, because the generation step itself can break behaviour (a lock, a sleep, an iterator protocol).

Recalled for pytest-asyncio 0.2x / 1.x. The config keys and default modes changed between releases; check the docs of the pinned version before changing configuration: https://pytest-asyncio.readthedocs.io/

## pytest-asyncio

- Async tests are `async def test_...`. Whether they need `@pytest.mark.asyncio` depends on `asyncio_mode` in the config (`strict`: marker required; `auto`: every async test and async fixture is handled). Follow the project config; do not mix styles in one module.
- Async fixtures: `@pytest_asyncio.fixture` in strict mode, plain `@pytest.fixture` in auto mode.
- No real waiting: never `await asyncio.sleep(<real seconds>)` in the SUT path of a test; the SDK takes an injected sleeper.
- Concurrency tests (single-flight refresh): start N callers with `asyncio.gather(*(client.wallet.balance() for _ in range(5)))` against a fake that counts `auth_token` calls; assert exactly one.
- Cancellation: `task = asyncio.create_task(...)`, let it reach the send, `task.cancel()`, assert `asyncio.CancelledError` propagates and no reconciliation / retry request was made.

## Covering both clients

Preferred: one parametrized fixture that yields either client plus a small adapter for awaiting:

```python
@pytest.fixture(params=["async", "sync"])
def client_kind(request: pytest.FixtureRequest) -> str:
    return request.param
```

When the shapes differ too much (iterators vs async iterators, context managers), write the full matrix against the async client and a thin smoke test per method for the sync client. Never skip the sync side entirely.

Threading for the sync client: the sync facade's single-flight refresh uses a thread lock; test it with `concurrent.futures.ThreadPoolExecutor` and a fake that counts `auth_token` calls.

## Deterministic time and randomness

- The SDK takes a clock (`now()` returning an aware `datetime`), a sleeper (records requested delays instead of sleeping), a jitter source and a UUID factory as constructor/config parameters. Tests pass fakes:

```python
class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
```

- Retry/backoff tests assert `sleeper.delays == [...]` (with a fixed jitter source), not wall-clock duration.
- Token expiry tests move the fake clock across the safety margin instead of waiting.
- `custom_id` generation tests inject a fixed UUID factory; validation tests use literal 100/101-char strings.

## Live (SSE / WS)

- Fake servers run in-process (an `asyncio` server or an ASGI app bound to `127.0.0.1` with port 0). Tests cover: `message` as string and as object, several messages in one frame, unknown event type, server ping, disconnect -> reconnect -> resubscribe, token refresh before reconnect, `close()` stops all background tasks (assert no pending tasks remain).
- Real endpoints only in opt-in live tests (skipped without `WHITEMARKET_PARTNER_TOKEN`), read-only, token never printed.
