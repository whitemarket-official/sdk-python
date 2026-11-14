"""`client.selling` single mutations and `my_products` through the HTTP boundary (SDK_SPEC 3.5).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

from decimal import Decimal
from typing import Any

import httpx
import pytest

from support import selling_payloads as sp
from support.clients import ClientRig as Rig
from support.flavors import Flavor
from support.http import data, json_response, reply
from whitemarket._generated.input_types import MarketProductSearchInput
from whitemarket._generated.market_edit import MarketEditMarketEdit
from whitemarket._generated.market_new import MarketNewMarketNew
from whitemarket._generated.market_remove import MarketRemoveMarketRemove
from whitemarket.errors import (
    DecodeError,
    GraphQLError,
    RateLimitError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.market import ProductFilter
from whitemarket.models import (
    Currency,
    DeliveryPromise,
    DeliveryType,
    Money,
    PageRequest,
    Product,
    ProductHistory,
    ProductStatus,
)

PRICE = Money.usd("12.50")
WIRE_PRICE = {"currency": "USD", "value": "12.50"}
LONG_ASSET = "40000000000000000002"


def listed(**overrides: Any) -> Any:
    return data(market_new=sp.product_as(MarketNewMarketNew, id=sp.PRODUCT_ID, **overrides))


@pytest.mark.parametrize(
    ("item", "options", "expected"),
    [
        pytest.param(
            sp.INVENTORY_ID,
            {},
            {"inventoryId": sp.INVENTORY_ID, "deliveryType": "SEMI"},
            id="inventory id, no options",
        ),
        pytest.param(
            sp.ASSET_ID, {}, {"assetId": sp.ASSET_ID, "deliveryType": "SEMI"}, id="asset id"
        ),
        pytest.param(
            sp.INVENTORY_ID.upper(),
            {},
            {"inventoryId": sp.INVENTORY_ID.upper(), "deliveryType": "SEMI"},
            id="upper-case inventory id is sent as given",
        ),
        pytest.param(
            sp.ASSET_ID,
            {"delivery_type": DeliveryType.MANUAL},
            {"assetId": sp.ASSET_ID, "deliveryType": "MANUAL"},
            id="manual delivery",
        ),
        pytest.param(
            sp.ASSET_ID,
            {"lifetime": 60},
            {"assetId": sp.ASSET_ID, "deliveryType": "SEMI", "lifetime": 60},
            id="lifetime only",
        ),
        pytest.param(
            sp.ASSET_ID,
            {"delivery_promise": DeliveryPromise.HOUR1},
            {"assetId": sp.ASSET_ID, "deliveryType": "SEMI", "deliveryPromise": "HOUR1"},
            id="promise only",
        ),
        pytest.param(
            sp.INVENTORY_ID,
            {
                "delivery_type": DeliveryType.MANUAL,
                "delivery_promise": DeliveryPromise.HOUR1,
                "lifetime": 31_536_000,
            },
            {
                "inventoryId": sp.INVENTORY_ID,
                "deliveryType": "MANUAL",
                "deliveryPromise": "HOUR1",
                "lifetime": 31_536_000,
            },
            id="everything",
        ),
    ],
)
def test_list_sends_one_market_new_and_maps_the_product(
    flavor: Flavor, item: str, options: dict[str, Any], expected: dict[str, Any]
) -> None:
    with Rig(flavor, listed(slug="ak")) as rig:
        product = rig.call(rig.client.selling.list(item, PRICE, **options))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketNew"
        assert body["query"].lstrip().startswith("mutation MarketNew(")
        assert body["variables"] == {"price": WIRE_PRICE, **expected}
    assert isinstance(product, Product)
    assert (product.id, product.slug, product.price) == (sp.PRODUCT_ID, "ak", PRICE)


def test_list_with_an_asset_id_of_20_digits_keeps_every_digit(flavor: Flavor) -> None:
    with Rig(flavor, listed()) as rig:
        rig.call(rig.client.selling.list(LONG_ASSET, PRICE))

        assert rig.variables()[0]["assetId"] == LONG_ASSET


def test_list_sends_a_price_with_many_places_as_exact_text(flavor: Flavor) -> None:
    price = Money.usd(Decimal("0.123456789012345678"))
    with Rig(flavor, listed()) as rig:
        rig.call(rig.client.selling.list(LONG_ASSET, price))

        assert rig.variables()[0]["price"] == {"currency": "USD", "value": "0.123456789012345678"}


@pytest.mark.parametrize(
    "item",
    ["", "400000000000000000021", " 123", "123\n", sp.INVENTORY_ID + "\n", "AK-47 | Redline", "-1"],
    ids=["empty", "21 digits", "leading space", "digits+newline", "uuid+newline", "name", "signed"],
)
def test_list_refuses_a_bad_item_before_any_request(flavor: Flavor, item: str) -> None:
    with Rig(flavor, listed()) as rig:
        with pytest.raises(ValueError, match="inventory id"):
            rig.call(rig.client.selling.list(item, PRICE))

        assert rig.script.count == 0


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param({"delivery_type": DeliveryType.AUTO}, "AUTO delivery", id="AUTO"),
        pytest.param({"lifetime": 59}, "60..31536000", id="lifetime 59"),
        pytest.param({"lifetime": 31_536_001}, "60..31536000", id="lifetime 31536001"),
    ],
)
def test_list_refuses_bad_options_before_any_request(
    flavor: Flavor, options: dict[str, Any], message: str
) -> None:
    with Rig(flavor, listed()) as rig:
        with pytest.raises(ValueError, match=message):
            rig.call(rig.client.selling.list(sp.ASSET_ID, PRICE, **options))

        assert rig.script.count == 0


def test_list_refuses_a_price_in_an_unknown_currency_before_any_request(flavor: Flavor) -> None:
    with Rig(flavor, listed()) as rig:
        with pytest.raises(ValueError, match="unknown currency"):
            rig.call(
                rig.client.selling.list(
                    sp.ASSET_ID, Money(amount=Decimal(5), currency=Currency("EUR"))
                )
            )

        assert rig.script.count == 0


def test_reprice_sends_one_market_edit_and_maps_the_product(flavor: Flavor) -> None:
    answer = data(market_edit=sp.product_as(MarketEditMarketEdit, id=sp.PRODUCT_ID))
    with Rig(flavor, answer) as rig:
        product = rig.call(rig.client.selling.reprice(sp.PRODUCT_ID, Money.usd("9.99")))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketEdit"
        assert body["variables"] == {
            "marketProductId": sp.PRODUCT_ID,
            "price": {"currency": "USD", "value": "9.99"},
        }
    assert product.id == sp.PRODUCT_ID


@pytest.mark.parametrize("call", ["reprice", "remove"])
@pytest.mark.parametrize("bad", [sp.ASSET_ID, "", sp.PRODUCT_ID + "\n", "not-a-uuid"])
def test_reprice_and_remove_refuse_anything_but_a_uuid_before_any_request(
    flavor: Flavor, call: str, bad: str
) -> None:
    with Rig(flavor, data()) as rig:
        selling = rig.client.selling
        with pytest.raises(ValueError, match="product id must be a UUID"):
            rig.call(selling.reprice(bad, PRICE) if call == "reprice" else selling.remove(bad))

        assert rig.script.count == 0


def test_remove_sends_one_market_remove_and_maps_the_archived_product(flavor: Flavor) -> None:
    answer = data(
        market_remove=sp.history_as(MarketRemoveMarketRemove, id=sp.PRODUCT_ID, status="REMOVED")
    )
    with Rig(flavor, answer) as rig:
        archived = rig.call(rig.client.selling.remove(sp.PRODUCT_ID))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketRemove"
        assert body["variables"] == {"marketProductId": sp.PRODUCT_ID}
    assert isinstance(archived, ProductHistory)
    assert (archived.id, archived.status) == (sp.PRODUCT_ID, ProductStatus("REMOVED"))


@pytest.mark.parametrize(
    ("seconds", "accepted"),
    [
        pytest.param(599, False, id="one below the minimum"),
        pytest.param(600, True, id="the minimum"),
        pytest.param(86_400, True, id="a day"),
        pytest.param(0, False, id="zero"),
        pytest.param(-600, False, id="negative"),
    ],
)
def test_set_lifetime_for_all_validates_the_minimum_before_any_request(
    flavor: Flavor, seconds: int, accepted: bool
) -> None:
    with Rig(flavor, data(market_lifetime_all=True)) as rig:
        if not accepted:
            with pytest.raises(ValueError, match="at least 600 seconds"):
                rig.call(rig.client.selling.set_lifetime_for_all(seconds))
            assert rig.script.count == 0
            return

        assert rig.call(rig.client.selling.set_lifetime_for_all(seconds)) is True
        (body,) = rig.bodies()
        assert body["operationName"] == "MarketLifetimeAll"
        assert body["variables"] == {"value": seconds}


def test_set_lifetime_for_all_returns_the_servers_answer_even_when_false(flavor: Flavor) -> None:
    with Rig(flavor, data(market_lifetime_all=False)) as rig:
        assert rig.call(rig.client.selling.set_lifetime_for_all(600)) is False


CALLS = {
    "list": (lambda s: s.list(sp.ASSET_ID, PRICE), "MarketNew"),
    "reprice": (lambda s: s.reprice(sp.PRODUCT_ID, PRICE), "MarketEdit"),
    "remove": (lambda s: s.remove(sp.PRODUCT_ID), "MarketRemove"),
    "set_lifetime_for_all": (lambda s: s.set_lifetime_for_all(600), "MarketLifetimeAll"),
}


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        pytest.param(reply(503), ServiceUnavailableError, id="503"),
        pytest.param(reply(429), RateLimitError, id="429"),
        pytest.param(httpx.ConnectError("boom"), TransportError, id="network error"),
        pytest.param(reply(200, b"not json"), DecodeError, id="unreadable answer"),
        pytest.param(
            json_response({"data": None, "errors": [{"message": "m", "path": ["x"]}]}),
            GraphQLError,
            id="graphql error",
        ),
    ],
)
def test_a_single_mutation_is_sent_once_and_the_failure_reaches_the_caller(
    flavor: Flavor, call: str, outcome: Any, error: type[Exception]
) -> None:
    build, operation = CALLS[call]
    with Rig(flavor, outcome, listed()) as rig:
        with pytest.raises(error):
            rig.call(build(rig.client.selling))

        assert [b["operationName"] for b in rig.bodies()] == [operation], "never resent"


@pytest.mark.parametrize(
    ("page", "filter_", "expected"),
    [
        pytest.param(None, None, {}, id="nothing"),
        pytest.param(
            PageRequest(first=5, after="c1"),
            ProductFilter(name_strict=True),
            {"forwardPagination": {"after": "c1", "first": 5}, "search": {"nameStrict": True}},
            id="page and filter",
        ),
        pytest.param(
            None,
            MarketProductSearchInput(name="ak"),
            {"search": {"name": "ak"}},
            id="a raw input is sent as is",
        ),
    ],
)
def test_my_products_sends_market_my_and_maps_the_page(
    flavor: Flavor, page: PageRequest | None, filter_: Any, expected: dict[str, Any]
) -> None:
    with Rig(flavor, data(**sp.my_products_data(["a", "b"], "c2", True))) as rig:
        result = rig.call(rig.client.selling.my_products(filter_, page))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketMy"
        assert body["query"].lstrip().startswith("query MarketMy(")
        assert body.get("variables", {}) == expected
    assert [p.slug for p in result.items] == ["a", "b"]
    assert (result.end_cursor, result.has_next_page, result.total_count) == ("c2", True, 3)


def test_iterate_my_products_is_lazy_follows_cursors_and_keeps_the_filter(flavor: Flavor) -> None:
    pages = [
        data(**sp.my_products_data(["a", "b"], "c2", True)),
        data(**sp.my_products_data(["c"], "c3", False)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.selling.iterate_my_products(ProductFilter(name_strict=True), 2)
        assert rig.script.count == 0, "created, not started"

        assert rig.step(items).slug == "a"
        assert rig.step(items).slug == "b"
        assert rig.script.count == 1, "page 2 is requested only when page 1 is consumed"
        assert rig.step(items).slug == "c"
        with pytest.raises(StopIteration):
            rig.step(items)

        assert rig.variables() == [
            {"forwardPagination": {"first": 2}, "search": {"nameStrict": True}},
            {"forwardPagination": {"after": "c2", "first": 2}, "search": {"nameStrict": True}},
        ]


def test_iterate_my_products_names_the_list_in_the_error_of_a_missing_cursor(
    flavor: Flavor,
) -> None:
    with Rig(flavor, data(**sp.my_products_data(["a"], None, True))) as rig:
        items = rig.client.selling.iterate_my_products()
        rig.step(items)

        with pytest.raises(DecodeError) as error:
            rig.step(items)

        assert error.value.path == ("market_my", "pageInfo", "endCursor")
