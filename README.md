# WhiteMarket Python SDK

> Status: in development, not released yet. The public API may change until `1.0.0`.

Official Python SDK for the [WhiteMarket](https://white.market) partner API (CS2 skins marketplace).

- distribution `whitemarket-sdk` (PyPI), import package `whitemarket`, `src/` layout, `py.typed`
- Runtime support: every CPython version in bugfix or security status at release time (https://devguide.python.org/versions/)

## What it covers

- **Generated layer**: typed client for every operation of the partner GraphQL schema
  (`https://api.white.market/graphql/partner`), regenerated automatically by a GitHub Actions workflow when the schema changes.
- **High-level client**: authentication with a Partner Token (cached access token, automatic refresh), market search,
  buying with idempotent `customId` and outcome reconciliation, deal tracking, selling, inventory, buy orders, wallet, profile, store.
- **Export files**: streaming access to the public price and product exports on `https://export.white.market` with freshness metadata.
- **Live updates**: Server-Sent Events and WebSocket (Centrifugo) with typed events and automatic reconnect.

## Documentation

- Partner API docs: https://api.white.market/docs_partner/index.html
- SDK specification shared by all WhiteMarket SDKs: [`docs/SDK_SPEC.md`](docs/SDK_SPEC.md)
- API facts used by the SDK: [`docs/WHITEMARKET_API.md`](docs/WHITEMARKET_API.md)

Installation, quickstart and usage sections are added with the first release.

## License

MIT (to be confirmed before the first release).
