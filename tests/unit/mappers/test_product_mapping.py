"""Generated result -> `Product`, `ProductHistory`, `InventoryItem`, `Page` (SDK_SPEC 4).

The generated models are built from synthetic wire JSON; nothing is stubbed.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from support import market_payloads as mp
from whitemarket._generated.deal_item import DealItemDealItemProduct
from whitemarket._generated.market_csgo_stickers_suggestion import (
    MarketCsgoStickersSuggestionMarketCsgoStickersSuggestion as Suggestions,
)
from whitemarket._generated.market_item import MarketItemMarketItem
from whitemarket._generated.market_list import (
    MarketList,
)
from whitemarket._generated.market_list import (
    MarketListMarketListEdgesNodeItemCSGOInventoryItemDescriptionCSGOSteamItem as SteamItem,
)
from whitemarket._mappers.products import (
    map_inventory_item,
    map_product,
    map_product_history,
    map_product_page,
    map_sticker_suggestions,
)
from whitemarket.errors import DecodeError
from whitemarket.models import Currency, DeliveryPromise, DeliveryType, Money, ProductStatus

PATH = ("market_item",)


def product_of(**overrides: Any) -> Any:
    return map_product(MarketItemMarketItem.model_validate(mp.market_item_node(**overrides)), PATH)


def test_a_product_maps_every_field() -> None:
    product = product_of(isOwner=True, deliveryType="MANUAL", deliveryPromise="HOURS12")

    assert (product.id, product.slug, product.is_owner) == ("product-1", "ak-47-redline", True)
    assert product.price == Money.usd("12.50")
    assert product.created_at.utcoffset() == timedelta(hours=2)
    assert (product.delivery_type, product.delivery_promise) == (
        DeliveryType.MANUAL,
        DeliveryPromise.HOURS12,
    )
    assert product.item is not None


def test_money_keeps_every_digit() -> None:
    price = {"currency": "USD", "value": "0.1000000000000000000001"}

    assert product_of(price=price).price.amount == Decimal("0.1000000000000000000001")


@pytest.mark.parametrize(
    "value",
    ["", "1,5", "1e3", "+1", " 1", "1 ", "1.", ".5", "NaN", "Infinity", "12.5\n", "١٢"],
)
def test_a_malformed_amount_is_a_decode_error_with_the_path_and_without_the_value(
    value: str,
) -> None:
    with pytest.raises(DecodeError) as caught:
        product_of(price={"currency": "USD", "value": value})

    assert caught.value.path == ("market_item", "price", "value")
    assert caught.value.reason == "not a decimal number"
    assert repr(value) not in str(caught.value) or value == ""


@pytest.mark.parametrize("value", ["0", "-0.5", "12", "007.50"])
def test_a_plain_decimal_is_accepted(value: str) -> None:
    assert product_of(price={"currency": "USD", "value": value}).price.amount == Decimal(value)


def test_unknown_enum_values_keep_the_raw_value() -> None:
    product = product_of(
        deliveryType="DRONE",
        deliveryPromise="WEEK1",
        price={"currency": "EUR", "value": "1"},
    )

    assert product.delivery_type.is_unknown
    assert product.delivery_type.value == "DRONE"
    assert product.delivery_promise.is_unknown
    assert product.delivery_promise.value == "WEEK1"
    assert product.price.currency.is_unknown
    assert product.price.currency.value == "EUR"
    assert product.price.currency is not Currency.USD


def test_an_item_of_an_unknown_type_maps_to_none_and_keeps_the_product() -> None:
    product = product_of(item={"__typename": "Dota2InventoryItem"})

    assert product.item is None
    assert product.slug == "ak-47-redline"


def test_a_null_item_maps_to_none() -> None:
    assert product_of(item=None).item is None


def test_an_item_maps_ids_as_strings_and_wear_as_an_exact_decimal() -> None:
    item = product_of().item

    assert item.asset_id == "9007199254740993"  # beyond 2^53
    assert (item.class_id, item.instance_id, item.id) == ("310776560", "188530139", "item-1")
    assert item.float == Decimal("0.15234567890123456789")
    assert (item.paint_seed, item.paint_index, item.phase) == ("661", "282", None)
    assert item.inspect_link == "steam://inspect/synthetic"
    assert item.name_hash == "AK-47 | Redline (Field-Tested)"


def test_a_null_wear_stays_none() -> None:
    assert product_of(item=mp.item(float=None)).item.float is None


def test_a_malformed_wear_is_a_decode_error_at_the_item() -> None:
    with pytest.raises(DecodeError) as caught:
        product_of(item=mp.item(float="0,15"))

    assert caught.value.path == ("market_item", "item", "float")


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        pytest.param(
            mp.steam_item(isStatTrak=True, isSouvenir=False),
            ("AK-47 | Redline (Field-Tested)", True, False),
            id="statTrak",
        ),
        pytest.param(
            mp.steam_item(isStatTrak=False, isSouvenir=True),
            ("AK-47 | Redline (Field-Tested)", False, True),
            id="souvenir",
        ),
        pytest.param(None, (None, None, None), id="no description"),
        pytest.param(
            {"__typename": "FutureSteamItem"}, (None, None, None), id="unknown description type"
        ),
    ],
)
def test_name_and_flags_come_from_the_steam_description(
    description: Any, expected: tuple[str | None, bool | None, bool | None]
) -> None:
    item = product_of(item=mp.item(description=description)).item

    assert (item.name, item.is_stat_trak, item.is_souvenir) == expected


def test_stickers_keep_exact_wear_and_skip_null_entries() -> None:
    stickers = [
        mp.sticker(name="a", wear="0.0123456789012345678"),
        None,
        mp.sticker(name="b", wear=None),
    ]

    mapped = product_of(item=mp.item(stickers=stickers)).item.stickers

    assert [(s.name, s.wear) for s in mapped] == [
        ("a", Decimal("0.0123456789012345678")),
        ("b", None),
    ]


def test_a_malformed_sticker_wear_names_its_index() -> None:
    stickers = [mp.sticker(wear="0.1"), mp.sticker(wear="x")]

    with pytest.raises(DecodeError) as caught:
        product_of(item=mp.item(stickers=stickers))

    assert caught.value.path == ("market_item", "item", "stickers", 1, "wear")


def test_a_product_page_skips_null_edges_and_nodes_and_reports_the_page_info() -> None:
    answer = {
        "market_list": {
            "edges": [
                {"cursor": "a", "node": mp.product(slug="a", item=None)},
                None,
                {"cursor": "n", "node": None},
            ],
            "pageInfo": mp.page_info("a", True),
            "totalCount": 9,
        }
    }
    page = map_product_page(MarketList.model_validate(answer).market_list, ("market_list",))

    assert [p.slug for p in page.items] == ["a"]
    assert (page.end_cursor, page.has_next_page, page.total_count) == ("a", True, 9)


@pytest.mark.parametrize(
    "connection",
    [
        pytest.param({"edges": None, "pageInfo": None, "totalCount": None}, id="everything null"),
        pytest.param({"edges": [], "pageInfo": None, "totalCount": None}, id="empty edges"),
    ],
)
def test_a_missing_page_info_means_no_next_page(connection: dict[str, Any]) -> None:
    page = map_product_page(
        MarketList.model_validate({"market_list": connection}).market_list, ("p",)
    )

    assert (page.items, page.end_cursor, page.has_next_page, page.total_count) == (
        (),
        None,
        False,
        None,
    )


def history_of(**overrides: Any) -> Any:
    raw = DealItemDealItemProduct.model_validate(mp.history_product(**overrides))
    return map_product_history(raw, ("deal_item", "product"))


def test_a_product_history_maps_its_fields() -> None:
    history = history_of(status="EXPIRED")

    assert history.status is ProductStatus.EXPIRED
    assert history.price == Money.usd("12.50")
    assert history.archived_at.utcoffset() == timedelta(0)
    assert (history.asset_id, history.class_id, history.instance_id) == (
        "9007199254740993",
        "310776560",
        "188530139",
    )
    assert history.item is None


def test_a_product_history_describes_its_item_from_the_product_description() -> None:
    params = {**mp.item(), "__typename": "CSGOInventoryItem"}
    del params["description"]

    history = history_of(
        params=params, description=mp.steam_item(name="Souvenir AWP", isSouvenir=True)
    )

    assert history.item.name == "Souvenir AWP"
    assert history.item.is_souvenir is True
    assert history.item.stickers == ()


def test_an_item_own_description_wins_over_the_given_one() -> None:
    node = MarketItemMarketItem.model_validate(
        mp.market_item_node(item=mp.item(description=mp.steam_item(name="Own")))
    )
    other = SteamItem.model_validate(mp.steam_item(name="Product"))

    assert map_inventory_item(node.item, other, ()).name == "Own"
    assert map_inventory_item(node.item, None, ()).name == "Own"


def test_an_unknown_product_status_keeps_the_raw_value() -> None:
    status = history_of(status="TELEPORTED").status

    assert status.is_unknown
    assert status.value == "TELEPORTED"


def test_a_history_malformed_amount_names_the_path() -> None:
    with pytest.raises(DecodeError) as caught:
        history_of(price={"currency": "USD", "value": "oops"})

    assert caught.value.path == ("deal_item", "product", "price", "value")


def test_a_history_item_of_an_unknown_type_is_none() -> None:
    assert history_of(params={"__typename": "TF2InventoryItem"}).item is None


def test_map_inventory_item_ignores_things_that_are_not_items() -> None:
    assert map_inventory_item(None, None, ()) is None
    assert map_inventory_item(object(), None, ()) is None
    assert map_inventory_item("CSGOInventoryItem", None, ()) is None


def test_sticker_suggestions_map_with_unknown_film_kept() -> None:
    raw = Suggestions.model_validate(
        {
            "moreCount": 3,
            "suggestions": [
                {"name": "n", "title": "T", "icon": None, "film": "PLASMA", "total": 2},
                None,
            ],
        }
    )

    mapped = map_sticker_suggestions(raw)

    assert mapped.more_count == 3
    assert [(s.name, s.film.value, s.film.is_unknown, s.total) for s in mapped.items] == [
        ("n", "PLASMA", True, 2)
    ]
