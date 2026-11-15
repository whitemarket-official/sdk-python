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
- Expiry (changed 2026-11-14, owner decision, SDK_SPEC 3.1; PHP made the same change): lifetime `exp - now` by the
  local clock, capped by `exp - iat` when `iat >= 0` and `exp > iat` (so a host clock behind the issuer does not
  lengthen it; a host clock ahead of the issuer now shortens it), and never longer than 24 h. `exp` and `iat` are
  NumericDates: an integer (not bool), or a fraction or exponent, which the SDK JSON codec reads as a finite `Decimal`
  and which is rounded down; a value outside the 64-bit integer range is clamped to its end (parity with the sister
  SDKs, and `1E+999999999` is never expanded into an integer); an integer longer than 19 digits is clamped while
  parsing, so Python's 4300-digit conversion limit cannot make a payload unreadable. The local clock is rounded up
  to whole seconds, so the expiry is at most 1 s early and never after `exp`. Missing or non-numeric `exp`, or an unreadable payload
  (bad base64 or JSON, parts != 3, `NaN` / `Infinity` literals, JSON nested too deep), gives 24 h. Refresh 5 minutes
  before expiry (`now < expires_at - 5 min` is "valid": at exactly the margin it refreshes), so an `exp` in the past or
  within the margin counts as expired at any later read of the store: such a token serves the request that asked for it
  and the next request exchanges again, instead of a 401 round trip. Before: a past `exp` gave 24 h, `exp - iat` alone
  set the lifetime, a fractional `exp` was unreadable, and every token was kept at least 10 minutes.
- Attempt budget across the replay (changed 2026-11-14, SDK_SPEC 1.4): the first send and the replay share one
  `_runtime.attempts.AttemptBudget`, so a query sends at most `max_attempts` requests plus the exchange; a 401 on the
  last attempt is still replayed once and that replay is not retried; a mutation is sent at most twice. Before, the
  replay started a fresh retry loop (up to 2 x `max_attempts` sends).
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
