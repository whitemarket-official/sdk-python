# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is `0.x`, a minor release (`0.2.0`) may contain breaking changes; they are always listed under
"Breaking".

## [Unreleased]

### Added

- Live updates: `client.live(LiveTransport.WS | SSE, LiveOptions)` returns `LiveSession` (sync, background thread,
  blocking `poll(timeout)`) or `AsyncLiveSession`; typed events (`ProductAdded`, `ProductEdited`, `ProductRemoved`, the
  eight `Deal*` events, `UnknownEvent`), `subscribe_products`, `subscribe_personal`, `on`, lifecycle callbacks,
  `wait_for_deal_event`. WebSocket needs the `live` extra (ADR 0005). `LiveConnectionError` now carries `code` and
  `reason`.
- High-level models (`whitemarket.models`): `Page`, `PageRequest`, `Product`, `ProductHistory`, `InventoryItem`, `Sticker`,
  `Deal`, `DealState`, `BuyResult`, `DealStatus` (with `is_in_progress`, `is_exchanged`, `is_successful`, `is_failed`,
  `is_reversed`, `is_final`, `awaiting_trade_protection`), `DealCancelReason`, `DealAction`, `TransactionReason` and the
  filter enums; `whitemarket.deals.Until` (`offered`, `exchanged_or_completed`, `completed`, `final`).
- `client.market` (sync and async): `search`, `iterate`, `get`, `sticker_suggestions`, `check_trade_url`, and
  `whitemarket.market.ProductFilter` / `ProductSort`.
