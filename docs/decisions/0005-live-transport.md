# 0005. Live updates: own Centrifugo client over websockets, SSE, sync exposure

- Status: accepted (owner decision 2026-11-14: replaces the first 0.1.0 decision, which wrapped `centrifuge-python`)
- Date: 2026-11-14

## Context

SDK_SPEC 3.11: live updates over `WS | SSE` with reconnect forever, full-jitter backoff (0.5 s base, 20 s cap),
a 5-consecutive rule for close codes outside the Centrifugo ranges, a token refresh from the connect reply `ttl`,
`109` / `3500` / SSE `401` as one refresh plus one reconnect, an idle deadline of `ping + 10 s` (ping clamped to 300 s,
25 s default), handler exceptions that propagate out of `poll()`, a fresh token before every connect, and a
bounded message size. The server is Centrifugo 6.7.2 OSS with the JSON protocol (WHITEMARKET_API.md 9).

The spec prefers the official client where one exists (`centrifuge-python`). The first implementation used it as the
transport of one connection attempt (reconnect switched off). That needed workarounds for what the library hides
or fixes: it exposes no connect reply `ttl` (the SDK read the JWT `exp` instead), collapses every WebSocket close below
3000 to its own code `1`, has no ping clamp, logs the connect token and every message at DEBUG (global logging
filters), passes `max_size=None` to `websockets` (no size bound), reads into an unbounded internal queue, turns a
`105` subscribe reply into an unsubscribe, and needed a private attribute to wait for its tasks on close. The owner
decided to drop the library, as the PHP SDK did over its WebSocket library.

## Decision

An own minimal Centrifugo JSON-protocol client over `websockets` (direct dependency of the `live` extra,
`websockets>=17`, the current major; the test extra pins `websockets==17.4`, which is also what `uv.lock` resolves).
`centrifuge-python` and its `protobuf` dependency are removed. CLAUDE.md rule 10: `websockets` is declared explicitly,
because the code imports it.

`src/whitemarket/live/_ws.py` (`WsConnection`) is the whole client. `_engine.py` (backoff, close-code rules, refresh
streaks, idle deadline, error replies, resubscribing) is shared with SSE and is unchanged.

### Protocol facts used [docs https://centrifugal.dev/docs/transports/client_protocol, read 2026-11-14]

- Connect command `{"id":1,"connect":{"token":"<JWT>","name":"..."}}`; the reply carries `client` and negotiates the
  heartbeat. The page does not list `ttl`, `expires`, `subs` or `version`: those come from WHITEMARKET_API.md 9
  (client.proto, centrifuge-js source; the fake server of the tests follows the same shape; real server [observed]).
- The server ping is an empty message; the client answers with an empty message if the handshake negotiated it
  (`pong: true`); the client arms a timer of ping interval plus slack, reset by any incoming message. The 10 s slack is
  the centrifuge-js default (WHITEMARKET_API.md 9, `[docs]` centrifuge-js `maxServerPingDelay`).
- Subscribe `{"id":2,"subscribe":{"channel":"..."}}`; subscribing twice returns error `105` (already subscribed).
- A push has no `id` (`pub`, `join`, `leave`, `subscribe`, `unsubscribe`, `message`, `disconnect`, ...); a failed command
  replies `{"id":1,"error":{"code":..,"message":..,"temporary":bool}}`.
- In JSON, several messages in one frame are joined with `\n`.
- Close and disconnect code ranges, error codes `105` / `109`, unsubscribe codes `>= 2500`: https://centrifugal.dev/docs/transports/client_api
  and https://centrifugal.dev/docs/server/codes, summarised with sources in WHITEMARKET_API.md 9. The protocol page
  does not give them.

### `websockets` 17.4 facts used

- `connect(uri, user_agent_header=, max_size=, compression=, ping_interval=, open_timeout=, close_timeout=, proxy=,
  logger=)` of `websockets.asyncio.client`; `max_size` defaults to 1 MiB, `None` disables it; `recv()` is cancel-safe
  [docs https://websockets.readthedocs.io/en/17.4/reference/asyncio/client.html]. `ping_interval=None` (Centrifugo pings
  at the protocol level) and `compression=None` (nothing negotiated; a smaller attack surface, `max_size` counts the
  decompressed size anyway).
- A message over `max_size` fails the connection with close code 1009 on our side; the exception carries the close
  frames (`rcvd`, `sent`); `close_code` is the received code or 1006 when none came [code `websockets/protocol.py:184-200`;
  the 1009 and 1006 results are pinned by tests against a loopback server].
- Frames are logged at DEBUG (`> TEXT '...'`, `< TEXT '...'`), and whether to do so is decided when the connection is
  created from `logger.isEnabledFor(DEBUG)` [code `websockets/protocol.py:108`, `610-611`, `756-757`;
  docs https://websockets.readthedocs.io/en/17.4/topics/logging.html: `logger=` replaces the default logger and does not
  change what is logged]. The SDK passes its own unregistered logger `whitemarket.live.websockets` whose `isEnabledFor(DEBUG)` is always False (a pinned level is reset by a later `dictConfig` naming a parent), so frame logging
  cannot be switched on by application logging configuration, and no filter on a global logger is installed.

### What `WsConnection` does

- `open()`: handshake (`wss` from the https base; the Python API cannot configure `ws`), connect command with token, `name`
  (`whitemarket-sdk-python`) and `version`; the connect reply gives `ConnectInfo.from_reply(ping, pong, ttl, expires)`
  (ping clamped to 300 s, 25 s default, real `ttl`), then one subscribe command per non-personal channel. The whole open is
  bounded by `connect_timeout`.
- A reader task per socket splits frames on `\n`, decodes with `decode_message`, answers the server ping with `{}` when
  `pong` is true (also while the consumer is slow: a missing pong closes the connection), and puts messages into a
  bounded queue (`min(4096, 64 MiB / max_message_bytes)`, shared with SSE). `put` never waits; on overflow the socket is
  closed (1008) and `read()` raises `SlowConsumerError` (the session reconnects and tells the user to resync).
- `read()` hands the engine pings, replies (errors included: `109` refreshes, `105` is success, others reach `on_error`),
  publications, disconnect pushes and unsubscribes. A line that is not valid or has a malformed known message raises
  `DecodeError` from `read()`: the engine reports it to `on_error` and the stream continues; unknown kinds are
  `OtherMessage`. The idle deadline is the engine's (`ConnectInfo.idle_seconds`, reset by every message).
- A WebSocket close ends `read()` with `ServerClosedError(real code, printable ASCII reason <= 128 bytes)`; a lost link is
  1006, an oversized frame 1009. While connecting, a close below 3000 is a failed attempt (not counted), from 3000 it is a
  close the engine handles (3500 refresh rule). A disconnect push is passed the same way.
- `max_size` is `LiveOptions.max_message_bytes`, the same option as SSE. It bounds a WebSocket frame, which can hold several
  messages, so it is at least as strict as for one message.
- Secrets: the connect command is built in one call and handed to `send`; a failed send is reduced to a flag, so no
  exception or frame local of ours keeps the token; handshake errors are built and raised outside any `except` block.
- Personal channels (leading `#`) are never subscribed (server-side subscription).
- `close()` cancels the reader, wakes a blocked `read()` with a local end marker, and closes the socket; no task outlives it.

SSE: own parser (`_sse_parser.py`) over `httpx` streaming with `aiter_bytes()` (not `aiter_lines()`: its line splitting is
`str.splitlines`-like and treats U+2028 / U+0085 as line ends, which SSE does not, and it has no size cap), a per-event and
per-line size cap, no redirects, `Accept-Encoding: identity`, the SDK's own `httpx.AsyncClient` per connection. The
`httpx` request log record (the URL holds `cf_connect`) is redacted by a filter.

Sync client: the connection code is asyncio-only and the engine is shared with SSE, so it is not derived by
`tools/unasync.py`. `LiveSession` (what `WhiteMarketClient.live()` returns) runs the same engine on a private event loop in
a daemon thread named `whitemarket-live`, with blocking `connect()`, `poll(timeout)`, `run()`, iteration,
`wait_for_deal_event()` and `close()`. Handlers and lifecycle callbacks run on the CALLER's thread inside the call that
returned the event (the engine reports into a queue the caller drains), so a handler exception propagates to the caller.
`close()` may be called from any thread and joins the thread. The sync token provider is called with `asyncio.to_thread`.
`client.live()` itself is ordinary async source in `_async/client.py`; unasync turns `AsyncLiveSession` /
`whitemarket.live.async_session` into `LiveSession` / `whitemarket.live.session`. Rejected: async-only live (the spec asks
for `poll(timeout)` in synchronous languages).

`deals.wait_for(..., live=session)` uses `session.wait_for_deal_event(deal_id, timeout)` on both sessions: it returns the next
`DealEvent` of that deal id or `None` at the deadline, dispatches other events to the handlers on the way, and consumes the
session like `poll()` (a second concurrent consumer raises `RuntimeError`). The event is a hint; the caller then reads the
GraphQL state.

## Options considered

1. `centrifuge-python` as the owner of the connection (its own reconnect): cannot meet the spec (backoff formula, counters,
   token for reconnect, `3500`, handler exceptions).
2. `centrifuge-python` as the transport of one attempt (the first 0.1.0 decision): met the rules only with the workarounds
   listed in Context, and left the frame size unbounded.
3. Own client over `websockets` (chosen): every row of SDK_SPEC 3.11 is met exactly; deterministic to test; one dependency
   fewer in the lock (`protobuf` is gone). Costs about 250 lines of protocol code that we maintain; the protocol is small
   and stable (connect, subscribe, ping, push).

## Consequences

- `pyproject.toml`: `live = ["websockets>=17"]`; no `centrifuge-python`, no `protobuf` in `uv.lock` / `requirements-*.txt`; the
  mypy / pyright overrides for the untyped library are removed (`websockets` ships `py.typed`).
- DEVIATIONS.md rows that existed only for the library are removed (ttl from the JWT, close code 1, ping clamp, `105`,
  message size). Kept: logging of the `httpx` SSE URL, sync live through a thread, SSE via `aiter_bytes`, slow consumer.
- A new major of `websockets` is a deliberate bump (the `>=17` bound has no cap; the fake-server tests and the loopback tests of
  1009 / 1006 fail on a semantic change).
- SDK_SPEC 3.11 still names `centrifuge-python` as the preferred Python client; the spec is shared by all SDKs, so a wording
  change is proposed there separately (CLAUDE.md rule 18).

## Sources

- https://centrifugal.dev/docs/transports/client_protocol (read 2026-11-14)
- https://centrifugal.dev/docs/transports/client_api, https://centrifugal.dev/docs/server/codes
- https://centrifugal.dev/docs/transports/uni_sse
- https://websockets.readthedocs.io/en/17.4/reference/asyncio/client.html, https://websockets.readthedocs.io/en/17.4/topics/logging.html
- websockets 17.4 source (`protocol.py`), installed in `.venv`
- WHITEMARKET_API.md 9; PHP SDK `src/Live/WebSocket/WebSocketConnection.php`, `src/Live/Protocol/`
