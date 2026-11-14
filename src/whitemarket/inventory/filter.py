"""`InventoryFilter`: typed conditions of an inventory list (SDK_SPEC 3.6)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from whitemarket._generated.enums import (
    CatalogColor,
    CSGOCategory,
    CSGOExterior,
    CSGOPhase,
    CSGORarity,
    CSGOSubcategory,
)
from whitemarket._generated.enums import LogicOperand as WireLogicOperand
from whitemarket._generated.input_types import PersonInventorySearchInput
from whitemarket._mappers.wire import (
    present,
    product_sort_input,
    wire_decimal,
    wire_enum,
    wire_enums,
    wire_list,
)
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

    def to_input(self) -> PersonInventorySearchInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return PersonInventorySearchInput(
            **present(
                color_enum=wire_enums(CatalogColor, self.colors),
                csgo_charm=self.has_charm,
                csgo_collection=self.collection,
                csgo_exterior_enum=wire_enums(CSGOExterior, self.exteriors),
                csgo_fade_from=self.fade_from,
                csgo_fade_rank_from=self.fade_rank_from,
                csgo_fade_rank_to=self.fade_rank_to,
                csgo_fade_to=self.fade_to,
                csgo_float_from=wire_decimal(self.float_from),
                csgo_float_to=wire_decimal(self.float_to),
                csgo_item_category_enum=wire_enum(CSGOCategory, self.category),
                csgo_item_subcategory_enum=wire_enum(CSGOSubcategory, self.subcategory),
                csgo_pattern=self.pattern,
                csgo_phase_enum=wire_enum(CSGOPhase, self.phase),
                csgo_rarity_enum=wire_enums(CSGORarity, self.rarities),
                csgo_souvenir=self.souvenir,
                csgo_stat_trak=self.stat_trak,
                csgo_sticker_names=wire_list(self.sticker_names),
                csgo_sticker_names_operand=wire_enum(WireLogicOperand, self.sticker_names_operand),
                csgo_stickers=self.has_stickers,
                name=self.name,
                name_hash=self.name_hash,
                name_strict=self.name_strict,
                sort=None if self.sort is None else product_sort_input(self.sort),
            )
        )
