# 0003. Access token lifecycle: provider, store, 401 replay

- Status: accepted (implementation 2026-11-13, T2.5)
- Date: 2026-11-13
- Port of: `../whitemarket_sdk_php/docs/decisions/0003-auth-token-lifecycle.md`

## Context

SDK_SPEC 1.4 (401: refresh once, replay once, mutations too), 2 (`partner_token`, `access_token`, `token_provider`,
`token_store`), 3.1 (`auth.access_token/refresh/ping`); WHITEMARKET_API 3: `auth_token` is exchanged with
`X-partner-token`, is rate limited, the JWT lives 24 h and its `exp` is read without verifying the signature.

## Decision

- Seam: `AsyncCredentials` (`headers(operation_name)`, `headers_after_rejection(rejected)`) used by
  `AsyncGraphQLExecutor`, which owns "one operation" and replays the same body once after a 401. A second 401 is
  `AuthenticationError`. `AsyncPartnerTokenCredentials` (`X-partner-token`, no `Authorization`, never replays: a 401
  there is a bad Partner Token); `AsyncBearerCredentials` (provider token as `Authorization: Bearer`).
- Public: `TokenProvider` (`access_token()`, `refresh()` -> `Secret`), `TokenStore` (`get() -> StoredToken | None`,
  `set(token, expires_at)`, `clear()`), `InMemoryTokenStore` (default); async twins `Async*` (DEVIATIONS.md). Tokens
  are `Secret` everywhere; the plain text is revealed once, in the header of one attempt.
- Replay (as PHP): after a 401 the credentials ask the provider for its current token (another worker may have
  stored a new one) and refresh only if it is the rejected one; a replay is offered only with a token different from
  the rejected one, so a fixed `access_token` is never replayed. Mutations are replayed too: a 401 means the request
  was rejected before execution; this is the one exception to CLAUDE.md rule 2 (owner confirmed for PHP 2026-10-31).
- Expiry: lifetime `exp - iat` when both are integers (not bool), `iat >= 0` and `exp > iat`, else `exp - now`, counted
  from the local clock (skew cannot shorten it); missing, unreadable (bad base64 or JSON, parts != 3, a float `exp`,
  JSON nested too deep) or non-positive gives 24 h; never longer than 24 h. The payload is decoded with the SDK JSON
  codec (floats become `Decimal`, so a float `exp` is "unreadable"). Refresh 5 minutes before expiry
  (`now < expires_at - 5 min` is "valid": at exactly the margin it refreshes); a token is kept at least 10 minutes so a
  short one is not exchanged on every call.
- A stored or received token that is not an RFC 6750 `b64token` is never sent: a poisoned store entry is cleared and
  exchanged again; a bad server value is a `DecodeError` and is not stored. A partner token must be a valid header value
  (visible ASCII, no leading/trailing whitespace); errors never echo it.
- Single-flight (new relative to PHP, which has one request at a time per process): `AsyncPartnerTokenProvider` holds
  one lock (`asyncio.Lock` / `threading.Lock` through `_concurrency`). `access_token()` checks the cache, takes the lock,
  checks again, exchanges. `refresh()` coalesces overlapping callers with a generation counter. After a 401 the
  credentials call `refresh_rejected(rejected)`: under the lock it exchanges only if the store still holds the rejected
  token, so N requests rejected with the same token cause one `auth_token` (tested with 20 tasks and 20 threads).
- Cross-process: none (a rare second exchange at expiry is accepted, as in PHP); share a `TokenStore`.
- `auth_token` goes through the mutation path: never retried.

## Consequences

A custom `TokenProvider` gets `refresh()` called once per rejected request; it must be safe for concurrent calls.
