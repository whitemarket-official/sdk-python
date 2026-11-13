# Untrusted data checklist

Server responses, live messages (SSE/WS) and export rows are untrusted input (SDK_SPEC 8, CLAUDE.md rule 13).

### [review] UNTRUSTED-1: parsed and validated, never executed - blocker

No `eval`, `exec`, `pickle`/`marshal`/`shelve` loads, `yaml.load` without `SafeLoader`, `importlib.import_module` / `getattr(module, name)` with a name taken from data, or `subprocess` with data in the command. Event type strings map through a fixed table (`dict` / `match`), unknown ones to the unknown variant.
```bash
git diff HEAD -- src | grep -nE '^\+.*\b(eval|exec|pickle\.loads?|marshal\.loads?|yaml\.load|import_module|__import__|subprocess|os\.system)\b'
```

### [review] UNTRUSTED-2: no URLs to other hosts from data - blocker

Data never decides the host the SDK connects to. Export URLs, SSE/WS endpoints and the GraphQL endpoint come from configuration; a value from a message or export row is never used to build a request URL (SSRF-like redirect of credentials).

### [review] UNKNOWN-1: unknown is not an error - blocker

New enum values, new event types, new fields deserialize into an unknown/raw variant and never raise (CLAUDE.md rule 5). Pydantic models of server data do not use `extra="forbid"`; strict enum fields have an unknown fallback. A test feeds an unknown value.

### [review] LIMIT-1: size and decompression limits - blocker

GraphQL response body capped (default 32 MiB, SDK_SPEC 1.3) while streaming, not after `response.read()`. Non-streaming export calls cap the decompressed size (configurable); streaming parsers (`ijson`, `csv` over a text wrapper) do not buffer the whole file. Live frames: a single message size is bounded; a malformed frame closes or skips, never grows memory unbounded.

### [review] LIMIT-2: no unbounded loops driven by the server - warning

Pagination stops on `hasNextPage = false` and also on a repeated or empty cursor; reconnect uses backoff with a cap and jitter; a server cannot make the client spin or spawn unbounded tasks.

### [review] PATH-1: file paths - blocker

Any file written (cached exports, `.meta.json`) uses a path from configuration; names from data are never joined into paths (`pathlib` `/` with a data value is the same defect as string concatenation).

### [review] LOG-DATA-1: no personal data logged - warning

Trade URLs, Steam IDs and deal data from responses are not logged at `INFO` level; `DEBUG` logs follow the redaction rules.
