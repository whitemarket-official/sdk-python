"""`InventoryFilter`: typed conditions of an inventory list (SDK_SPEC 3.6)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from whitemarket._runtime.filter_checks import normalize_filter
from whitemarket.market.filter import ProductSort
from whitemarket.models.enums import (
    Color,
    Exterior,
    ItemCategory,
    ItemSubcategory,
    LogicOperand,
    Phase,
    Rarity,
)

_TUPLE_FIELDS = ("rarities", "exteriors", "colors", "sticker_names")
_DECIMAL_FIELDS = ("float_from", "float_to", "fade_from", "fade_to")


@dataclass(frozen=True, slots=True, kw_only=True)
class InventoryFilter:
    """Conditions of an inventory list (`inventory.list()`): every field is optional and the ones
    given are combined with AND. Deprecated fields of the API are not exposed; pass a raw
    `PersonInventorySearchInput` to `inventory.list()` for anything this class does not cover.

    Immutable: change a copy with `dataclasses.replace(filter, stat_trak=True)`. Lists given are
    kept as tuples. `float_from` / `float_to` are wear bounds and `fade_from` / `fade_to` Fade
    percentages, all exact `Decimal`; `sticker_names` come from `market.sticker_suggestions()`;
    `pattern` is the paint seed; `sort` reuses the product sort (the API shares its fields).

    Raises `TypeError` for a `float` where a `Decimal` is required.
    """

    name_hash: str | None = None
    name: str | None = None
    name_strict: bool | None = None
    category: ItemCategory | None = None
    subcategory: ItemSubcategory | None = None
    rarities: Sequence[Rarity] | None = None
    exteriors: Sequence[Exterior] | None = None
    colors: Sequence[Color] | None = None
    phase: Phase | None = None
    float_from: Decimal | None = None
    float_to: Decimal | None = None
    fade_from: Decimal | None = None
    fade_to: Decimal | None = None
    fade_rank_from: int | None = None
    fade_rank_to: int | None = None
    stat_trak: bool | None = None
    souvenir: bool | None = None
    has_stickers: bool | None = None
    has_charm: bool | None = None
    sticker_names: Sequence[str] | None = None
    sticker_names_operand: LogicOperand | None = None
    pattern: int | None = None
    collection: str | None = None
    sort: ProductSort | None = None

    def __post_init__(self) -> None:
        normalize_filter(self, tuples=_TUPLE_FIELDS, decimals=_DECIMAL_FIELDS)
