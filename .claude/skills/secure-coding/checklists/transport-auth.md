# Transport and auth checklist

Applies to transport, auth, token storage, secret type, logging, errors, retry, buying. Source: SDK_SPEC 1.3, 1.4, 1.5, 3.3, 8. Code paths below are hand-written sources (`src/whitemarket` minus `_generated/` and `_sync/`); `_sync/` follows `_async/` after `make codegen`.

### [code] SECRET-1: no hardcoded credentials - blocker

```bash
git diff HEAD -- . ':!*.md' | grep -inE '(token|secret|password|bearer|api[_-]?key)\s*[:=]\s*["'\''][^"'\'']{12,}'
```
Fixtures use obvious placeholders (`test-partner-token`, a JWT with a synthetic payload). Real-looking value -> FAIL; if committed, it must be rotated, not just deleted.

### [code] SECRET-2: secrets wrapped and redacted - blocker

Every parameter or attribute holding a Partner Token, JWT, Steam token payload or proxy credential is typed as `pydantic.SecretStr` or the SDK's own `Secret` type, never plain `str` past the public boundary.
```bash
grep -rnE '(partner_token|access_token|refresh_token|token|secret|password)\s*:\s*str\b' src/whitemarket --include='*.py' | grep -vE '/_generated/|/_sync/'
```
The secret type's `__repr__`, `__str__`, `__format__` never return the value; it is excluded from `dataclasses` `repr` (`field(repr=False)`) or pydantic serialization; pickling either redacts or is refused. A test asserts the redacted form (`***` / `SecretStr('**********')`) for `repr()`, `str()`, f-string formatting and `model_dump_json()`.

### [review] REDACT-1: logs and errors never carry secrets or bodies - blocker

Headers `Authorization`, `X-partner-token` and `cf_connect` query values are always redacted in debug logs (including `httpx` event hooks the SDK installs); request bodies of `auth_*` and `profile_token_set` are never logged; no request/response bodies logged by default. Exception messages and `args` contain no token and no request body (SDK_SPEC 1.5); exception chaining (`raise ... from exc`) does not drag an `httpx` exception whose message holds a URL with a token. Trace every new `logger.*` call and every `raise ...Error(` in the diff to its inputs. A redaction test (`caplog`) exists for each new log site.

### [code] TLS-1: no TLS-off switch - blocker

```bash
grep -rnE 'verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False|_create_unverified_context|insecure|skip_tls|disable_tls' src/whitemarket --include='*.py'
```
Any option that disables certificate verification in the SDK -> FAIL. The user may inject their own `httpx.Client` / `httpx.AsyncClient`; the SDK itself never offers the switch.

### [review] REDIRECT-1: credentials never follow a redirect - blocker

GraphQL, auth and SSE requests are sent with redirects **not followed** (`httpx` clients the SDK creates keep `follow_redirects=False`; per-request `follow_redirects=True` never appears on these paths). A 3xx is an error, not a hop. Export downloads that do follow redirects carry no credentials at all. A test covers a cross-host 3xx and asserts no second request with `Authorization` / `X-partner-token`.

### [review] TOKEN-STORE-1: token store is safe - warning

Stored access tokens: cache keys are namespaced and do not contain the token; TTL derived from JWT `exp` minus the safety margin; the JWT payload is decoded without trusting it for anything but `exp`. Never persists the Partner Token unless the user explicitly provides that store. File-based stores (if any) write with `0o600` permissions to a path from configuration.

### [review] REFRESH-1: single-flight refresh and one replay - blocker

401 -> refresh once -> replay once (also for mutations). No loop: a second 401 becomes the authentication error. Concurrent callers trigger exactly one `auth_token` call: an `asyncio.Lock` in the async core and a `threading.Lock` in the sync facade (the generated mirror must not silently turn one into a no-op); a test with concurrent callers asserts it for both clients.

### [code] RETRY-1: mutations are never retried - blocker

Inspect every retry path (transport, helpers, pagination, reconciliation) touched by the diff. A mutation is sent once; only 401 replay is allowed. A test asserts exactly one request on 503 for a mutation.
```bash
git diff HEAD -- src | grep -nE '(retry|attempt|backoff|sleep|tenacity|stamina)'
```

### [review] RECON-1: purchase reconciliation exactly as SDK_SPEC 3.3 - blocker

`customId` generated (UUIDv4) when absent and validated (max 100 chars) before sending; `market_buy` sent once; GraphQL error and 400/401/429 raise without reconciliation; only 5xx/timeout/transport error after the request may have been sent triggers `deal_item` then `deal_history_item` lookups by `customId`; nothing found -> `PurchaseOutcomeUnknownError(custom_id)`. Never "buy again". `asyncio.CancelledError` during the send is re-raised, never converted into a reconciliation or a retry.

### [code] MONEY-1: exact decimals, no float - blocker

```bash
git diff HEAD -- src | grep -nE '^\+.*(\bfloat\b|float\(|round\(|parse_float|use_float=True|json\.loads\()'
```
Money and wear values flow as `decimal.Decimal` end to end (JSON parsed with `parse_float=Decimal` or through pydantic `Decimal` fields; `ijson` with `use_float=False`); 64-bit ids as `str`. A test with an id above 2^53 exists where ids are mapped. Every hit of the grep is explained or fixed.

### [review] ERR-1: branching on category, not message - warning

New error handling branches on `extensions.category` / HTTP status, never on `message` text (CLAUDE.md rule 4).

### [code] DEBUG-1: no debug output - blocker

```bash
git diff HEAD -- src | grep -nE '^\+.*\b(print\(|pprint\(|breakpoint\(|pdb\.|logging\.basicConfig)'
```
The library never configures logging handlers and never prints; it logs through `logging.getLogger(__name__)` only.
