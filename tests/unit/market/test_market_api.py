"""`client.market` through the HTTP boundary: request shape, decoding, pagination (SDK_SPEC 3.2).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

from decimal import Decimal
from typing import Any

import pytest

from support import market_payloads as mp
from support.clients import Rig
from support.flavors import Flavor
from support.http import data, json_response
from support.payloads import model_json
from whitemarket._generated.enums import SteamApp
from whitemarket._generated.input_types import MarketProductSearchInput
from whitemarket._generated.market_list import (
    MarketListMarketListEdgesNodeItemCSGOInventoryItemProduct,
)
from whitemarket.errors import DecodeError, GraphQLError, NotFoundError
from whitemarket.market import ProductFilter, ProductSort
from whitemarket.models import (
    App,
    Currency,
    Money,
    PageRequest,
    ProductSortField,
    SortDirection,
    StickerFilm,
)


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        pytest.param(None, {}, id="no request -> no variable"),
        pytest.param(PageRequest(), {}, id="empty request -> no variable"),
        pytest.param(
            PageRequest(first=50, after="cursor-1"),
            {"forwardPagination": {"after": "cursor-1", "first": 50}},
            id="first and after",
        ),
        pytest.param(PageRequest(first=1), {"forwardPagination": {"first": 1}}, id="first only"),
        pytest.param(
            PageRequest(after="c"), {"forwardPagination": {"after": "c"}}, id="after only"
        ),
    ],
)
def test_search_sends_forward_pagination_only_when_given(
    flavor: Flavor, page: PageRequest | None, expected: dict[str, Any]
) -> None:
    with Rig(flavor, data(**mp.market_list_data(["ak-1"]))) as rig:
        rig.call(rig.client.market.search(None, page))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketList"
        assert body["query"].lstrip().startswith("query MarketList(")
        assert body.get("variables", {}) == expected


def test_search_maps_the_page(flavor: Flavor) -> None:
    answer = mp.market_list_data(["ak-1", "awp-2"], "cursor-2", True, total_count=5)
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.market.search())

    assert [p.slug for p in page.items] == ["ak-1", "awp-2"]
    assert [p.id for p in page.items] == ["id-ak-1", "id-awp-2"]
    assert (page.end_cursor, page.has_next_page, page.total_count) == ("cursor-2", True, 5)
    assert page.items[0].price == Money.usd("12.50")


def test_search_encodes_a_product_filter(flavor: Flavor) -> None:
    with Rig(flavor, data(**mp.market_list_data([]))) as rig:
        rig.call(rig.client.market.search(ProductFilter(app=App.CSGO, name_strict=True)))

        assert rig.variables() == [{"search": {"appId": "CSGO", "nameStrict": True}}]


def test_search_sends_wear_bounds_and_prices_as_exact_decimal_text(flavor: Flavor) -> None:
    flt = ProductFilter(
        float_from=Decimal("0.0700"),
        float_to=Decimal("0.07000000000000000001"),
        price_from=Money.usd("1.10"),
        price_to=Money(amount=Decimal("99.990"), currency=Currency.USD),
        sort=ProductSort(field=ProductSortField.PRICE, direction=SortDirection.DESC),
    )
    with Rig(flavor, data(**mp.market_list_data([]))) as rig:
        rig.call(rig.client.market.search(flt))

        (variables,) = rig.variables()
        assert variables["search"] == {
            "csgoFloatFrom": "0.0700",
            "csgoFloatTo": "0.07000000000000000001",
            "price": {
                "from": {"currency": "USD", "value": "1.10"},
                "to": {"currency": "USD", "value": "99.990"},
            },
            "sort": {"field": "PRICE", "type": "DESC"},
        }


def test_search_sends_a_raw_input_exactly(flavor: Flavor) -> None:
    raw = MarketProductSearchInput(app_id=SteamApp.TF2, csgo_float_from="0.0700")
    with Rig(flavor, data(**mp.market_list_data([]))) as rig:
        rig.call(rig.client.market.search(raw))

        assert rig.variables() == [{"search": {"appId": "TF2", "csgoFloatFrom": "0.0700"}}]


@pytest.mark.parametrize("typename", ["CSGOInventoryItem", "FutureInventoryItem"])
def test_search_decodes_an_interface_at_the_depth_limit_by_its_typename(
    flavor: Flavor, typename: str
) -> None:
    # `product.item` is selected as `__typename id` only (SDK_SPEC 1.2): a known and an unknown
    # implementation both decode, and the inventory item itself still maps (SPEC_SYNC 2026-11-02 2).
    nested = mp.item(product={**_nested_product(), "item": {"__typename": typename, "id": "n-1"}})
    node = mp.product(id="id-ak", slug="ak", item=nested)
    answer = {
        "market_list": {
            "edges": [{"cursor": "c-ak", "node": node}],
            "pageInfo": mp.page_info(None, False),
            "totalCount": 1,
        }
    }
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.market.search())

    assert [p.slug for p in page.items] == ["ak"]
    assert page.items[0].item is not None


def _nested_product() -> dict[str, Any]:
    return model_json(MarketListMarketListEdgesNodeItemCSGOInventoryItemProduct)


def test_a_listing_of_an_unknown_item_type_is_kept_with_no_item(flavor: Flavor) -> None:
    answer = {
        "market_list": {
            "edges": [
                {"cursor": "a", "node": mp.product(slug="known")},
                {
                    "cursor": "b",
                    "node": mp.product(slug="future", item={"__typename": "Dota2Item"}),
                },
            ],
            "pageInfo": mp.page_info(None, False),
            "totalCount": 2,
        }
    }
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.market.search())

    assert [(p.slug, p.item is None) for p in page.items] == [("known", False), ("future", True)]


def test_null_edges_and_nodes_are_skipped_in_order(flavor: Flavor) -> None:
    answer = {
        "market_list": {
            "edges": [
                {"cursor": "a", "node": mp.product(slug="a", item=None)},
                None,
                {"cursor": "x", "node": None},
                {"cursor": "b", "node": mp.product(slug="b", item=None)},
            ],
            "pageInfo": mp.page_info("b", False),
            "totalCount": 4,
        }
    }
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.market.search())

    assert [p.slug for p in page.items] == ["a", "b"]


def test_a_malformed_amount_is_a_decode_error_naming_its_path(flavor: Flavor) -> None:
    node = mp.product(price={"currency": "USD", "value": "12,50"}, item=None)
    answer = {
        "market_list": {
            "edges": [{"cursor": "c", "node": node}],
            "pageInfo": mp.page_info(None, False),
            "totalCount": 1,
        }
    }
    with Rig(flavor, data(**answer)) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.market.search())

    assert caught.value.path == ("market_list", "edges", 0, "node", "price", "value")
    assert "12,50" not in str(caught.value)


def test_iterate_makes_no_request_until_it_is_consumed(flavor: Flavor) -> None:
    pages = [
        data(**mp.market_list_data(["a", "b"], "c2", True)),
        data(**mp.market_list_data(["c"], "c3", False)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.market.iterate()
        assert rig.script.count == 0, "created, not started"

        assert rig.step(items).slug == "a"
        assert rig.script.count == 1, "the first item needs page 1 only"

        assert rig.step(items).slug == "b"
        assert rig.script.count == 1, "last item of page 1: page 2 is not requested yet"

        assert rig.step(items).slug == "c"
        assert rig.script.count == 2
        with pytest.raises(StopIteration):
            rig.step(items)
        assert rig.script.count == 2, "no next page: no further request"


def test_iterate_follows_cursors_and_sends_the_page_size_and_filter(flavor: Flavor) -> None:
    pages = [
        data(**mp.market_list_data(["a", "b"], "c2", True)),
        data(**mp.market_list_data(["c"], "c3", False)),
    ]
    with Rig(flavor, *pages) as rig:
        slugs = [
            p.slug for p in rig.drain(rig.client.market.iterate(ProductFilter(name_strict=True), 2))
        ]

        assert slugs == ["a", "b", "c"]
        assert rig.variables() == [
            {"forwardPagination": {"first": 2}, "search": {"nameStrict": True}},
            {"forwardPagination": {"after": "c2", "first": 2}, "search": {"nameStrict": True}},
        ]


def test_iterate_without_a_page_size_sends_no_first(flavor: Flavor) -> None:
    pages = [data(**mp.market_list_data(["a"], "c1", True)), data(**mp.market_list_data([]))]
    with Rig(flavor, *pages) as rig:
        rig.drain(rig.client.market.iterate())

        assert rig.variables() == [{}, {"forwardPagination": {"after": "c1"}}]


@pytest.mark.parametrize(
    "second_cursor",
    [pytest.param(None, id="no cursor"), pytest.param("c1", id="the cursor just used")],
)
def test_iterate_refuses_a_next_page_without_a_new_cursor(
    flavor: Flavor, second_cursor: str | None
) -> None:
    pages = [
        data(**mp.market_list_data(["a"], "c1", True)),
        data(**mp.market_list_data(["b"], second_cursor, True)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.market.iterate()
        with pytest.raises(DecodeError) as caught:
            rig.drain(items)

        assert caught.value.path == ("market_list", "pageInfo", "endCursor")
        assert rig.script.count == 2, "the loop did not request a third page"


def test_iterate_refuses_a_first_page_that_reports_more_but_no_cursor(flavor: Flavor) -> None:
    with Rig(flavor, data(**mp.market_list_data(["a"], None, True))) as rig:
        with pytest.raises(DecodeError) as caught:
            rig.drain(rig.client.market.iterate())

        assert caught.value.path == ("market_list", "pageInfo", "endCursor")
        assert rig.script.count == 1


def test_get_sends_the_id_or_slug_and_maps_the_product(flavor: Flavor) -> None:
    node = mp.market_item_node(id="id-1", slug="ak-47-redline")
    with Rig(flavor, data(market_item=node)) as rig:
        product = rig.call(rig.client.market.get("ak-47-redline"))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketItem"
        assert body["variables"] == {"idOrSlug": "ak-47-redline"}
    assert (product.id, product.slug) == ("id-1", "ak-47-redline")
    assert product.item is not None
    assert product.item.asset_id == "9007199254740993"
    assert product.item.float == Decimal("0.15234567890123456789")


def test_get_raises_not_found_by_category(flavor: Flavor) -> None:
    answer = json_response(
        {
            "data": None,
            "errors": [
                {
                    "message": "any text",
                    "path": ["market_item"],
                    "extensions": {"category": "market.product.not_found"},
                }
            ],
        }
    )
    with Rig(flavor, answer) as rig, pytest.raises(NotFoundError):
        rig.call(rig.client.market.get("missing"))


def test_a_graphql_error_without_the_not_found_category_is_not_a_not_found(flavor: Flavor) -> None:
    answer = json_response(
        {
            "data": None,
            "errors": [{"message": "Not found", "extensions": {"category": "market.other"}}],
        }
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.market.get("x"))

    assert not isinstance(caught.value, NotFoundError)


@pytest.mark.parametrize(
    ("args", "sent"),
    [
        pytest.param((), {"limit": 10, "offset": 0}, id="omitted -> schema defaults"),
        pytest.param((5, 20), {"limit": 5, "offset": 20}, id="explicit window"),
        pytest.param((1, 0), {"limit": 1, "offset": 0}, id="zero offset kept"),
    ],
)
def test_sticker_suggestions_send_the_window_and_map_the_answer(
    flavor: Flavor, args: tuple[int, ...], sent: dict[str, int]
) -> None:
    answer = {
        "moreCount": 7,
        "suggestions": [
            {
                "name": "cph2024_team_navi",
                "title": "Natus Vincere",
                "icon": None,
                "film": "HOLO",
                "total": 12,
            },
            None,
            {"name": "future", "title": "Future", "icon": "i.png", "film": "PLASMA", "total": 1},
            {"name": "plain", "title": "Plain", "icon": None, "film": None, "total": 0},
        ],
    }
    with Rig(flavor, data(market_csgo_stickers_suggestion=answer)) as rig:
        result = rig.call(rig.client.market.sticker_suggestions("navi", *args))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketCsgoStickersSuggestion"
        assert body["variables"] == {**sent, "search": "navi"}
    assert result.more_count == 7
    assert [s.name for s in result.items] == ["cph2024_team_navi", "future", "plain"]
    first, future, plain = result.items
    assert first.film is StickerFilm.HOLO
    assert future.film is not None
    assert future.film.is_unknown
    assert future.film.value == "PLASMA"
    assert plain.film is None
    assert future.icon == "i.png"


def test_check_trade_url_sends_the_link_and_returns_the_answer_unchanged(flavor: Flavor) -> None:
    url = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=synthetic"
    with Rig(flavor, data(market_trade_url=" Trade URL ok ")) as rig:
        answer = rig.call(rig.client.market.check_trade_url(url))

        (body,) = rig.bodies()
        assert body["operationName"] == "MarketTradeUrl"
        assert body["variables"] == {"link": {"value": url}}
    assert answer == " Trade URL ok "
