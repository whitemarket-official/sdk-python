"""`client.buying` through the HTTP boundary: request shape, rejections, reconciliation (3.3).

Every case runs against the async client and its generated sync twin. Responses are synthetic and
time is a fake: a wait is a recorded number, never a real sleep.
"""

import re
from decimal import Decimal
from typing import Any

import httpx
import pytest

from support import market_payloads as mp
from support.clients import ClientRig
from support.deal_apis import (
    CUSTOM_ID,
    DEAL_ID,
    DELAY,
    INTERVAL,
    PRODUCT_ID,
    Timeline,
    archived_deal,
    bought,
    buying_api,
    graphql_error,
    live_deal,
    names,
    not_found,
    operations,
)
from support.flavors import Flavor
from support.http import data, json_response, reply
from whitemarket import BuyReconciliation, RetryPolicy, Secret
from whitemarket._generated.market_buy import MarketBuyMarketBuy
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    DecodeError,
    GraphQLError,
    NotFoundError,
    PurchaseOutcomeUnknownError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.models import App, Currency, DealStatus, DeliveryPromise, Money, Phase

UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
TRADE_URL = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=syntheticTradeToken"
WRONG_TYPE: Any = 42  # a value of the wrong type, hidden from the type checker
NO_RETRY = {"retry": RetryPolicy(max_attempts=1)}

CALLS = {
    "buy_product": (
        lambda api, **kw: api.buy_product(PRODUCT_ID, **kw),
        {"id": PRODUCT_ID},
    ),
    "buy_cheapest with every filter": (
        lambda api, **kw: api.buy_cheapest(
            App.CSGO,
            "Doppler Karambit (Factory New)",
            phase=Phase.BLACK_PEARL,
            max_price=Money.usd("12.50"),
            delivery_promise=DeliveryPromise.HOUR1,
            **kw,
        ),
        {
            "appIdNameHashInput": {
                "app": "CSGO",
                "nameHash": "Doppler Karambit (Factory New)",
                "phase": "BLACK_PEARL",
            },
            "deliveryPromise": "HOUR1",
            "maxPriceInput": {"currency": "USD", "value": "12.50"},
        },
    ),
    "buy_cheapest with only the required arguments": (
        lambda api, **kw: api.buy_cheapest(App.TF2, "Mann Co. Supply Crate Key", **kw),
        {"appIdNameHashInput": {"app": "TF2", "nameHash": "Mann Co. Supply Crate Key"}},
    ),
    "buy_by_asset_id": (
        lambda api, **kw: api.buy_by_asset_id(App.DOTA2, "40000000000000000002", **kw),
        {"appIdAssetIdInput": {"app": "DOTA2", "assetId": "40000000000000000002"}},
    ),
}
CALL_IDS = list(CALLS)


def call_params() -> list[Any]:
    return [pytest.param(*CALLS[name], id=name) for name in CALL_IDS]


def rig_of(flavor: Flavor, *outcomes: Any, **options: Any) -> tuple[ClientRig, Timeline, Any]:
    rig = ClientRig(flavor, *outcomes, **{**NO_RETRY, **options})
    timeline = Timeline()
    return rig, timeline, buying_api(rig, timeline)


# ---- success ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("call", "target"), call_params())
def test_sends_one_market_buy_with_the_given_custom_id_and_maps_the_deal(
    flavor: Flavor, call: Any, target: dict[str, Any]
) -> None:
    rig, timeline, api = rig_of(flavor, bought(CUSTOM_ID))
    with rig:
        result = rig.call(call(api, custom_id=CUSTOM_ID))

        assert operations(rig) == [("MarketBuy", {"customId": CUSTOM_ID, **target})]
        assert rig.bodies()[0]["query"].lstrip().startswith("mutation MarketBuy(")
        assert (result.deal.id, result.deal.status) == (DEAL_ID, DealStatus.OFFERED)
        assert result.deal.price == Money.usd("12.50")
        assert (result.custom_id, result.reconciled) == (CUSTOM_ID, False)
        assert timeline.sleeps == []


@pytest.mark.parametrize(("call", "target"), call_params())
def test_never_sends_a_delivery_type_or_a_link_unless_given(
    flavor: Flavor, call: Any, target: dict[str, Any]
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        rig.call(call(api))

        (variables,) = rig.variables()
        assert "deliveryType" not in variables
        assert "link" not in variables


@pytest.mark.parametrize(("call", "target"), call_params())
@pytest.mark.parametrize("secret", [False, True], ids=["str", "Secret"])
def test_sends_the_trade_url_of_a_third_party_as_a_link(
    flavor: Flavor, call: Any, target: dict[str, Any], secret: bool
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        rig.call(
            call(api, custom_id=CUSTOM_ID, trade_url=Secret(TRADE_URL) if secret else TRADE_URL)
        )

        assert rig.variables()[0]["link"] == {"value": TRADE_URL}


@pytest.mark.parametrize(("call", "target"), call_params())
def test_generates_a_uuid_v4_custom_id_and_uses_it_for_the_call_and_the_result(
    flavor: Flavor, call: Any, target: dict[str, Any]
) -> None:
    rig, _, api = rig_of(flavor, bought("generated"), bought("generated"))
    with rig:
        first = rig.call(call(api))
        second = rig.call(call(api))

        sent = [v["customId"] for v in rig.variables()]
        assert UUID_V4.fullmatch(first.custom_id)
        assert UUID_V4.fullmatch(second.custom_id)
        assert first.custom_id != second.custom_id
        assert sent == [first.custom_id, second.custom_id]


# ---- rejections: exactly one request, nothing else ---------------------------------------------

REJECTIONS = [
    pytest.param(graphql_error("market.buy.insufficient_funds"), GraphQLError, id="GraphQL error"),
    pytest.param(graphql_error(), GraphQLError, id="GraphQL error without a category"),
    pytest.param(graphql_error("market.product.not_found"), NotFoundError, id="GraphQL not found"),
    pytest.param(reply(400, b"bad"), BadRequestError, id="HTTP 400"),
    pytest.param(
        reply(401), AuthenticationError, id="HTTP 401 with a token that cannot be renewed"
    ),
    pytest.param(reply(429), RateLimitError, id="HTTP 429"),
    pytest.param(
        reply(429, headers={"Retry-After": "30"}), RateLimitError, id="HTTP 429 + Retry-After"
    ),
]


@pytest.mark.parametrize(("answer", "expected"), REJECTIONS)
def test_rethrows_a_rejection_after_exactly_one_request(
    flavor: Flavor, answer: Any, expected: type[Exception]
) -> None:
    rig, timeline, api = rig_of(flavor, answer)
    with rig:
        with pytest.raises(expected) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert type(caught.value) is expected
        assert names(rig) == ["MarketBuy"], "no lookup follows a rejection"
        assert timeline.sleeps == []


def error(path: list[Any] | None, message: str = "Failure") -> dict[str, Any]:
    entry: dict[str, Any] = {"message": message, "extensions": {"category": "internal"}}
    if path is not None:
        entry["path"] = path
    return entry


def payload_deal() -> dict[str, Any]:
    return mp.deal_as(MarketBuyMarketBuy, id=DEAL_ID, customId=CUSTOM_ID)


GRAPHQL_AFTER_THE_MUTATION = [
    pytest.param(
        {"data": {"market_buy": None}, "errors": [error(["market_buy"])]},
        True,
        id="root-path error with market_buy null -> rejection",
    ),
    pytest.param(
        {"data": None, "errors": [{"message": "Rejected"}]},
        True,
        id="error without a path and data null -> rejection",
    ),
    pytest.param(
        {"data": {"market_buy": payload_deal()}, "errors": [error(["market_buy", "item", "x"])]},
        False,
        id="nested-path error with the created deal in data -> reconcile",
    ),
    pytest.param(
        {"data": {"market_buy": None}, "errors": [error(["market_buy", "product", "price"])]},
        False,
        id="nested-path error with market_buy null -> reconcile",
    ),
    pytest.param(
        {"data": {"market_buy": payload_deal()}, "errors": [error(["market_buy"])]},
        False,
        id="root-path error but market_buy in data -> reconcile",
    ),
    pytest.param(
        {"data": {}, "errors": [error(["market_buy"])]},
        False,
        id="root-path error with an empty data object -> reconcile (ambiguous)",
    ),
    pytest.param(
        {"data": {"other": None}, "errors": [error(["market_buy"])]},
        False,
        id="root-path error with data without market_buy -> reconcile (ambiguous)",
    ),
    pytest.param(
        {"data": {"other": None}, "errors": [{"message": "Rejected"}]},
        False,
        id="error without a path and data without market_buy -> reconcile (ambiguous)",
    ),
    pytest.param(
        {"data": {"auth_token": {"accessToken": "x"}}, "errors": [error(["market_buy"])]},
        False,
        id="root-path error with credential-only data (stripped from the error) -> reconcile",
    ),
    pytest.param(
        {"data": {"market_buy": "x"}, "errors": [error(["market_buy"])]},
        False,
        id="root-path error with a non-null scalar market_buy -> reconcile",
    ),
    pytest.param(
        {"data": [{"market_buy": payload_deal()}], "errors": [{"message": "Failure"}]},
        False,
        id="deal inside a data list -> reconcile",
    ),
    pytest.param(
        {
            "data": {"market_buy": None},
            "errors": [error(["market_buy"]), error(["market_buy", "item"])],
        },
        False,
        id="one root and one nested error -> reconcile",
    ),
    pytest.param(
        {"data": {"market_buy": None}, "errors": [error(["something_else"])]},
        False,
        id="error of another root field -> reconcile",
    ),
    pytest.param(
        {"data": {"market_buy": None}, "errors": [error(["market_buy", 0])]},
        False,
        id="integer path segment below the root field -> reconcile",
    ),
    # A malformed `path` must never read as "no path" (a root error).
    pytest.param(
        {"data": None, "errors": [error(["market_buy", "item", None])]},
        False,
        id="path with a null segment -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [error(["market_buy", "item", "stickers", 1.5])]},
        False,
        id="path with a float segment -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [error(["market_buy", "item", True])]},
        False,
        id="path with a boolean segment -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [error("market_buy.item.description")]},
        False,
        id="path as a dotted string -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [error({"a": "market_buy"})]},
        False,
        id="path as an object -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": ["boom"]},
        False,
        id="error entry that is not an object -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [{"extensions": {"category": "x"}}]},
        False,
        id="error entry without a message -> reconcile",
    ),
    pytest.param(
        {"data": None, "errors": [{"message": "Rejected", "extensions": "nope"}]},
        False,
        id="error entry with extensions that are not an object -> reconcile",
    ),
]


@pytest.mark.parametrize(("payload", "rejection"), GRAPHQL_AFTER_THE_MUTATION)
def test_a_graphql_error_is_a_rejection_only_when_the_mutation_cannot_have_run(
    flavor: Flavor, payload: dict[str, Any], rejection: bool
) -> None:
    rig, _, api = rig_of(flavor, json_response(payload), live_deal())
    with rig:
        if rejection:
            with pytest.raises(GraphQLError):
                rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))
            assert names(rig) == ["MarketBuy"], "no lookup follows a rejection"
            return

        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.reconciled
        assert names(rig) == ["MarketBuy", "DealItem"]


def test_a_not_found_error_below_market_buy_is_reconciled_too(flavor: Flavor) -> None:
    payload = {
        "data": {"market_buy": None},
        "errors": [
            {
                "message": "Gone",
                "path": ["market_buy", "item"],
                "extensions": {"category": "market.product.not_found"},
            }
        ],
    }
    rig, _, api = rig_of(flavor, json_response(payload), live_deal())
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.reconciled
        assert names(rig) == ["MarketBuy", "DealItem"]


def test_an_unexpected_exception_from_the_send_is_reconciled(flavor: Flavor) -> None:
    rig, timeline, api = rig_of(flavor, RuntimeError("send boom"), live_deal())
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.reconciled
        assert names(rig) == ["MarketBuy", "DealItem"]
        assert timeline.sleeps == [DELAY]


class Abort(BaseException):
    """What a cancelled task or an interrupt looks like: not an `Exception`."""


def abort(request: httpx.Request) -> httpx.Response:
    raise Abort


def test_a_cancellation_is_not_reconciled(flavor: Flavor) -> None:
    rig, timeline, api = rig_of(flavor, abort, live_deal())
    with rig:
        with pytest.raises(Abort):
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert names(rig) == ["MarketBuy"]
        assert timeline.sleeps == []


# ---- ambiguous failures: reconcile -------------------------------------------------------------

AMBIGUOUS = [
    pytest.param(reply(500), ServerError, id="HTTP 500"),
    pytest.param(reply(502), ServerError, id="HTTP 502"),
    pytest.param(reply(503), ServiceUnavailableError, id="HTTP 503"),
    pytest.param(
        reply(503, headers={"Retry-After": "30"}),
        ServiceUnavailableError,
        id="HTTP 503 + Retry-After",
    ),
    pytest.param(reply(504), ServerError, id="HTTP 504"),
    pytest.param(reply(418), Exception, id="unexpected HTTP status"),
    pytest.param(httpx.ConnectError("boom"), TransportError, id="network error"),
    pytest.param(httpx.ReadTimeout("boom"), TransportError, id="timeout"),
    pytest.param(reply(200, b"<html>"), DecodeError, id="HTTP 200 with a body that is not JSON"),
    pytest.param(
        data(market_buy={**payload_deal(), "price": {"currency": "USD", "value": "1,5"}}),
        DecodeError,
        id="HTTP 200 with a deal that cannot be mapped",
    ),
]


@pytest.mark.parametrize(("failure", "cause"), AMBIGUOUS)
def test_looks_the_deal_up_once_after_the_delay_and_returns_it_reconciled(
    flavor: Flavor, failure: Any, cause: type[Exception]
) -> None:
    rig, timeline, api = rig_of(flavor, failure, live_deal())
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.reconciled
        assert result.custom_id == CUSTOM_ID
        assert (result.deal.id, result.deal.is_archived) == (DEAL_ID, False)
        assert timeline.sleeps == [DELAY]
        assert operations(rig) == [
            ("MarketBuy", {"customId": CUSTOM_ID, "id": PRODUCT_ID}),
            ("DealItem", {"customId": CUSTOM_ID}),
        ]


@pytest.mark.parametrize(("failure", "cause"), AMBIGUOUS)
def test_fails_with_outcome_unknown_when_reconciliation_finds_nothing(
    flavor: Flavor, failure: Any, cause: type[Exception]
) -> None:
    rig, timeline, api = rig_of(flavor, failure, not_found("live"), not_found("archive"))
    with rig:
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert caught.value.custom_id == CUSTOM_ID
        assert isinstance(caught.value.__cause__, cause), "the market_buy failure is the cause"
        assert isinstance(caught.value.last_lookup_error, NotFoundError)
        assert timeline.sleeps == [DELAY, INTERVAL, INTERVAL, INTERVAL]
        assert names(rig) == [
            "MarketBuy",
            *["DealItem", "DealHistoryItem"] * 3,
        ], "market_buy is sent once; three rounds of two lookups"


def test_finds_an_archived_deal_on_a_later_round(flavor: Flavor) -> None:
    rig, timeline, api = rig_of(
        flavor, reply(503), not_found(), not_found(), not_found(), archived_deal()
    )
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.reconciled
        assert result.deal.is_archived
        assert result.deal.status is DealStatus.STEAM_ROLLBACK
        assert timeline.sleeps == [DELAY, INTERVAL]
        assert names(rig) == [
            "MarketBuy",
            "DealItem",
            "DealHistoryItem",
            "DealItem",
            "DealHistoryItem",
        ]


def test_a_failed_lookup_is_not_found_for_that_round_and_the_last_error_is_kept(
    flavor: Flavor,
) -> None:
    rig, _, _ = rig_of(flavor, reply(502), httpx.ConnectError("boom"), reply(500))
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert isinstance(caught.value.__cause__, ServerError)
        assert isinstance(caught.value.last_lookup_error, ServerError)
        assert caught.value.last_lookup_error.status == 500, "the last lookup, not the first"
        assert rig.script.count == 3


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(reply(500), ServerError, id="HTTP 500"),
        pytest.param(httpx.ConnectError("boom"), TransportError, id="network error"),
    ],
)
def test_a_failed_lookup_is_kept_over_a_later_not_found(
    flavor: Flavor, failure: Any, expected: type[Exception]
) -> None:
    rig, _, _ = rig_of(flavor, reply(500), failure, not_found())
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert isinstance(caught.value.last_lookup_error, expected), (
            "deal_item failed, the archive only said not found"
        )


def test_a_found_deal_that_cannot_be_mapped_counts_as_a_lookup_failure(flavor: Flavor) -> None:
    broken = data(
        deal_item={
            **mp.deal(id=DEAL_ID, customId=CUSTOM_ID),
            "price": {"currency": "USD", "value": "1,5"},
        }
    )
    rig, _, api = rig_of(flavor, reply(500), broken, archived_deal())
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert result.deal.is_archived


@pytest.mark.parametrize(
    "foreign",
    [
        pytest.param("other-order", id="another custom_id"),
        pytest.param(None, id="no custom_id"),
        pytest.param(CUSTOM_ID + " ", id="the custom_id with a trailing space"),
    ],
)
def test_a_found_deal_of_another_custom_id_is_a_failed_lookup_never_a_reconciled_purchase(
    flavor: Flavor, foreign: str | None
) -> None:
    rig, _, _ = rig_of(
        flavor, reply(500), live_deal(foreign), archived_deal(foreign), not_found(), not_found()
    )
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=2, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert isinstance(caught.value.last_lookup_error, DecodeError), "kept over a not-found"
        assert names(rig) == ["MarketBuy", *["DealItem", "DealHistoryItem"] * 2]


def test_a_foreign_deal_in_one_lookup_is_kept_as_the_last_error_and_the_search_goes_on(
    flavor: Flavor,
) -> None:
    rig, _, _ = rig_of(flavor, reply(500), live_deal("other-order"), not_found())
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert isinstance(caught.value.last_lookup_error, DecodeError), "not a plain not-found"
        assert "other-order" not in str(caught.value.last_lookup_error)


def test_a_foreign_live_deal_does_not_hide_the_archived_deal_of_the_custom_id(
    flavor: Flavor,
) -> None:
    rig, _, api = rig_of(flavor, reply(500), live_deal("other-order"), archived_deal())
    with rig:
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert (result.reconciled, result.deal.is_archived, result.deal.custom_id) == (
            True,
            True,
            CUSTOM_ID,
        )


def test_honours_a_custom_reconciliation(flavor: Flavor) -> None:
    rig, timeline, _ = rig_of(flavor, reply(500), not_found(), not_found())
    with rig:
        api = buying_api(rig, timeline, BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError):
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert timeline.sleeps == [10.0, 0.0]
        assert rig.script.count == 3


def test_reconciles_with_the_generated_custom_id(flavor: Flavor) -> None:
    generated = "11111111-2222-4333-8444-555555555555"
    rig, timeline, _ = rig_of(flavor, reply(500), live_deal(generated))
    with rig:
        api = buying_api(rig, timeline, new_custom_id=lambda: generated)
        result = rig.call(api.buy_by_asset_id(App.CSGO, "40000000000000000002"))

        sent, looked_up = rig.variables()
        assert UUID_V4.fullmatch(result.custom_id)
        assert sent["customId"] == result.custom_id
        assert looked_up == {"customId": result.custom_id}


def test_the_outcome_unknown_error_carries_the_generated_custom_id(flavor: Flavor) -> None:
    rig, _, api = rig_of(flavor, reply(500), not_found())
    with rig:
        with pytest.raises(PurchaseOutcomeUnknownError) as caught:
            rig.call(api.buy_by_asset_id(App.CSGO, "40000000000000000002"))

        assert caught.value.custom_id == rig.variables()[0]["customId"]
        assert UUID_V4.fullmatch(caught.value.custom_id)


def test_never_retries_market_buy_even_with_the_default_retry_policy(flavor: Flavor) -> None:
    rig = ClientRig(
        flavor, reply(503), live_deal()
    )  # the client's default RetryPolicy retries queries
    with rig:
        api = buying_api(rig, Timeline())
        result = rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert names(rig) == ["MarketBuy", "DealItem"]
        assert result.reconciled


def test_the_buy_stays_a_single_request_after_a_server_error_with_retries_enabled(
    flavor: Flavor,
) -> None:
    rig = ClientRig(flavor, reply(500), reply(500), reply(500), not_found(), not_found())
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises(PurchaseOutcomeUnknownError):
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID))

        assert names(rig).count("MarketBuy") == 1


# ---- input validation: before anything is sent --------------------------------------------------


@pytest.mark.parametrize(
    ("custom_id", "accepted"),
    [
        pytest.param("a", True, id="1 character"),
        pytest.param("a" * 100, True, id="100 characters"),
        pytest.param("ж" * 100, True, id="100 non-ASCII characters"),
        pytest.param("", False, id="empty"),
        pytest.param("a" * 101, False, id="101 characters"),
        pytest.param("\ud800", False, id="a lone surrogate"),
    ],
)
def test_a_given_custom_id_is_1_to_100_characters_of_valid_text(
    flavor: Flavor, custom_id: str, accepted: bool
) -> None:
    rig, _, api = rig_of(flavor, bought(custom_id) if accepted else bought())
    with rig:
        if accepted:
            assert rig.call(api.buy_product(PRODUCT_ID, custom_id=custom_id)).custom_id == custom_id
            return
        with pytest.raises(ValueError, match="custom_id"):
            rig.call(api.buy_product(PRODUCT_ID, custom_id=custom_id))

        assert rig.script.count == 0


BUY_WITH_UNSENDABLE_TEXT = [
    pytest.param(lambda api: api.buy_product("\ud800", custom_id=CUSTOM_ID), id="product id"),
    pytest.param(
        lambda api: api.buy_cheapest(App.CSGO, "x\ud800", custom_id=CUSTOM_ID), id="name hash"
    ),
    pytest.param(
        lambda api: api.buy_by_asset_id(App.CSGO, "1\ud800", custom_id=CUSTOM_ID), id="asset id"
    ),
    pytest.param(
        lambda api: api.buy_product(PRODUCT_ID, trade_url="https://x/\ud800", custom_id=CUSTOM_ID),
        id="trade url",
    ),
    pytest.param(
        lambda api: api.buy_product(
            PRODUCT_ID, trade_url=Secret("https://x/\ud800"), custom_id=CUSTOM_ID
        ),
        id="trade url as a Secret",
    ),
]


@pytest.mark.parametrize("call", BUY_WITH_UNSENDABLE_TEXT)
def test_a_text_that_cannot_be_encoded_is_refused_before_anything_is_sent_or_reconciled(
    flavor: Flavor, call: Any
) -> None:
    rig, timeline, api = rig_of(flavor, reply(500), live_deal())
    with rig:
        with pytest.raises(ValueError, match="valid Unicode") as caught:
            rig.call(call(api))

        assert rig.script.count == 0
        assert timeline.sleeps == []
        assert "\ud800" not in str(caught.value)


def test_a_custom_id_of_the_wrong_type_is_refused_before_sending(flavor: Flavor) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        with pytest.raises(TypeError, match="custom_id"):
            rig.call(api.buy_product(PRODUCT_ID, custom_id=WRONG_TYPE))

        assert rig.script.count == 0


def test_a_trade_url_of_the_wrong_type_is_refused_before_sending(flavor: Flavor) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        with pytest.raises(TypeError, match="trade_url"):
            rig.call(api.buy_product(PRODUCT_ID, trade_url=WRONG_TYPE))

        assert rig.script.count == 0


CALLS_WITH_A_MAX_PRICE = {
    "buy_product": lambda api, price: api.buy_product(PRODUCT_ID, price, custom_id=CUSTOM_ID),
    "buy_cheapest": lambda api, price: api.buy_cheapest(
        App.CSGO, "AK-47 | Redline (Field-Tested)", max_price=price, custom_id=CUSTOM_ID
    ),
    "buy_by_asset_id": lambda api, price: api.buy_by_asset_id(
        App.CSGO, "40000000000000000002", price, custom_id=CUSTOM_ID
    ),
}


@pytest.fixture(params=list(CALLS_WITH_A_MAX_PRICE))
def with_max_price(request: pytest.FixtureRequest) -> Any:
    return CALLS_WITH_A_MAX_PRICE[request.param]


def test_sends_the_max_price_as_an_exact_decimal_when_given(
    flavor: Flavor, with_max_price: Any
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        rig.call(with_max_price(api, Money.usd("12.50")))

        assert rig.variables()[0]["maxPriceInput"] == {"currency": "USD", "value": "12.50"}


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        pytest.param("0.07", "0.07", id="below one"),
        pytest.param("1E+2", "100", id="exponent form is sent plain"),
        pytest.param(
            "12345678901234567890.123456789", "12345678901234567890.123456789", id="many digits"
        ),
    ],
)
def test_the_max_price_never_passes_through_a_binary_float(
    flavor: Flavor, amount: str, text: str
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        price = Money(amount=Decimal(amount), currency=Currency.USD)
        rig.call(api.buy_product(PRODUCT_ID, price, custom_id=CUSTOM_ID))

        assert rig.variables()[0]["maxPriceInput"]["value"] == text


def test_omits_the_max_price_key_when_none_is_given(flavor: Flavor, with_max_price: Any) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        rig.call(with_max_price(api, None))

        assert "maxPriceInput" not in rig.variables()[0]


def test_rejects_a_max_price_with_an_unknown_currency_before_sending(
    flavor: Flavor, with_max_price: Any
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        price = Money(amount=Decimal("5"), currency=Currency("EUR"))
        with pytest.raises(ValueError, match="EUR"):
            rig.call(with_max_price(api, price))

        assert rig.script.count == 0


def test_rejects_an_app_or_phase_the_api_cannot_take_before_sending(flavor: Flavor) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig:
        with pytest.raises(ValueError, match="App"):
            rig.call(api.buy_cheapest(App("ATARI"), "x", custom_id=CUSTOM_ID))
        with pytest.raises(ValueError, match="Phase"):
            rig.call(api.buy_cheapest(App.CSGO, "x", phase=Phase("PURPLE"), custom_id=CUSTOM_ID))

        assert rig.script.count == 0


# ---- the trade URL is sensitive ------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [pytest.param(reply(400), id="rejected (400)"), pytest.param(reply(500), id="ambiguous (500)")],
)
def test_a_failed_buy_keeps_the_trade_url_out_of_every_message(
    flavor: Flavor, failure: Any
) -> None:
    rig, _, _ = rig_of(flavor, failure, not_found(), not_found())
    with rig:
        api = buying_api(rig, Timeline(), BuyReconciliation(delay=10.0, attempts=1, interval=0.0))
        with pytest.raises((GraphQLError, BadRequestError, PurchaseOutcomeUnknownError)) as caught:
            rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID, trade_url=TRADE_URL))

        error: BaseException | None = caught.value
        while error is not None:
            assert "syntheticTradeToken" not in f"{error!s} {error!r}"
            last = getattr(error, "last_lookup_error", None)
            assert last is None or "syntheticTradeToken" not in f"{last!s} {last!r}"
            error = error.__cause__


def test_the_trade_url_never_reaches_the_log(
    flavor: Flavor, caplog: pytest.LogCaptureFixture
) -> None:
    rig, _, api = rig_of(flavor, bought())
    with rig, caplog.at_level("DEBUG"):
        rig.call(api.buy_product(PRODUCT_ID, custom_id=CUSTOM_ID, trade_url=TRADE_URL))

    assert "syntheticTradeToken" not in caplog.text
