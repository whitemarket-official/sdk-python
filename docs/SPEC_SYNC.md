# Spec sync from the PHP reference SDK (2026-11-01)

`docs/SDK_SPEC.md` and `docs/WHITEMARKET_API.md` in this repository were replaced on 2026-11-01 with the current
versions from `../whitemarket_sdk_php/docs/` (the reference implementation), on the owner's request. They are the
contract; this note only lists what changed so this SDK can catch up.

## What changed in SDK_SPEC (owner-approved proposals merged)

Rationale and before/after text for each item: `../whitemarket_sdk_php/docs/plans/2026-10-30-sdk-spec-proposals.md`.

| Proposal | Section | Topic |
|---|---|---|
| P1, P2, P5 | 1.3, 1.2, 1.5 | transport default client, fragment rule, redacted HttpError body excerpt |
| P3 | 0 | supported runtimes (PHP exception) |
| P7 | 1.4 | the HTTP client below the SDK must not resend a mutation |
| P8 | 2 | credential options are exclusive; an injected HTTP client is used as is |
| P9 | 4 | model field sets, unknown enum values, DealStatus extras |
| P10 | 3.3 | buy reconciliation details |
| P11 | 3.4 | deals (`waitFor` and statuses) |
| P12 | 3.5 | selling |
| P13 | 3.6 | inventory |
| P15 | 3.8 | wallet |
| P16, P17 | 3.9 | profile and store |
| P18, P19 | 3.10 | exports (redirects, streaming, products row, CSV) |
| P20, P21 | 3.11 | live: probe facts, reconnect/backoff/token-refresh bounds, close-code ranges (other codes reconnect at most 5 in a row), TLS only, handler exceptions propagate, close reasons as server text |

Not merged: P14 (1.2, interfaces without possible types) is still a proposal.

## What changed in WHITEMARKET_API

Section 9 (live updates): Centrifugo facts with sources, "Live observations" from a read-only probe and an SDK run
(personal channel and `broadcast` are server-side subscriptions; `stickers`/`keychains` arrays; message volume).
Section 8: products export rows with a null `product_category`.

## For this SDK

Compare the code with the new sections and implement the differences (CLAUDE.md rule 18: parity). The PHP SDK
(`../whitemarket_sdk_php/src/`) shows one way to do each rule; idioms differ per language, behaviour must not.
Language-specific deviations go to this repository's own `docs/DEVIATIONS.md`, not into the shared spec.

## Update 2026-11-02: lessons from the PHP implementation (do these)

The owner asked that every implementation nuance learned in the PHP SDK is known to this SDK's agent at once. Each
item: what, why (fact), what to do, PHP reference (paths relative to `../whitemarket_sdk_php/`). Nothing here changes
the shared `docs/SDK_SPEC.md`; language deviations go to this repository's `docs/DEVIATIONS.md`. Do not edit the
sister repositories, and do not edit the shared `.mjs` operation generator.

### Also changed in WHITEMARKET_API (facts a-d, all [observed] by the PHP SDK)

- a. 2026-11-01: `MarketProductHistory.params` (a deal's product item, `InventoryItemInterface` / `CSGOInventoryItem`):
  selecting `updatedAt` returns "Internal error occurred" without `extensions.category` for every archived row (5 of 5;
  control: the same document without the field succeeds). With `updatedAt` removed, selecting `params.order { id }`
  makes the server answer HTTP 500.
- b. 2026-11-02: `market_buy` returns the same `product.params.updatedAt` error (path
  `market_buy.product.params.updatedAt`) and the purchase is rolled back (no deal with the `customId`, the listing
  stays; 2 of 2). After dropping both fields, 4 purchases succeeded.
- c. 2026-11-01: `market_trade_url(link:)` with a Steam profile URL answers an uncategorized "An unknown error
  occurred."; a trade offer URL (`https://steamcommunity.com/tradeoffer/new/?partner=..&token=..`) answers normally.
- d. 2026-11-02: personal live channel: no subscribe command is needed (the server subscribes on connect);
  `DealOffered`, `DealExchanged`, `DealCancelled` arrived for fresh purchases (open question 2 confirmed).

### Checklist

1. **Server field bug (facts a, b): stop selecting `updatedAt` and `order` inside `MarketProductHistory.params`.**
   - Why: without it `market_buy` reports purchase-outcome-unknown and buys nothing; deals history/get fail.
   - Do: copy the 13 hand-written override files from `../whitemarket_sdk_php/graphql/overrides/` into this repo's
     `graphql/overrides/` under the same names (the operation generator is shared, so they apply as is), regenerate
     (`graphql/operations/` changes only through the generator), and make the CHECKSUMS match PHP's again. Add a
     structural test that fails if any generated document selects `updatedAt` or `order` inside
     `MarketProductHistory.params` again (for example after a schema-sync). PHP test:
     `tests/unit/Generated/ProductHistoryParamsSelectionTest.php`.
   - The 13 files:
     - `graphql/overrides/query/deal_history.graphql`
     - `graphql/overrides/query/deal_history_item.graphql`
     - `graphql/overrides/query/deal_item.graphql`
     - `graphql/overrides/query/deal_buyer_list.graphql`
     - `graphql/overrides/query/deal_seller_list.graphql`
     - `graphql/overrides/mutation/market_buy.graphql`
     - `graphql/overrides/mutation/market_new_multiple.graphql`
     - `graphql/overrides/mutation/market_edit_multiple.graphql`
     - `graphql/overrides/mutation/market_remove.graphql`
     - `graphql/overrides/mutation/market_remove_multiple.graphql`
     - `graphql/overrides/mutation/deal_request_cancel.graphql`
     - `graphql/overrides/mutation/deal_cancel_sending_offer.graphql`
     - `graphql/overrides/mutation/deal_steam_offer_sent.graphql`
   - Do not copy the other PHP overrides (`query/inventory_my`, `query/store_my`, `mutation/store_edit`) unless this
     SDK needs them for its own reasons.
2. **Operation generator: `__typename id` at the depth limit (proposal P22, decided B by the owner 2026-11-02;
   SDK_SPEC 1.2).** The shared generator used to select an interface field at the depth limit as `{ id }` without a
   discriminator, and a codegen that decodes interfaces by `__typename` failed on every `market_list` answer.
   - Copy `tools/codegen/generate-operations.mjs` byte for byte from the PHP repo and regenerate.
   - In your hand-written overrides, add `__typename` before `id` in every interface `{ id }` selection (`item`,
     `order`, `params`).
   - Compare `graphql/operations/CHECKSUMS` with PHP's: generated documents must be identical; overrides differ only
     where your overrides differ.
   - Tests: an invariant over every operation document that each interface or union field selects `__typename` (PHP:
     `tests/codegen/AbstractSelectionTest.php`), and a decode test of `market_list` with a known and an unknown
     `__typename` at the depth limit (PHP:
     `tests/unit/Market/MarketApiTest.php::searchDecodesAnInterfaceFieldAtTheDepthLimitByItsTypename`).
   - PHP keeps its language-codegen fallback (an interface selected without `__typename` decodes as one object,
     `GeneratorTest::emitsOneClassForAnInterfaceSelectedWithoutATypename`) only as a safety net; optional for you.
3. **SDK_SPEC 1.1: the generated client is reachable from the main client**, sharing token, retry and error handling
   (PHP: `WhiteMarketClient::$generated`). Test:
   `WhiteMarketClientTest::theGeneratedLayerSharesTheClientsTokenAndTransport` (`tests/unit/`).
4. **Live smoke (SDK_SPEC 6.4).** PHP reference: `tools/live-smoke/**`, `tests/livesmoke/**`,
   `.github/workflows/live-smoke.yml`, `make live-smoke`. Rules:
   - A read-only guard wraps the executor: reject unless the operation type is query AND the document starts with
     `query`.
   - A test that the smoke's query list equals the set of generated query operations.
   - Minimal variables: a random UUID for id lookups (not-found counts as reachable). `market_trade_url` input must be
     a synthetic trade offer URL (fact c), never a profile URL.
   - The report holds only step name, PASS/FAIL, milliseconds, exception class and category; never messages, ids or
     URLs.
   - Token from the environment or the git-ignored dotenv file.
   - Workflow: `schedule` + `workflow_dispatch` only, a `HAS_TOKEN` boolean at job level, the secret only in the run
     step's `env`, actions pinned by commit SHA.
   - PASS rule for categorized GraphQL errors (approved by the owner 2026-11-02): not-found, or a category that does
     not start with auth/internal/server, counts as reachable.
5. **Examples (SDK_SPEC 9).**
   - Money-moving examples need a `--yes` gate and print a dry run first.
   - Print failures with class, HTTP status and each GraphQL error's category, path and server message, with control
     characters replaced (PHP: `examples/Support/failure.php` and an uncaught-exception handler in
     `examples/bootstrap.php`).
   - Deal tracking examples wait without a timeout by default (trades take hours) and poll every 30 s.
   - `iterate_all_listings` is bounded.
   - The `sell_*` examples assume a seller deal's product id equals the listed product id (unconfirmed; say so).
   - Extra example beyond the spec list: `buy_product_by_id` (reads the listing, refuses above a max price, then buys
     by id with a `customId`): `examples/buy_product_by_id.php`.
6. **CI.** Dependabot: add `.github/dependabot.yml` for this ecosystem plus `github-actions`, weekly, grouped
   minor/patch (PHP: `.github/dependabot.yml`). CodeQL: PHP has none (see PHP `docs/DEVIATIONS.md`), but CodeQL
   supports Go, JavaScript/TypeScript, Python, C# and Rust [docs:
   https://codeql.github.com/docs/codeql-overview/supported-languages-and-frameworks/], so THIS SDK should add a CodeQL
   workflow (actions pinned by SHA). CodeQL language for this SDK: Python (language python).
7. **Test infrastructure.** Tests that push multi-MB payloads plus random order exhausted a 128 MB PHP memory limit
   under coverage. Budget memory for such tests in your runner (heap/stack limits, parallelism) and do not rely on the
   default.
8. **DEVIATIONS rows to mirror** in this repository's `docs/DEVIATIONS.md`: (a) `orders` is not shipped while P14 is
   open (the public schema hides every order type); (b) the overrides of item 1 (what was required -> why it did not
   work -> what was done, with facts a and b).
9. **Release notes, "Known limitations"**: mirror the list in `../whitemarket_sdk_php/CHANGELOG.md` `[Unreleased]`
   "Known limitations" (no `orders` module; unknown `extensions.category` catalogue; live prices assumed USD and no
   gap-free resume; `MarketProductResult.index` base and max batch size unconfirmed; products CSV header assumed to
   name the JSON keys; of the 13 operations only 4 were checked live; `sell_*` examples assumption).

10. `waitFor` misses seller deals (proposal P23, now SDK_SPEC 3.4 rule 12). Fact [observed 2026-11-02]: `deal_buyer_statuses([id])` returns no
    row for a deal where the caller is the seller; `deal_item(id)` returns it. To do: when the reference is not in the
    statuses answer, read the deal with `deals.get` and keep using `get` for the rest of the call; not-found of both is
    "not there yet". PHP: `../whitemarket_sdk_php/src/Deals/DealsApi.php` `waitFor()`, `ModelMapper::dealStateOf()`,
    tests `DealsApiTest::waitForReadsASellerDealWithGetWhenTheStatusesDoNotKnowIt` and the three next to it. Examples
    that wait print every status change (`printStatusChanges()` in `../whitemarket_sdk_php/examples/Support/env.php`).
11. Price cap on every buy form (proposal P24, owner decision, now SDK_SPEC 3.3 method table and rule 7): `buyProduct(productId, maxPrice?, opts)` and
    `buyByAssetId(app, assetId, maxPrice?, opts)` send `market_buy` `maxPriceInput` like `buyCheapest`; null sends no
    key. PHP: `../whitemarket_sdk_php/src/Buying/BuyingApi.php` (`maxPriceInput()` helper), tests
    `BuyingApiTest::sendsTheMaxPriceAsAnExactDecimalWhenGiven`, `omitsTheMaxPriceKeyWhenNoneIsGiven`. The server honours the cap
    with `id` [observed 2026-11-02: `market.product.not_found_in_specified_price`, no deal; WHITEMARKET_API.md].

## Update 2026-11-02: schema sync, operation CHECKSUMS changed (do these)

The partner schema sync of 2026-11-02 (PHP PR #2, commit `349b6f3` on `schema-sync/auto`, not merged yet) changed
`graphql/operations/CHECKSUMS` in the PHP reference. Inspector: 0 breaking, 0 dangerous, 77 safe. Nothing in
`docs/SDK_SPEC.md` changed.

1. Schema: new types `CSGOMarketOrder` (implements `MarketOrder`) and `CSGOMarketOrderPublic` (implements
   `MarketOrderPublic`); `icon` / `iconLarge` there take optional `width` / `height`. Take `schema/partner.graphql`
   from `../whitemarket_sdk_php/schema/` once PR #2 is merged.
2. Regenerate the operation documents with the shared generator. New fragments: `CSGOMarketOrder`,
   `CSGOMarketOrderPublic`, `MarketOrderParamValue`. The `order_*` mutations and `order_list` / `order_my*` queries
   now select the order fields instead of a bare `__typename`; the generated return types widen accordingly
   (unknown types still map to the unknown variant, CLAUDE.md rule 5).
3. Copy the five new overrides from `../whitemarket_sdk_php/graphql/overrides/`: `query/market_list.graphql`,
   `query/market_item.graphql`, `query/market_my.graphql`, `mutation/market_new.graphql`,
   `mutation/market_edit.graphql`. Why: without them `item.order` grows to
   `order { ...CSGOMarketOrderPublicFields inventory { id } }` in operations the high-level layer uses; no model reads
   it, and the server has failed `order` selections before (fact a above). With them the five documents are identical
   to the pre-sync ones. PHP pins this with `tests/unit/Generated/HighLevelItemOrderSelectionTest.php` (every
   `order { }` block in those five documents is exactly `__typename`); add the same guard here. PHP DEVIATIONS row:
   "SDK_SPEC 1.2 selection of an inventory item's `order`".
4. Check: this repository's `graphql/operations/CHECKSUMS` must equal the PHP one after steps 2-3.
5. Not checked live: the five overrides only restore the pre-sync documents. `order_list` gained a deep path
   (`node.inventory.{deal,order,product,...}`); PHP reaches it only from the generated client and did not cut it.
6. Open for the spec, nothing to implement yet: the schema now exposes order types, so the "no `orders` module"
   limitation (proposal P14, SDK_SPEC 3.7) is up for review by the owner.
12. Orders unblocked (proposal P14 obsolete, 2026-11-02). The backend added `CSGOMarketOrder` (implements `MarketOrder`)
    and `CSGOMarketOrderPublic` (implements `MarketOrderPublic`); fields in WHITEMARKET_API.md 4 "Orders". Run this
    repo's schema sync / codegen: the `order*` operations now select the order fields through the existing
    inline-fragment rule, no generator change. Two follow-ups from the PHP sync: (a) `market_list`, `market_item`,
    `market_my`, `market_new`, `market_edit` grew `item.order { ...CSGOMarketOrderPublicFields inventory { id } }`;
    PHP keeps `order { __typename }` there with overrides (`../whitemarket_sdk_php/graphql/overrides/`, test
    `tests/unit/Generated/HighLevelItemOrderSelectionTest.php`, DEVIATIONS row) because no model reads it and the server
    failed `order` selections before; mirror that. (b) The high-level `orders` module (SDK_SPEC 3.7) is not in PHP
    0.1.0; `CSGOMarketOrder.link` carries a trade token (secret, like `Profile.steamTradeUrl`).

## Update 2026-11-13: schema sync 2026-11-10, redirects (P25), dependency audit (do these)

`docs/SDK_SPEC.md` and `docs/WHITEMARKET_API.md` were replaced again on 2026-11-13 with the PHP versions. Changes since
the 2026-11-02 copy: SDK_SPEC 1.3 (new "Redirects" bullet, P25) and 3.4 rule 6 (`QUEUED`); WHITEMARKET_API 1 (staging
values) and 4 (deal status groups). PHP references are relative to `../whitemarket_sdk_php/`.

1. **Schema sync 2026-11-10** (PHP PR #5, commit `d4489fc`; `schema/CHANGES.md` "2026-11-10": 0 breaking, 10
   dangerous, 2 safe).
   - Schema: `MarketDealStatus.QUEUED` ("Waiting to send trade offer"), `MarketDealCancelReason.INSTANT_EXCHANGE_FAILED`,
     `WalletTransactionReason.INSTANT_EXCHANGE`, `INSTANT_EXCHANGE_TRANSFER_IN/OUT`, `INSTANT_EXCHANGE_REFUND_IN/OUT`,
     `INSTANT_EXCHANGE_HOLD_RELEASE_IN/OUT`, `MarketProductState.AVAILABLE_FOR_TRADE`, input field
     `MarketProductSearchInput.forTrade: Boolean`. Run this repo's schema sync (or take `schema/partner.graphql` from
     the PHP repo) and regenerate; never edit generated files by hand. Compare `graphql/operations/CHECKSUMS` with PHP's.
   - Deals (SDK_SPEC 3.4 rule 6): `QUEUED` is now sent in the status filters of `listAsBuyer` / `listAsSeller` like any
     other status; remove any client-side rejection. It is an in-progress status (WHITEMARKET_API 4). PHP:
     `src/Models/WireEncoder.php`, `src/Models/DealStatus.php`, tests in `tests/unit/Deals/DealsApiTest.php` and
     `tests/unit/Models/WireEncoderTest.php`.
   - Models (SDK_SPEC 4): add `DealCancelReason.InstantExchangeFailed` and the seven `TransactionReason.InstantExchange*`
     values to the high-level enums; before, they decoded as the unknown variant. PHP: `src/Models/DealCancelReason.php`,
     `src/Models/TransactionReason.php`, `src/Models/ModelMapper.php`, test `tests/unit/Models/TransactionReasonTest.php`.
     If this SDK has an enum parity test that listed `QUEUED` as an allowed extra, drop that exception
     (PHP: `tests/unit/Models/HighLevelEnumParityTest.php`).
   - Not exposed in the high-level layer yet: `forTrade` in the product filter, `AVAILABLE_FOR_TRADE` (generated layer
     only, as in PHP).
   - The `Currency` staging values are still absent from the public schema (WHITEMARKET_API 1).
2. **Redirects (P25, SDK_SPEC 1.3).** The default client never follows a redirect on GraphQL and `auth_*` requests or
   the live SSE GET; a 3xx is `HttpError(status)`, not retried. Only export GETs follow redirects (3.10 rule 2).
   - Why: a client that follows a cross-host redirect resends the request there with the credential headers; Guzzle
     strips `Authorization` but keeps `X-partner-token` [observed in PHP]. A redirected POST is also a resent mutation.
   - Do: disable redirect following on this SDK's default clients for GraphQL, auth and SSE (check your HTTP library's
     default in its docs for the pinned version; many follow redirects by default). Document in the README that an
     injected client must not follow redirects.
   - Tests: a loopback server answers 3xx pointing at a second host; for every default client (query, mutation, live,
     export) the second host receives nothing. Control test: a client that follows redirects does reach the second
     host. PHP: `tests/unit/Transport/GuzzleClientFactoryTest.php` (`sendsNothingToTheHostARedirectPointsAt`,
     `aClientThatFollowsRedirectsCarriesThePartnerTokenToTheOtherHost`), fixture `tests/fixtures/servers/loopback.php`.
3. **Dependency audit workflow (CI, optional but recommended).** PHP added `.github/workflows/dependency-audit.yml` and
   `tools/github/audit-fix.sh`: a daily audit of the lock files; when a fixed version is allowed by the constraints it
   updates only the affected packages and opens or updates a PR; when no fix exists the run fails so a human is
   notified. The audit job has a read-only token and runs no dependency code (no install, no plugins, no scripts); the
   write token lives only in the PR job, which applies the lock-file patch as data. Actions pinned by SHA. Mirror it
   with this ecosystem's audit tool (Go `govulncheck`, `npm audit`, `pip-audit`, `dotnet list package --vulnerable`,
   `cargo audit`), checking the tool's flags in its docs first.
4. **Release notes, "Known limitations"** (item 9 above): `orders` is no longer blocked by the schema (item 12) but is
   still not in PHP 0.1.0; keep the limitation until this SDK ships the module.
