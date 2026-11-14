"""`ProductFilter` and `ProductSort`: typed conditions of a product search (SDK_SPEC 3.2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from whitemarket._mappers.wire import require_sendable
from whitemarket._runtime.filter_checks import normalize_filter
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
        normalize_filter(self, tuples=_TUPLE_FIELDS, decimals=_DECIMAL_FIELDS, dates=_DATE_FIELDS)
        for price in (self.price_from, self.price_to):
            if price is not None:
                require_sendable(price)
