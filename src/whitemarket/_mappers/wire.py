"""High-level values to generated input types (CLAUDE.md rule 12: API names only at the boundary).

High-level enums are matched to the wire enum by value. A value the wire enum does not know (or an
unknown value of the high-level enum) cannot be sent: it is a `ValueError` here, not a server
error later.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar, overload

from whitemarket._generated.enums import (
    CatalogColor,
    CSGOCategory,
    CSGOExterior,
    CSGOPhase,
    CSGORarity,
    CSGOStickerFilm,
    CSGOSubcategory,
    MarketOfferType,
    MarketProductSortField,
    SortType,
    SteamApp,
)
from whitemarket._generated.enums import DeliveryPromise as WireDeliveryPromise
from whitemarket._generated.enums import DeliveryType as WireDeliveryType
from whitemarket._generated.enums import LogicOperand as WireLogicOperand
from whitemarket._generated.input_types import (
    DateTimeRangeInput,
    MarketProductSearchInput,
    MarketProductSortInput,
    MoneyInput,
    MoneyRangeInput,
)
from whitemarket._runtime.enums import UnknownTolerantEnum
from whitemarket._runtime.unset import UNSET, UnsetType
from whitemarket.models.money import Money

if TYPE_CHECKING:
    from whitemarket.market.filter import ProductFilter, ProductSort

_W = TypeVar("_W", bound=UnknownTolerantEnum)
_S = TypeVar("_S")


@overload
def wire_enum(wire: type[_W], value: UnknownTolerantEnum) -> _W: ...
@overload
def wire_enum(wire: type[_W], value: None) -> None: ...
@overload
def wire_enum(wire: type[_W], value: UnknownTolerantEnum | None) -> _W | None: ...
def wire_enum(wire: type[_W], value: UnknownTolerantEnum | None) -> _W | None:
    """The wire enum member with the value of `value`; None stays None."""
    if value is None:
        return None
    converted = wire(value.value)
    if value.is_unknown or converted.is_unknown:
        raise ValueError(
            f"{type(value).__name__} value {value.value} cannot be sent: "
            "the API schema does not accept it"
        )
    return converted


def wire_enums(wire: type[_W], values: Sequence[UnknownTolerantEnum] | None) -> list[_W] | None:
    if values is None:
        return None
    return [wire_enum(wire, value) for value in values]


def require_sendable(money: Money) -> None:
    """A price with a currency this SDK does not know cannot be sent."""
    if money.currency.is_unknown:
        raise ValueError(f"unknown currency {money.currency.value} cannot be sent")


def wire_money(money: Money) -> MoneyInput:
    require_sendable(money)
    return MoneyInput(currency=money.currency, value=format(money.amount, "f"))


def present(**fields: Any) -> dict[str, Any]:
    """The fields that are not None: an unset input field is left out of the request, a None one
    would be sent as `null`."""
    return {name: value for name, value in fields.items() if value is not None}


def wire_money_range(start: Money | None, end: Money | None) -> MoneyRangeInput | None:
    """None when both bounds are None."""
    if start is None and end is None:
        return None
    return MoneyRangeInput(
        **present(
            from_=None if start is None else wire_money(start),
            to=None if end is None else wire_money(end),
        )
    )


def wire_date_range(start: datetime | None, end: datetime | None) -> DateTimeRangeInput | None:
    """None when both bounds are None."""
    if start is None and end is None:
        return None
    return DateTimeRangeInput(**present(from_=start, to=end))


def wire_decimal(value: Decimal | None) -> str | None:
    """A wear bound as the plain decimal text the API takes (no exponent)."""
    return None if value is None else format(value, "f")


def wire_list(values: Sequence[_S] | None) -> list[_S] | None:
    return None if values is None else list(values)


def product_sort_input(sort: "ProductSort") -> MarketProductSortInput:
    return MarketProductSortInput(
        field=wire_enum(MarketProductSortField, sort.field),
        type_=wire_enum(SortType, sort.direction),
    )


def search_argument(
    product_filter: "ProductFilter | MarketProductSearchInput | None",
) -> MarketProductSearchInput | UnsetType:
    """The `search` variable of `market_list` / `market_my`: a filter is encoded, a raw input is
    sent as is, and nothing at all is sent for None."""
    if product_filter is None:
        return UNSET
    if isinstance(product_filter, MarketProductSearchInput):
        return product_filter
    return product_search_input(product_filter)


def product_search_input(product_filter: "ProductFilter") -> MarketProductSearchInput:
    """The generated search input of a `ProductFilter`; unset conditions are left out."""
    return MarketProductSearchInput(
        **present(
            app_id=wire_enum(SteamApp, product_filter.app),
            color_enum=wire_enums(CatalogColor, product_filter.colors),
            created_at=wire_date_range(product_filter.created_from, product_filter.created_to),
            csgo_charm=product_filter.has_charm,
            csgo_collection=product_filter.collection,
            csgo_exterior_enum=wire_enums(CSGOExterior, product_filter.exteriors),
            csgo_fade_from=product_filter.fade_from,
            csgo_fade_rank_from=product_filter.fade_rank_from,
            csgo_fade_rank_to=product_filter.fade_rank_to,
            csgo_fade_to=product_filter.fade_to,
            csgo_float_from=wire_decimal(product_filter.float_from),
            csgo_float_to=wire_decimal(product_filter.float_to),
            csgo_item_categories_exclude=wire_enums(
                CSGOCategory, product_filter.exclude_categories
            ),
            csgo_item_category_enum=wire_enum(CSGOCategory, product_filter.category),
            csgo_item_skin=product_filter.skin,
            csgo_item_subcategories_exclude=wire_enums(
                CSGOSubcategory, product_filter.exclude_subcategories
            ),
            csgo_item_subcategory_enum=wire_enum(CSGOSubcategory, product_filter.subcategory),
            csgo_pattern=product_filter.pattern,
            csgo_phase_enum=wire_enum(CSGOPhase, product_filter.phase),
            csgo_rarity_enum=wire_enums(CSGORarity, product_filter.rarities),
            csgo_souvenir=product_filter.souvenir,
            csgo_stat_trak=product_filter.stat_trak,
            csgo_sticker_film=wire_enum(CSGOStickerFilm, product_filter.sticker_film),
            csgo_sticker_names=wire_list(product_filter.sticker_names),
            csgo_sticker_names_by_slot=wire_list(product_filter.sticker_names_by_slot),
            csgo_sticker_names_operand=wire_enum(
                WireLogicOperand, product_filter.sticker_names_operand
            ),
            csgo_sticker_player=product_filter.sticker_player_id,
            csgo_sticker_team=product_filter.sticker_team_id,
            csgo_sticker_tournament=product_filter.sticker_tournament_id,
            csgo_stickers=product_filter.has_stickers,
            delivery_promise=wire_enum(WireDeliveryPromise, product_filter.delivery_promise),
            delivery_type=wire_enum(WireDeliveryType, product_filter.delivery_type),
            distinct_values=product_filter.distinct_values,
            ids=wire_list(product_filter.ids),
            is_popular=product_filter.popular,
            is_weapon_and_gear=product_filter.weapon_and_gear,
            name=product_filter.name,
            name_hash=product_filter.name_hash,
            name_strict=product_filter.name_strict,
            names=wire_list(product_filter.names),
            names_hash=wire_list(product_filter.name_hashes),
            offer_type=wire_enum(MarketOfferType, product_filter.offer_type),
            only_promo=product_filter.only_promo,
            price=wire_money_range(product_filter.price_from, product_filter.price_to),
            sort=None if product_filter.sort is None else product_sort_input(product_filter.sort),
            special=product_filter.special,
            store_slug=product_filter.store_slug,
            super_deal=product_filter.super_deal,
        )
    )
