# HTTP fakes: respx and httpx.MockTransport

The HTTP boundary is the only place a double is allowed for request/response behaviour (`../SKILL.md` rule 7). The SDK's own transport, retry, auth and mapping code always runs for real.

Recalled for httpx 0.27/0.28 and respx 0.21/0.22. Check the docs of the pinned versions before relying on anything not listed here: https://www.python-httpx.org/advanced/transports/ , https://lundberg.github.io/respx/

## Option A: respx (route-based)

```python
import httpx
import respx


def test_mutation_is_sent_once_on_503(respx_mock: respx.MockRouter, client) -> None:
    route = respx_mock.post("https://api.example.test/graphql").mock(
        return_value=httpx.Response(503)
    )

    with pytest.raises(ServerError):
        client.selling.remove(product_id="p-1")

    assert route.call_count == 1
```

- `respx_mock` is the pytest fixture shipped with respx; alternatively `@respx.mock` / `with respx.mock(...) as router:`.
- Routes match on method, URL, and optional patterns (`params=`, `json=`, `headers=`); an unmatched request raises, which is what you want: no silent real network.
- `.mock(return_value=httpx.Response(...))` for a fixed answer; `side_effect=[r1, r2, ...]` for a queue (one per call); `side_effect=httpx.ConnectError` (or an exception instance) to simulate a transport error; `side_effect=callable(request) -> Response` for request-dependent answers.
- Recorded calls: `route.calls` / `route.call_count`, `route.calls.last.request` (an `httpx.Request`: `.headers`, `.url`, `json.loads(request.content)` for `operationName` / variables).
- Works for both `httpx.Client` and `httpx.AsyncClient` without changes.

## Option B: `httpx.MockTransport` (handler-based)

```python
def make_transport(responses: list[httpx.Response]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(queue)

    return httpx.MockTransport(handler), seen
```

- Inject via the SDK's option for a custom `httpx.Client` / `httpx.AsyncClient` (`httpx.Client(transport=...)`). A handler may be `async def` for the async client.
- Good for a project-wide fake that queues responses and records requests: write it **once** in the test helpers and reuse it (CLAUDE.md rule 11).
- Raise `httpx.ConnectError("...", request=request)` / `httpx.ReadTimeout(...)` from the handler to simulate transport failures before / after send.

## What to assert

- Request shape: method, URL path, `Content-Type`, auth header present (and redacted in logs), `operationName`, variables.
- **Never** a real token in fixtures: `test-partner-token`, a JWT with a synthetic payload.
- Redirects: return a `302` with a `Location` on another host and assert no second request was made (the SDK does not follow redirects on GraphQL/auth/SSE).
- Size limits: a response body over the cap (streamed) -> the SDK error, not a `MemoryError`.
- Gzip: `httpx.Response(200, content=gzip.compress(body), headers={"Content-Encoding": "gzip"})`.
- `Retry-After`: both `"3"` and an HTTP-date; assert the delay through the injected sleeper.

## Anti-patterns

- `unittest.mock.patch("whitemarket....Transport.send")`: mocks our own code; the retry/auth logic under test is bypassed.
- Asserting on the response the test itself queued (`assert result.raw == fixture`): tautology.
- One new fake class per test module: consolidate into the shared helper.
