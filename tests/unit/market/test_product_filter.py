"""`ProductFilter` and `ProductSort`: the high-level builder over `MarketProductSearchInput`."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from whitemarket._mappers.search import product_search_input, product_sort_input
from whitemarket._runtime.json_codec import to_plain
from whitemarket.market import ProductFilter, ProductSort
from whitemarket.models import (
    App,
    Color,
    Currency,
    DeliveryPromise,
    DeliveryType,
    Exterior,
    ItemCategory,
    ItemSubcategory,
    LogicOperand,
    Money,
    OfferType,
    Phase,
    ProductSortField,
    Rarity,
    SortDirection,
    StickerFilm,
)

NAIVE = datetime(2026, 11, 1, tzinfo=UTC).replace(tzinfo=None)


def wire(flt: ProductFilter) -> Any:
    """What the transport would send for this filter."""
    return to_plain(product_search_input(flt))


def test_an_empty_filter_sends_nothing() -> None:
    assert wire(ProductFilter()) == {}


@pytest.mark.parametrize(
    ("filter_", "expected"),
    [
        pytest.param(ProductFilter(app=App.DOTA2), {"appId": "DOTA2"}, id="app"),
        pytest.param(
            ProductFilter(name_hash="AK-47 | Vulcan"),
            {"nameHash": "AK-47 | Vulcan"},
            id="name hash",
        ),
        pytest.param(
            ProductFilter(name_hashes=["a", "b"]), {"namesHash": ["a", "b"]}, id="name hashes"
        ),
        pytest.param(
            ProductFilter(name="Vulcan", names=["x"]),
            {"name": "Vulcan", "names": ["x"]},
            id="names",
        ),
        pytest.param(
            ProductFilter(name_strict=False), {"nameStrict": False}, id="false is sent, not dropped"
        ),
        pytest.param(ProductFilter(ids=["i-1"]), {"ids": ["i-1"]}, id="ids"),
        pytest.param(
            ProductFilter(fade_from=Decimal("80.0"), fade_to=Decimal("100.0")),
            {"csgoFadeFrom": Decimal("80.0"), "csgoFadeTo": Decimal("100.0")},
            id="fade",
        ),
        pytest.param(
            ProductFilter(fade_rank_from=1, fade_rank_to=9),
            {"csgoFadeRankFrom": 1, "csgoFadeRankTo": 9},
            id="fade rank",
        ),
        pytest.param(ProductFilter(phase=Phase.RUBY), {"csgoPhaseEnum": "RUBY"}, id="phase"),
        pytest.param(
            ProductFilter(category=ItemCategory.KNIVES),
            {"csgoItemCategoryEnum": "KNIVES"},
            id="category",
        ),
        pytest.param(
            ProductFilter(subcategory=ItemSubcategory.AK47),
            {"csgoItemSubcategoryEnum": "AK47"},
            id="subcategory",
        ),
        pytest.param(
            ProductFilter(exclude_categories=[ItemCategory.CASE, ItemCategory.STICKERS]),
            {"csgoItemCategoriesExclude": ["CASE", "STICKERS"]},
            id="exclude categories",
        ),
        pytest.param(
            ProductFilter(exclude_subcategories=[ItemSubcategory.AWP]),
            {"csgoItemSubcategoriesExclude": ["AWP"]},
            id="exclude subcategories",
        ),
        pytest.param(
            ProductFilter(rarities=[Rarity.ANCIENT]), {"csgoRarityEnum": ["ANCIENT"]}, id="rarities"
        ),
        pytest.param(
            ProductFilter(exteriors=[Exterior.FACTORY_NEW]),
            {"csgoExteriorEnum": ["FACTORY_NEW"]},
            id="exteriors",
        ),
        pytest.param(ProductFilter(colors=[Color.RED]), {"colorEnum": ["RED"]}, id="colors"),
        pytest.param(
            ProductFilter(stat_trak=True, souvenir=False),
            {"csgoStatTrak": True, "csgoSouvenir": False},
            id="stattrak and souvenir",
        ),
        pytest.param(
            ProductFilter(has_stickers=True, has_charm=False),
            {"csgoStickers": True, "csgoCharm": False},
            id="stickers and charm presence",
        ),
        pytest.param(
            ProductFilter(sticker_names=["s1"], sticker_names_operand=LogicOperand.OR),
            {"csgoStickerNames": ["s1"], "csgoStickerNamesOperand": "OR"},
            id="sticker names",
        ),
        pytest.param(
            ProductFilter(sticker_names_by_slot=["s1", None, "s3"]),
            {"csgoStickerNamesBySlot": ["s1", None, "s3"]},
            id="sticker names by slot keep the null",
        ),
        pytest.param(
            ProductFilter(
                sticker_film=StickerFilm.HOLO,
                sticker_player_id=1,
                sticker_team_id=2,
                sticker_tournament_id=3,
            ),
            {
                "csgoStickerFilm": "HOLO",
                "csgoStickerPlayer": 1,
                "csgoStickerTeam": 2,
                "csgoStickerTournament": 3,
            },
            id="sticker facets",
        ),
        pytest.param(
            ProductFilter(pattern=878, collection="set_gamma_2", skin="Vulcan"),
            {"csgoPattern": 878, "csgoCollection": "set_gamma_2", "csgoItemSkin": "Vulcan"},
            id="pattern collection skin",
        ),
        pytest.param(
            ProductFilter(
                delivery_type=DeliveryType.AUTO, delivery_promise=DeliveryPromise.HOURS12
            ),
            {"deliveryType": "AUTO", "deliveryPromise": "HOURS12"},
            id="delivery",
        ),
        pytest.param(
            ProductFilter(offer_type=OfferType.BARGAIN, store_slug="best-store"),
            {"offerType": "BARGAIN", "storeSlug": "best-store"},
            id="offer type and store",
        ),
        pytest.param(
            ProductFilter(
                distinct_values=True,
                only_promo=True,
                popular=True,
                weapon_and_gear=True,
                special=True,
                super_deal=True,
            ),
            {
                "distinctValues": True,
                "onlyPromo": True,
                "isPopular": True,
                "isWeaponAndGear": True,
                "special": True,
                "superDeal": True,
            },
            id="flags",
        ),
    ],
)
def test_each_field_goes_to_its_wire_field(
    filter_: ProductFilter, expected: dict[str, Any]
) -> None:
    assert wire(filter_) == expected


def test_a_price_range_keeps_the_exact_digits_and_either_bound_alone_is_enough() -> None:
    both = ProductFilter(price_from=Money.usd("1.10"), price_to=Money.usd("99.990"))
    low = ProductFilter(price_from=Money.usd("0.07"))
    high = ProductFilter(price_to=Money.usd("5"))

    assert wire(both) == {
        "price": {
            "from": {"currency": "USD", "value": "1.10"},
            "to": {"currency": "USD", "value": "99.990"},
        }
    }
    assert wire(low) == {"price": {"from": {"currency": "USD", "value": "0.07"}}}
    assert wire(high) == {"price": {"to": {"currency": "USD", "value": "5"}}}


def test_a_price_amount_is_never_written_in_exponent_form() -> None:
    flt = ProductFilter(price_from=Money(amount=Decimal("1E+3"), currency=Currency.USD))

    assert wire(flt) == {"price": {"from": {"currency": "USD", "value": "1000"}}}


def test_wear_bounds_are_sent_as_plain_decimal_text() -> None:
    flt = ProductFilter(float_from=Decimal("0.0700"), float_to=Decimal("1E-7"))

    assert wire(flt) == {"csgoFloatFrom": "0.0700", "csgoFloatTo": "0.0000001"}


def test_a_created_range_is_sent_as_iso_dates_with_offsets() -> None:
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    end = datetime(2026, 11, 2, 10, 0, tzinfo=timezone(timedelta(hours=2)))

    assert wire(ProductFilter(created_from=start, created_to=end)) == {
        "createdAt": {"from": "2026-11-01T10:00:00+00:00", "to": "2026-11-02T10:00:00+02:00"}
    }
    assert wire(ProductFilter(created_to=end)) == {"createdAt": {"to": "2026-11-02T10:00:00+02:00"}}


def test_a_sort_goes_as_field_and_type() -> None:
    flt = ProductFilter(sort=ProductSort(field=ProductSortField.PRICE))
    desc = ProductFilter(
        sort=ProductSort(field=ProductSortField.CREATED, direction=SortDirection.DESC)
    )

    assert wire(flt) == {"sort": {"field": "PRICE", "type": "ASC"}}
    assert wire(desc) == {"sort": {"field": "CREATED", "type": "DESC"}}


def test_the_filter_is_immutable_and_copies_its_lists() -> None:
    names = ["a"]
    flt = ProductFilter(names=names)
    names.append("b")

    assert flt.names == ("a",)
    with pytest.raises(FrozenInstanceError):
        flt.name_strict = True


@pytest.mark.parametrize(
    ("kwargs", "error", "name"),
    [
        pytest.param({"float_from": 0.07}, TypeError, "float_from", id="float wear bound"),
        pytest.param({"float_to": "0.07"}, TypeError, "float_to", id="string wear bound"),
        pytest.param({"fade_from": 80.0}, TypeError, "fade_from", id="float fade bound"),
        pytest.param({"fade_to": 1}, TypeError, "fade_to", id="int fade bound"),
        pytest.param({"created_from": NAIVE}, ValueError, "created_from", id="naive start"),
        pytest.param({"created_to": NAIVE}, ValueError, "created_to", id="naive end"),
    ],
)
def test_invalid_values_are_refused_at_construction(
    kwargs: dict[str, Any], error: type[Exception], name: str
) -> None:
    with pytest.raises(error, match=name):
        ProductFilter(**kwargs)


@pytest.mark.parametrize("bound", ["price_from", "price_to"])
def test_a_price_in_an_unknown_currency_is_refused_at_construction(bound: str) -> None:
    unknown = Money(amount=Decimal(1), currency=Currency("EUR"))

    with pytest.raises(ValueError, match="EUR"):
        ProductFilter(**{bound: unknown})


def test_an_enum_value_the_schema_does_not_accept_is_refused_when_sent() -> None:
    unknown_phase = Phase("FUTURE_PHASE")
    unknown_app = App("UNKNOWN")  # declared by the schema, deliberately not an App member

    with pytest.raises(ValueError, match="FUTURE_PHASE"):
        product_search_input(ProductFilter(phase=unknown_phase))
    with pytest.raises(ValueError, match="UNKNOWN"):
        product_search_input(ProductFilter(app=unknown_app))
    with pytest.raises(ValueError, match="ZZZ"):
        product_search_input(
            ProductFilter(exclude_categories=[ItemCategory.CASE, ItemCategory("ZZZ")])
        )


def test_a_sort_with_an_unknown_field_is_refused_when_sent() -> None:
    with pytest.raises(ValueError, match="NEW_FIELD"):
        product_sort_input(ProductSort(field=ProductSortField("NEW_FIELD")))
