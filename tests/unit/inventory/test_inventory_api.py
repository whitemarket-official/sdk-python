"""`client.inventory` through the HTTP boundary: request shape, mapping, pagination (SDK_SPEC 3.6).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

from decimal import Decimal
from typing import Any

import httpx
import pytest

from support import account_payloads as ap
from support.clients import Rig
from support.flavors import Flavor
from support.http import data, json_response, reply
from whitemarket import RetryPolicy
from whitemarket._generated.enums import CSGOExterior
from whitemarket._generated.input_types import PersonInventorySearchInput
from whitemarket.errors import DecodeError, GraphQLError, ServerError, TransportError
from whitemarket.inventory import InventoryFilter
from whitemarket.market import ProductSort
from whitemarket.models import (
    Color,
    Exterior,
    ItemCategory,
    ItemSubcategory,
    LogicOperand,
    PageRequest,
    Phase,
    ProductSortField,
    Rarity,
    SortDirection,
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
    ],
)
def test_list_sends_forward_pagination_only_when_given(
    flavor: Flavor, page: PageRequest | None, expected: dict[str, Any]
) -> None:
    with Rig(flavor, data(**ap.inventory_page(["a"]))) as rig:
        rig.call(rig.client.inventory.list(None, page))

        (body,) = rig.bodies()
        assert body["operationName"] == "InventoryMy"
        assert body["query"].lstrip().startswith("query InventoryMy(")
        assert body.get("variables", {}) == expected


def test_list_maps_the_page_and_the_item(flavor: Flavor) -> None:
    answer = ap.inventory_page(["a", "b"], "cursor-2", True)
    answer["inventory_my"]["totalCount"] = 5
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.inventory.list())

    assert [i.id for i in page.items] == ["item-a", "item-b"]
    assert (page.end_cursor, page.has_next_page, page.total_count) == ("cursor-2", True, 5)
    item = page.items[0]
    assert item.asset_id == "9007199254740993"  # beyond 2^53: stays text
    assert item.float == Decimal("0.15234567890123456789")
    assert item.name == "AK-47 | Redline (Field-Tested)"
    assert item.name_hash == "AK-47 | Redline (Field-Tested)"


def test_items_of_another_game_and_null_entries_are_skipped_but_counted(flavor: Flavor) -> None:
    answer = {
        "inventory_my": {
            "edges": [
                {"cursor": "a", "node": ap.inventory_item(id="kept-1")},
                {"cursor": "x", "node": {"__typename": "Dota2InventoryItem"}},
                None,
                {"cursor": "n", "node": None},
                {"cursor": "b", "node": ap.inventory_item(id="kept-2")},
            ],
            "pageInfo": ap.mp.page_info("b", False),
            "totalCount": 5,
        }
    }
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.inventory.list())

    assert [i.id for i in page.items] == ["kept-1", "kept-2"]
    assert page.total_count == 5, "the server's count includes the skipped entries"


def test_a_page_without_edges_or_page_info_is_an_empty_last_page(flavor: Flavor) -> None:
    answer = {"inventory_my": {"edges": None, "pageInfo": None, "totalCount": None}}
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.inventory.list())

    assert (page.items, page.end_cursor, page.has_next_page, page.total_count) == (
        (),
        None,
        False,
        None,
    )


def test_list_encodes_an_inventory_filter_with_exact_decimals_and_the_shared_sort(
    flavor: Flavor,
) -> None:
    flt = InventoryFilter(
        name_hash="AK-47 | Redline (Field-Tested)",
        name_strict=True,
        category=ItemCategory.RIFLES,
        subcategory=ItemSubcategory.AK47,
        rarities=[Rarity.RARE],
        exteriors=[Exterior.FIELD_TESTED],
        colors=[Color.RED],
        phase=Phase.PHASE1,
        float_from=Decimal("0.0700"),
        float_to=Decimal("0.07000000000000000001"),
        fade_from=Decimal("80.5"),
        fade_rank_from=1,
        stat_trak=True,
        souvenir=False,
        has_stickers=True,
        has_charm=False,
        sticker_names=["a", "b"],
        sticker_names_operand=LogicOperand.OR,
        pattern=661,
        collection="set_gamma_2",
        sort=ProductSort(field=ProductSortField.PRICE, direction=SortDirection.DESC),
    )
    with Rig(flavor, data(**ap.inventory_page([]))) as rig:
        rig.call(rig.client.inventory.list(flt))

        (variables,) = rig.variables()
    assert variables["search"] == {
        "colorEnum": ["RED"],
        "csgoCharm": False,
        "csgoCollection": "set_gamma_2",
        "csgoExteriorEnum": ["FIELD_TESTED"],
        "csgoFadeFrom": 80.5,  # a JSON number: the schema type is Float
        "csgoFadeRankFrom": 1,
        "csgoFloatFrom": "0.0700",
        "csgoFloatTo": "0.07000000000000000001",
        "csgoItemCategoryEnum": "RIFLES",
        "csgoItemSubcategoryEnum": "AK47",
        "csgoPattern": 661,
        "csgoPhaseEnum": "PHASE1",
        "csgoRarityEnum": ["RARE"],
        "csgoSouvenir": False,
        "csgoStatTrak": True,
        "csgoStickerNames": ["a", "b"],
        "csgoStickerNamesOperand": "OR",
        "csgoStickers": True,
        "nameHash": "AK-47 | Redline (Field-Tested)",
        "nameStrict": True,
        "sort": {"field": "PRICE", "type": "DESC"},
    }


def test_list_leaves_unset_conditions_out(flavor: Flavor) -> None:
    with Rig(flavor, data(**ap.inventory_page([]))) as rig:
        rig.call(rig.client.inventory.list(InventoryFilter(stat_trak=False)))

        assert rig.variables() == [{"search": {"csgoStatTrak": False}}]


def test_list_sends_a_raw_input_exactly(flavor: Flavor) -> None:
    raw = PersonInventorySearchInput(csgo_exterior_enum=[CSGOExterior.WELL_WORN], name="Vulcan")
    with Rig(flavor, data(**ap.inventory_page([]))) as rig:
        rig.call(rig.client.inventory.list(raw))

        assert rig.variables() == [
            {"search": {"csgoExteriorEnum": ["WELL_WORN"], "name": "Vulcan"}}
        ]


def test_a_malformed_wear_is_a_decode_error_naming_its_path(flavor: Flavor) -> None:
    node = ap.inventory_item(**{"float": "0,15"})
    answer = ap.connection("inventory_my", [node])
    with Rig(flavor, data(**answer)) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.inventory.list())

    assert caught.value.path == ("inventory_my", "edges", 0, "node", "float")
    assert "0,15" not in str(caught.value)


def test_list_raises_a_graphql_error_with_its_category(flavor: Flavor) -> None:
    answer = json_response(
        {
            "data": None,
            "errors": [{"message": "x", "extensions": {"category": "inventory.private"}}],
        }
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.inventory.list())

    assert caught.value.errors[0].category == "inventory.private"


def test_list_is_retried_as_a_query(flavor: Flavor) -> None:
    with Rig(
        flavor, reply(503), data(**ap.inventory_page(["a"])), retry=RetryPolicy(base_delay=0)
    ) as rig:
        page = rig.call(rig.client.inventory.list())

        assert rig.script.count == 2
    assert len(page.items) == 1


def test_iterate_makes_no_request_until_it_is_consumed(flavor: Flavor) -> None:
    pages = [
        data(**ap.inventory_page(["a", "b"], "c2", True)),
        data(**ap.inventory_page(["c"], "c3", False)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.inventory.iterate()
        assert rig.script.count == 0, "created, not started"

        assert rig.step(items).id == "item-a"
        assert rig.step(items).id == "item-b"
        assert rig.script.count == 1, "last item of page 1: page 2 is not requested yet"

        assert rig.step(items).id == "item-c"
        assert rig.script.count == 2
        with pytest.raises(StopIteration):
            rig.step(items)
        assert rig.script.count == 2, "hasNextPage was false: no further request"


def test_iterate_follows_cursors_keeping_the_filter_and_the_page_size(flavor: Flavor) -> None:
    pages = [
        data(**ap.inventory_page(["a"], "c1", True)),
        data(**ap.inventory_page(["b"], None, False)),
    ]
    with Rig(flavor, *pages) as rig:
        ids = [
            i.id for i in rig.drain(rig.client.inventory.iterate(InventoryFilter(souvenir=True), 1))
        ]

        assert ids == ["item-a", "item-b"]
        assert rig.variables() == [
            {"forwardPagination": {"first": 1}, "search": {"csgoSouvenir": True}},
            {"forwardPagination": {"after": "c1", "first": 1}, "search": {"csgoSouvenir": True}},
        ]


def test_iterate_refuses_a_next_page_without_a_new_cursor(flavor: Flavor) -> None:
    with Rig(flavor, data(**ap.inventory_page(["a"], None, True))) as rig:
        with pytest.raises(DecodeError) as caught:
            rig.drain(rig.client.inventory.iterate())

        assert caught.value.path == ("inventory_my", "pageInfo", "endCursor")
        assert rig.script.count == 1


def test_refresh_from_steam_sends_the_mutation_once_and_returns_nothing(flavor: Flavor) -> None:
    answer = data(inventory_update=ap.profile())
    with Rig(flavor, answer) as rig:
        result = rig.call(rig.client.inventory.refresh_from_steam())

        (body,) = rig.bodies()
        assert body["operationName"] == "InventoryUpdate"
        assert body["query"].lstrip().startswith("mutation InventoryUpdate")
    assert result is None


def test_refresh_from_steam_is_never_retried(flavor: Flavor) -> None:
    with Rig(flavor, reply(503), data(inventory_update=ap.profile()), retry=RetryPolicy()) as rig:
        with pytest.raises(ServerError):
            rig.call(rig.client.inventory.refresh_from_steam())

        assert rig.script.count == 1


def test_refresh_from_steam_after_a_network_error_is_not_resent(flavor: Flavor) -> None:
    with Rig(flavor, httpx.ConnectError("synthetic"), data(inventory_update=ap.profile())) as rig:
        with pytest.raises(TransportError):
            rig.call(rig.client.inventory.refresh_from_steam())

        assert rig.script.count == 1
