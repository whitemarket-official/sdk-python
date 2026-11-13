# 0002. Sync and async from one source, and the HTTP transport

- Status: accepted (implementation 2026-11-13, T2.3-T2.6)
- Date: 2026-11-13
- Follows: [0001](0001-codegen.md) (generated layer, executor seam)

## Context

SDK_SPEC 1.3 and 1.4 fix the transport rules: headers, timeouts, no redirects, body limit, retry table, and
"never" for mutations "includes resends by the HTTP client library". CLAUDE.md language rules: a sync and an async
client with the same method names, no copy-paste of business logic; runtime dependency `httpx`.

## Decisions

### 1. One async source, a generated sync twin

All IO code is hand-written once, as async, under `src/whitemarket/_async/`. `tools/unasync.py` derives
`src/whitemarket/_sync/` (committed, `make codegen-check` fails when stale). The rewrite works on NAME tokens
(`async`/`await` removed, `Async*`/`async_*` prefixes, `aclose`/`aread`/`aiter_*`/`anext`/`aiter`, `_async` module
paths, `_generated.client` -> `_generated.sync_client`), leaves comments and prose alone, and fails when a forbidden
name survives. Primitives that differ (`AsyncLock`/`Lock`, `async_sleep`/`sleep`, `AsyncDeadline`/`Deadline`) live in
`whitemarket/_concurrency.py`; `_async` code never imports `asyncio`. Pure rules with no IO (`RetryPolicy`,
`Retry-After`, body accumulator, JWT expiry, redaction, endpoint validation) sit outside both trees and are shared.
No event loop runs inside the sync client. An async client must stay in one event loop (httpx rule for
`AsyncClient`).

### 2. httpx

`httpx` (>= 0.28, tested with 0.28.1, httpcore 1.0.9, h11 0.16.0) is the only HTTP library: one API for sync and
async, streaming reads, pluggable transports (`MockTransport` in tests). The SDK creates the clients unless one is
injected. Compression: the request asks for `Accept-Encoding: gzip` only and the SDK decodes it itself from
`aiter_raw()`/`iter_raw()` with `zlib.decompressobj(...).decompress(data, max_length)` in 256-byte slices
(`_runtime/body.py`): httpx decompresses a whole network chunk in one step with no output bound, so a gzip bomb would
be inflated before any limit could look at it. The 32 MiB limit (`max_response_bytes`) counts decompressed bytes and is
enforced while streaming; an error body is read up to 1 MiB and cut, never failing the status mapping.

### 3. Redirects

httpx does not follow redirects by default [docs https://www.python-httpx.org/compatibility/;
code `httpx/_client.py:197` `follow_redirects: bool = False`, `:991-995` returns the 3xx response when not
following]. The SDK still sets `follow_redirects=False` on both clients it creates (`_async/transport.py`
`AsyncHttpClients.create`), so a default change cannot silently forward a credential. A 3xx is `HttpError(status)`
and is never retried. Why it matters [observed, tests/unit/transport/test_loopback.py control]: a client with
`follow_redirects=True` carries `X-partner-token` to the other host (httpx strips `Authorization` across origins but
not custom headers). Tests use two real loopback servers; the second receives nothing for query, mutation and
`auth_token`, and the control test shows it would receive `X-partner-token` from a following client. An injected client
is used as is (owner decision): one INFO log notice says the SDK cannot set its timeouts and redirect policy; the caller
must not let it follow redirects. (Open for the owner: sending `follow_redirects=False` per request would harden
injected clients too, at the price of not using them "as is".)

### 4. Mutations are never resent by the library

Question: does httpx/httpcore ever resend a request on its own? Findings for httpx 0.28.1 / httpcore 1.0.9:

- `AsyncConnectionPool.handle_async_request` loops on `ConnectionNotAvailable` and re-queues the request
  (`httpcore/_async/connection_pool.py:239-244`). The only sources of that exception for HTTP/1.1 are raised before
  any request byte is written: `httpcore/_async/http11.py:73-78` (state is not NEW/IDLE, checked under the state lock
  before `_send_request_headers`).
- With HTTP/2 only (`http2=True`; default `False`, `httpx/_client.py:650`): `httpcore/_async/http2.py:350-354` raises it
  when the server's GOAWAY says the stream was not processed (`stream_id > last_stream_id`), and `:102`, `:139` before
  sending. The server states the request was not executed, so a resend is safe; the SDK never enables HTTP/2.
- `retries=` (`httpx/_transports/default.py:147`, default 0; `httpcore/_async/connection.py:110-162`) retries only
  `ConnectError`/`ConnectTimeout` while opening the connection, before the request is sent.
- A dead keep-alive connection is detected before reuse (`httpcore/_async/http11.py:274-286`, `has_expired`) but a
  race remains: the write succeeds and the read fails. That raises a `ReadError`/`RemoteProtocolError`; nothing resends.

[observed, tests/unit/transport/test_loopback.py] with a raw socket server that reads the whole request and then closes
without an answer, or sends a status line only, a mutation is received exactly once; a query is received exactly as
often as the SDK retry policy attempts (3), so the library adds none.

So no resend by httpx is possible in the default configuration. The spec still demands (1.4) a connection that is not
reused unless the library DOCUMENTS that it never resends, and httpcore does not document that. Decision: mutations
follow the spec. The SDK creates a second `httpx.Client` for mutations with
`Limits(max_keepalive_connections=0)` and sends `Connection: close`, so a mutation never rides an idle connection that
the server may have closed (a spurious failure of a request that would never have reached the server) and never shares
a pool with queries. Cost: one TCP + TLS handshake per mutation. Queries keep connection reuse. Tested: a query pair
uses one connection, three mutations use three, and a mutation after a server-closed idle connection succeeds. An
injected client serves both kinds and is trusted not to resend.

### 5. Timeouts

httpx timeouts are per phase and there is no total timeout [docs https://www.python-httpx.org/advanced/timeouts/]:
the read timeout is "the maximum duration to wait for a chunk of data", so a server that sends one byte every few
seconds never trips it. Defaults: connect 10 s, request 30 s (`Timeouts`), set on the clients the SDK creates as
`httpx.Timeout(request, connect=connect)`.

- Async: the whole attempt (send + body read) runs in `asyncio.timeout(request)` (`AsyncDeadline`), a hard bound.
- Sync: a blocking read cannot be interrupted. `Deadline.check()` runs between body chunks; a stall inside one read is
  bounded by the read timeout. One attempt therefore ends within `request` plus one read timeout (DEVIATIONS.md).

Not applied to an injected client. A timeout before the response is a network error (retried for queries); a deadline
or read failure after the status line is a `TransportError` and is not retried.

### 6. Errors, logging, secrets

httpx exceptions hold the request, with its credential headers: they are never chained (`TransportError` and
`DecodeError` are raised after the `except` block; tests check `__context__ is None`), and their text is never used,
only the class name. The `whitemarket` logger gets one DEBUG line per attempt (operation, type, attempt, status,
duration) plus the redacted request headers (allow-list: only known harmless names keep a value) and the URL with
every query value replaced by `***`. No request or response bodies are logged. A logger that raises never changes the
outcome of a request.

### 7. Retry policy

`RetryPolicy` (pure, `whitemarket/retry.py`): queries only, 3 attempts, 429/500/502/503/504 and network errors before
a response, delay `random() * min(cap, 0.5 * 2^(attempt-1))` (full jitter, cap 30 s). `Retry-After` (seconds or one of
the three HTTP-date forms, parsed strictly, GMT only) on 429/503 stops at once with `retry_after` on the error; on any
other status it is ignored. The random source, sleeper and clock are injectable on the internal transport.

## Consequences

- `import whitemarket` imports the generated layer (about 0.5 s).
- Two httpx clients per SDK client (query and mutation); `aclose()`/`close()` closes both when the SDK made them.
- HTTP/2 is not enabled; proxies, TLS close_notify behaviour and other httpcore versions were not checked.

## Sources

- httpx timeouts: https://www.python-httpx.org/advanced/timeouts/ ; redirects: https://www.python-httpx.org/compatibility/
- Installed code (httpx 0.28.1, httpcore 1.0.9): file:line citations above.
- PHP reference: `../whitemarket_sdk_php/docs/decisions/0002-generated-layer-and-transport.md` (libcurl resend, mutation client).
