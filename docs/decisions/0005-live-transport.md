# 0005. Live updates: WebSocket client, SSE, sync exposure

- Status: accepted for the 0.1.0 work; two points are open questions for the owner (below)
- Date: 2026-11-13

## Context

SDK_SPEC 3.11: live updates over `WS | SSE` with reconnect forever, full-jitter backoff (0.5 s base, 20 s cap),
a 5-consecutive rule for close codes outside the Centrifugo ranges, a token refresh from the connect reply `ttl`,
`109` / `3500` / SSE `401` as one refresh plus one reconnect, an idle deadline of `ping + 10 s`, handler exceptions
that propagate out of `poll()`, and a fresh token before every connect. The server is Centrifugo 6.7.2 OSS with the
JSON protocol (WHITEMARKET_API.md 9). The spec says: official Centrifugo client where one exists
(`centrifuge-python`), otherwise a minimal own implementation over a WebSocket library. CLAUDE.md rule 10: a new
runtime dependency needs an ADR, and using a transitive dependency directly is forbidden. Rule 14: protocol and
library behaviour is verified at the pinned version; the library facts below are `[code]` for
`centrifuge-python` 0.7.0 (`.venv/lib/python3.13/site-packages/centrifuge/`), the protocol facts are `[docs]`.

## Centrifugo protocol facts used

- A frame holds one or more JSON messages joined with `\n`; a failed command replies `{"id":N,"error":{code,message,
  temporary}}`; a message without `id` is a push. [docs https://centrifugal.dev/docs/transports/client_protocol]
- The server ping is an empty message; the client answers with an empty message when the connect reply negotiated
  it (`pong: true`); the client arms a timer of ping interval plus slack, reset by any frame, and reconnects when it
  fires. [docs, same page; the 10 s slack is the centrifuge-js default, WHITEMARKET_API.md 9]
- The unidirectional SSE transport takes the connect command in the `cf_connect` query parameter (JSON, URL-encoded),
  sends one `data: {json}` frame per message, `data: {}` as a ping, and the connect reply first. Token expiry and
  disconnect signalling are not described on the page. [docs https://centrifugal.dev/docs/transports/uni_sse]
- Close and disconnect codes 3000-3499 / 4000-4499 reconnect, 3500-3999 / 4500-4999 are terminal; error `105` already
  subscribed, `109` token expired. [docs https://centrifugal.dev/docs/transports/client_api,
  https://centrifugal.dev/docs/server/codes; summarised with sources in WHITEMARKET_API.md 9]
- The server subscribes `broadcast` and `#<personId>` on connect (connect reply `subs`): [observed 2026-11-01 and
  2026-11-02, WHITEMARKET_API.md 9].

## What `centrifuge-python` 0.7.0 does, and where it conflicts with SDK_SPEC 3.11

| Topic | Library behaviour [code] | SDK_SPEC 3.11 | Verdict |
|---|---|---|---|
| Server ping, pong | `_handle_ping` answers `{}` when the connect reply has `pong` (`client.py:2113-2118`); the connect reply is applied in `_connected` (`client.py:814-858`) | answer `{}` when `pong: true` | matches |
| Idle deadline | `_restart_ping_wait`: `ping + max_server_ping_delay`, default 10.0 (`client.py:312`, `2104-2111`); no timer when the reply has no ping; no clamp to 300 s | `ping + 10 s`, ping clamped to 300 s, default 25 s | matches, except the clamp and the default (documented deviation) |
| Several messages per frame | `_JsonCodec.decode_replies` splits on `\n` (`codecs.py:20-22`) | split on `\n` | matches |
| Reconnect backoff | `utils._backoff`: `min(max, min + uniform(0, min(max, min * 2**step)))`, defaults 0.1 / 20 s (`utils.py:10-17`, `client.py:316-317`); the module-level `random` and the event loop clock are not injectable | full jitter `random * min(20, 0.5 * 2**(n-1))`, deterministic tests | does not match: other formula (adds the base), no injection |
| Attempt counter | reset on the connect reply (`_clear_connecting_state`, `client.py:1020`, called from `_connected`) | reset only after 60 s connected | does not match |
| Attempt cap | none, reconnects forever | optional `max_reconnect_attempts` | does not match |
| Close codes | `_listen` (`client.py:2325-2371`): a WebSocket close code below 3000 becomes the client code `1` "transport closed" (1009 aside), codes from 3000 are kept; 3500-3999 / 4500-4999 do not reconnect (`client.py:2205`, `2368`) | same ranges; codes outside them reconnect at most 5 in a row, and the report names the code | ranges match; the original code below 3000 is lost; the 5-rule is missing |
| Token for a reconnect | `get_token` is called only after an `109` (`_refresh_required`, `client.py:793-798`) or when there is no token (`client.py:690-700`); the same token is reused otherwise | a fresh token before every connect | does not match |
| Token expiry | with `get_token`: sends a `refresh` command at `ttl` seconds on the same connection (`_refresh`, `client.py:1104-1190`); `ConnectedContext` has no `ttl` (`contexts.py:18-20`) | `ttl` < 10 min: refresh the JWT and reconnect; one refresh per streak; `3500` and `109`: one refresh + reconnect, the second in a row terminal | does not match, and `ttl` is not exposed |
| `3500` | terminal disconnect (`client.py:2205`) | one refresh + reconnect | does not match |
| Handler exceptions | an exception in an event handler disconnects the client without reconnect (`_handler_failed`, `client.py:661-672`, `2308-2323`) | propagates out of `poll()`, connection stays open | does not match unless handlers never raise inside the library |
| Debug logging | `logger.debug("send commands: %s", ...)` (`client.py:2134`) and `logger.debug("data received %s", ...)` (`client.py:2339`) print the connect token and every message (deal events with Steam ids); `websockets` logs frames at DEBUG too | tokens never logged; Steam ids never logged | needs a filter |
| `105` on subscribe | a non-temporary subscribe error unsubscribes with that code (`client.py:1535-1550`, `_move_unsubscribed`) | `105` is success | handled in our handler |
| Server-side subscriptions | pushes arrive in `ClientEventHandler.on_publication` with `ServerPublicationContext` | personal channel never subscribed | usable |
| Python | `>=3.10`, depends on `websockets>=15,<18` and `protobuf>=5.29.6,<8` | 3.11-3.15 | fine |

## Options

1. Use `centrifuge-python` as the owner of the connection, with its own reconnect. Cannot meet the spec: six rows above
   do not match and cannot be configured away.
2. Own minimal Centrifugo JSON protocol over `websockets` (what the PHP SDK does over phrity). Meets every row exactly
   and is deterministic to test. Needs `websockets` as a direct runtime dependency (rule 10: declaring it explicitly is
   the owner's decision, so it is a stop point and not taken here), and re-implements connect, subscribe, ping, push.
3. Use `centrifuge-python` as the transport and codec of ONE connection attempt: a fresh `Client` per `open()`, its
   reconnect cancelled on the first loss (`disconnect()` from the event handler is supported, `client.py:1096-1102`,
   `_transition`), no `get_token`. Every reconnect decision (backoff, counters, close codes, token refresh, `Retry-After`)
   is made by the SDK's own session engine, which is shared with SSE. Within the allowed dependencies.

## Decision

Option 3. `src/whitemarket/live/_ws.py` wraps the library; `src/whitemarket/live/_engine.py` is the port of the PHP
`LiveSession` (one engine for both transports, injected clock / sleeper / random, pull-driven so a handler exception
propagates out of the dispatching call). `centrifuge-python` stays in the `live` extra (`>=0.7`; the code relies on the
private `Client._background_tasks` only to wait for the library's own tasks on close, guarded with `getattr`).

What the library still owns on a connection: the connect command, ping/pong, the idle deadline (`ping + 10 s`), frame
splitting, subscribe and its own resubscribe for pushes `>= 2500`. What the SDK changes or adds:

- The ttl rule: the library does not expose the connect reply `ttl`, so the SDK computes it from the `exp` claim of the
  JWT it sent (`_runtime/jwt.seconds_left`); the server derives `ttl` from the same claim. Recorded as a deviation.
- The library collapses every WebSocket close below 3000 to its own code `1`; the SDK reports it as a close outside the
  Centrifugo ranges (code `1`, counted by the 5-in-a-row rule). A connect-phase code `1` is a failed attempt, uncounted.
- Library debug logging is dropped by a `logging.Filter` on `centrifuge` and `websockets.client` (global, installed on the
  first WebSocket connect); the `httpx` request record of the SSE GET is redacted (`cf_connect` value replaced).
- Handlers never run inside the library: its callbacks put protocol items into a bounded queue (4096; a full queue
  stops the library reading, i.e. TCP backpressure), the session reads them in `poll()`.
- Personal channels (leading `#`) are never subscribed.

SSE: own parser (`sse_parser.py`) over `httpx` streaming with `aiter_bytes()` (not `aiter_lines()`: its line splitting is
`str.splitlines`-like and treats U+2028 / U+0085 as line ends, which SSE does not, and it has no size cap), a per-event
and per-line size cap, no redirects, `Accept-Encoding: identity`, the SDK's own `httpx.AsyncClient` per connection.

Sync client: the connection code is asyncio-only (the Centrifugo client has no sync flavour), so it cannot be derived
by `tools/unasync.py`. `LiveSession` (what `WhiteMarketClient.live()` returns) runs the same engine on a private event
loop in a daemon thread named `whitemarket-live`, with blocking `connect()`, `poll(timeout)`, `run()`, iteration,
`wait_for_deal_event()` and `close()`. Handlers and lifecycle callbacks run on the CALLER's thread inside the call that
returned the event (the engine reports into a queue the caller drains), so a handler exception propagates to the caller.
`close()` may be called from any thread and joins the thread. The sync token provider is called with
`asyncio.to_thread`. `client.live()` itself is ordinary async source in `_async/client.py`; unasync turns
`AsyncLiveSession` / `whitemarket.live.async_session` into `LiveSession` / `whitemarket.live.session`, whose `create()`
has the same keywords. Rejected: async-only live (the spec asks for `poll(timeout)` in synchronous languages).

`deals.wait_for(..., live=session)` (P3) uses `session.wait_for_deal_event(deal_id, timeout)` on both sessions: it
returns the next `DealEvent` of that deal id or `None` at the deadline, dispatches other events to the handlers on the
way, and consumes the session like `poll()` (a second concurrent consumer raises `RuntimeError`). The event is a hint;
the caller then reads the GraphQL state.

## Open questions for the owner (defaults used)

1. Declare `websockets` as a direct dependency and replace `centrifuge-python` by an own protocol implementation
   (option 2)? It would give the exact `ttl` and ping from the connect reply, the real close code below 3000, the ping
   clamp, a deterministic idle timer and one dependency fewer (no `protobuf`). Default: no, option 3 stays.
2. Pin `centrifuge-python` to `>=0.7,<0.8`? The code reads one private attribute and relies on the event semantics of
   0.7.0 (a failed first attempt reports only `on_error`, a lost connection reports `on_connecting`). Default: leave
   `>=0.7` until a release breaks it; the live tests (fake server) fail on a semantic change.

## Consequences

- Deviations recorded in DEVIATIONS.md: ttl from the JWT, collapsed close codes, no ping clamp / default on WS, global
  logging filters, sync live through a thread, SSE via `aiter_bytes`.
- The live tests run a fake Centrifugo server with `websockets` (test extra, exact pin).
- Memory per live connection is bounded (queue 4096 messages, SSE event cap `max_message_bytes`).

## Sources

- https://centrifugal.dev/docs/transports/client_protocol
- https://centrifugal.dev/docs/transports/uni_sse
- https://centrifugal.dev/docs/transports/client_api, https://centrifugal.dev/docs/server/codes
- https://github.com/centrifugal/centrifuge-python (0.7.0, read from the installed package)
- WHITEMARKET_API.md 9; PHP SDK `src/Live/LiveSession.php`, ADR 0005 of the PHP SDK
