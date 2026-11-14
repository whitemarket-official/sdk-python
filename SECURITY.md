# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.x (latest minor) | yes |
| older | no |

## Reporting a vulnerability

Please do **not** open a public issue. Report privately through
[GitHub Security Advisories](https://github.com/whitemarket-official/sdk-python/security/advisories/new) of this repository.

Include the affected version, a description, and steps to reproduce. Never include real Partner Tokens,
access tokens or other credentials in a report.

We acknowledge reports within 5 business days and coordinate a fix and disclosure with the reporter.

## What the SDK does to protect you

- TLS verification is always on; there is no switch to turn it off. Endpoint options accept `https` origins only and refuse
  credentials in a URL.
- Every SDK request is sent with `follow_redirects=False` and `auth=None`, also through an injected HTTP client, so a
  redirect cannot carry a credential or a resent mutation to another host. Only export downloads follow redirects, within
  the same origin.
- Partner Tokens, access tokens, the Steam proxy and token payloads are `Secret` values with a redacting `repr` and
  `str`. Logs never contain the `Authorization` and `X-partner-token` headers, `cf_connect` values or the bodies of
  authentication and token requests; `HttpError.body_excerpt` is redacted.
- Mutations are never retried automatically.
- Responses are size-limited, and downloaded export files are written through a private temporary file.

## What stays your responsibility

- Keep the Partner Token out of source control, logs and error reports; read it from the environment or a secret store.
- Server error messages, `GraphQLError.partial_data` and live event content are raw server data and are not redacted:
  do not pass them to places where a stray credential would matter.
- An injected `http_client` must not resend a request whose connection failed (that could repeat a mutation).
