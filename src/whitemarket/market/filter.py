"""`ProductFilter` and `ProductSort`: typed conditions of a product search (SDK_SPEC 3.2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

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
from whitemarket._generated.enums import (
    DeliveryPromise as WireDeliveryPromise,
)
from whitemarket._generated.enums import (
    DeliveryType as WireDeliveryType,
)
from whitemarket._generated.enums import (
    LogicOperand as WireLogicOperand,
)
from whitemarket._generated.input_types import MarketProductSearchInput, MarketProductSortInput
from whitemarket._mappers.wire import (
    assert_sendable,
    present,
    wire_date_range,
    wire_enum,
    wire_enums,
    wire_money_range,
)
from whitemarket.models.enums import (
    App,
    Color,
    DeliveryPromise,
    DeliveryType,
    Exterior,
    ItemCategory,
    ItemSubcategory,
    LogicOperand,
    OfferType,
    Phase,
    ProductSortField,
    Rarity,
    SortDirection,
    StickerFilm,
)
from whitemarket.models.money import Money

_S = TypeVar("_S")
_TUPLE_FIELDS = (
    "name_hashes",
    "names",
    "ids",
    "exclude_categories",
    "exclude_subcategories",
    "rarities",
    "exteriors",
    "colors",
    "sticker_names",
    "sticker_names_by_slot",
)
_DECIMAL_FIELDS = ("float_from", "float_to", "fade_from", "fade_to")
_DATE_FIELDS = ("created_from", "created_to")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductSort:
    """How a product search is ordered (`ProductFilter(sort=...)`); also the sort of an inventory
    list."""

    field: ProductSortField
    direction: SortDirection = SortDirection.ASC

    def to_input(self) -> MarketProductSortInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return MarketProductSortInput(
            field=wire_enum(MarketProductSortField, self.field),
            type_=wire_enum(SortType, self.direction),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductFilter:
    """Conditions of a product search (SDK_SPEC 3.2): every field is optional and the ones given
    are combined with AND. Deprecated fields of the API are not exposed; pass a raw
    `MarketProductSearchInput` to `market.search()` for anything this class does not cover.

    Immutable: change a copy with `dataclasses.replace(filter, name_strict=True)`. Lists given are
    kept as tuples. `price_from` / `price_to` are `Money` bounds (inclusive); `float_from` /
    `float_to` are wear bounds and `fade_from` / `fade_to` Fade percentages, all exact `Decimal`;
    `sticker_names` come from `market.sticker_suggestions()`; `sticker_names_by_slot` holds one
    name per slot, `None` for "any sticker" in that slot; `pattern` is the paint seed;
    `created_from` / `created_to` are aware datetimes (listed at or after / at or before).

    Raises `ValueError` for a price whose currency this SDK does not know or a naive datetime and
    `TypeError` for a `float` where a `Decimal` is required.
    """

    app: App | None = None
    name_hash: str | None = None
    name_hashes: Sequence[str] | None = None
    name: str | None = None
    names: Sequence[str] | None = None
    name_strict: bool | None = None
    ids: Sequence[str] | None = None
    price_from: Money | None = None
    price_to: Money | None = None
    float_from: Decimal | None = None
    float_to: Decimal | None = None
    fade_from: Decimal | None = None
    fade_to: Decimal | None = None
    fade_rank_from: int | None = None
    fade_rank_to: int | None = None
    phase: Phase | None = None
    category: ItemCategory | None = None
    subcategory: ItemSubcategory | None = None
    exclude_categories: Sequence[ItemCategory] | None = None
    exclude_subcategories: Sequence[ItemSubcategory] | None = None
    rarities: Sequence[Rarity] | None = None
    exteriors: Sequence[Exterior] | None = None
    colors: Sequence[Color] | None = None
    stat_trak: bool | None = None
    souvenir: bool | None = None
    has_stickers: bool | None = None
    has_charm: bool | None = None
    sticker_names: Sequence[str] | None = None
    sticker_names_by_slot: Sequence[str | None] | None = None
    sticker_names_operand: LogicOperand | None = None
    sticker_film: StickerFilm | None = None
    sticker_player_id: int | None = None
    sticker_team_id: int | None = None
    sticker_tournament_id: int | None = None
    pattern: int | None = None
    collection: str | None = None
    skin: str | None = None
    delivery_type: DeliveryType | None = None
    delivery_promise: DeliveryPromise | None = None
    offer_type: OfferType | None = None
    store_slug: str | None = None
    sort: ProductSort | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    distinct_values: bool | None = None
    only_promo: bool | None = None
    popular: bool | None = None
    weapon_and_gear: bool | None = None
    special: bool | None = None
    super_deal: bool | None = None

    def __post_init__(self) -> None:
        for name in _TUPLE_FIELDS:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, tuple(value))
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
        for name in _DATE_FIELDS:
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        for price in (self.price_from, self.price_to):
            if price is not None:
                assert_sendable(price)

    def to_input(self) -> MarketProductSearchInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return MarketProductSearchInput(
            **present(
                app_id=wire_enum(SteamApp, self.app),
                color_enum=wire_enums(CatalogColor, self.colors),
                created_at=wire_date_range(self.created_from, self.created_to),
                csgo_charm=self.has_charm,
                csgo_collection=self.collection,
                csgo_exterior_enum=wire_enums(CSGOExterior, self.exteriors),
                csgo_fade_from=self.fade_from,
                csgo_fade_rank_from=self.fade_rank_from,
                csgo_fade_rank_to=self.fade_rank_to,
                csgo_fade_to=self.fade_to,
                csgo_float_from=_plain(self.float_from),
                csgo_float_to=_plain(self.float_to),
                csgo_item_categories_exclude=wire_enums(CSGOCategory, self.exclude_categories),
                csgo_item_category_enum=wire_enum(CSGOCategory, self.category),
                csgo_item_skin=self.skin,
                csgo_item_subcategories_exclude=wire_enums(
                    CSGOSubcategory, self.exclude_subcategories
                ),
                csgo_item_subcategory_enum=wire_enum(CSGOSubcategory, self.subcategory),
                csgo_pattern=self.pattern,
                csgo_phase_enum=wire_enum(CSGOPhase, self.phase),
                csgo_rarity_enum=wire_enums(CSGORarity, self.rarities),
                csgo_souvenir=self.souvenir,
                csgo_stat_trak=self.stat_trak,
                csgo_sticker_film=wire_enum(CSGOStickerFilm, self.sticker_film),
                csgo_sticker_names=_listed(self.sticker_names),
                csgo_sticker_names_by_slot=_listed(self.sticker_names_by_slot),
                csgo_sticker_names_operand=wire_enum(WireLogicOperand, self.sticker_names_operand),
                csgo_sticker_player=self.sticker_player_id,
                csgo_sticker_team=self.sticker_team_id,
                csgo_sticker_tournament=self.sticker_tournament_id,
                csgo_stickers=self.has_stickers,
                delivery_promise=wire_enum(WireDeliveryPromise, self.delivery_promise),
                delivery_type=wire_enum(WireDeliveryType, self.delivery_type),
                distinct_values=self.distinct_values,
                ids=_listed(self.ids),
                is_popular=self.popular,
                is_weapon_and_gear=self.weapon_and_gear,
                name=self.name,
                name_hash=self.name_hash,
                name_strict=self.name_strict,
                names=_listed(self.names),
                names_hash=_listed(self.name_hashes),
                offer_type=wire_enum(MarketOfferType, self.offer_type),
                only_promo=self.only_promo,
                price=wire_money_range(self.price_from, self.price_to),
                sort=None if self.sort is None else self.sort.to_input(),
                special=self.special,
                store_slug=self.store_slug,
                super_deal=self.super_deal,
            )
        )


def _plain(value: Decimal | None) -> str | None:
    """A wear bound as the plain decimal text the API takes (no exponent)."""
    return None if value is None else format(value, "f")


def _listed(values: Sequence[_S] | None) -> list[_S] | None:
    return None if values is None else list(values)
