"""`DealHistoryFilter` and `DealHistorySort`: conditions of `deals.history()` (SDK_SPEC 3.4)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from whitemarket._generated.enums import (
    CatalogColor,
    CSGOExterior,
    CSGOPhase,
    CSGORarity,
    CSGOStickerFilm,
    MarketDealActionType,
    MarketDealHistorySortField,
    MarketDealHistoryStatus,
    SortType,
)
from whitemarket._generated.enums import LogicOperand as WireLogicOperand
from whitemarket._generated.input_types import (
    MarkerDealHistorySearchInput,
    MarketDealHistorySortInput,
)
from whitemarket._mappers.wire import (
    present,
    require_sendable,
    wire_date_range,
    wire_decimal,
    wire_enum,
    wire_enums,
    wire_list,
    wire_money_range,
)
from whitemarket._runtime.filter_checks import normalize_filter
from whitemarket.models.enums import (
    Color,
    DealAction,
    DealHistorySortField,
    DealHistoryStatus,
    Exterior,
    LogicOperand,
    Phase,
    Rarity,
    SortDirection,
    StickerFilm,
)
from whitemarket.models.money import Money

_TUPLE_FIELDS = (
    "asset_ids",
    "rarities",
    "exteriors",
    "colors",
    "sticker_names",
    "sticker_names_by_slot",
)
_DECIMAL_FIELDS = ("float_from", "float_to")
_DATE_FIELDS = ("created_from", "created_to")


@dataclass(frozen=True, slots=True, kw_only=True)
class DealHistorySort:
    """How the deal history is ordered (`DealHistoryFilter(sort=...)`)."""

    field: DealHistorySortField
    direction: SortDirection = SortDirection.ASC

    def to_input(self) -> MarketDealHistorySortInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return MarketDealHistorySortInput(
            field=wire_enum(MarketDealHistorySortField, self.field),
            type_=wire_enum(SortType, self.direction),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DealHistoryFilter:
    """Conditions of a deal history search (`deals.history()`): every field is optional and the
    ones given are combined with AND. Deprecated fields of the API are not exposed; pass a raw
    `MarkerDealHistorySearchInput` to `deals.history()` for anything this class does not cover.

    Immutable: change a copy with `dataclasses.replace(filter, status=...)`. Lists given are kept
    as tuples. `price_from` / `price_to` are `Money` bounds (inclusive), `float_from` / `float_to`
    wear bounds as exact `Decimal`; `created_from` / `created_to` are aware datetimes; `pattern` is
    the paint seed; `sticker_names_by_slot` holds one name per slot, `None` for "any sticker".

    Raises `ValueError` for a price whose currency this SDK does not know or a naive datetime and
    `TypeError` for a `float` where a `Decimal` is required.
    """

    action: DealAction | None = None
    status: DealHistoryStatus | None = None
    asset_ids: Sequence[str] | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    price_from: Money | None = None
    price_to: Money | None = None
    name_hash: str | None = None
    name: str | None = None
    name_strict: bool | None = None
    float_from: Decimal | None = None
    float_to: Decimal | None = None
    phase: Phase | None = None
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
    only_for_orders: bool | None = None
    sort: DealHistorySort | None = None

    def __post_init__(self) -> None:
        normalize_filter(self, tuples=_TUPLE_FIELDS, decimals=_DECIMAL_FIELDS, dates=_DATE_FIELDS)
        for price in (self.price_from, self.price_to):
            if price is not None:
                require_sendable(price)

    def to_input(self) -> MarkerDealHistorySearchInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return MarkerDealHistorySearchInput(
            **present(
                action=wire_enum(MarketDealActionType, self.action),
                asset_ids=wire_list(self.asset_ids),
                color_enum=wire_enums(CatalogColor, self.colors),
                created_at=wire_date_range(self.created_from, self.created_to),
                csgo_charm=self.has_charm,
                csgo_collection=self.collection,
                csgo_exterior_enum=wire_enums(CSGOExterior, self.exteriors),
                csgo_float_from=wire_decimal(self.float_from),
                csgo_float_to=wire_decimal(self.float_to),
                csgo_pattern=self.pattern,
                csgo_phase_enum=wire_enum(CSGOPhase, self.phase),
                csgo_rarity_enum=wire_enums(CSGORarity, self.rarities),
                csgo_souvenir=self.souvenir,
                csgo_stat_trak=self.stat_trak,
                csgo_sticker_film=wire_enum(CSGOStickerFilm, self.sticker_film),
                csgo_sticker_names=wire_list(self.sticker_names),
                csgo_sticker_names_by_slot=wire_list(self.sticker_names_by_slot),
                csgo_sticker_names_operand=wire_enum(WireLogicOperand, self.sticker_names_operand),
                csgo_sticker_player=self.sticker_player_id,
                csgo_sticker_team=self.sticker_team_id,
                csgo_sticker_tournament=self.sticker_tournament_id,
                csgo_stickers=self.has_stickers,
                name=self.name,
                name_hash=self.name_hash,
                name_strict=self.name_strict,
                only_for_orders=self.only_for_orders,
                price=wire_money_range(self.price_from, self.price_to),
                sort=None if self.sort is None else self.sort.to_input(),
                status=wire_enum(MarketDealHistoryStatus, self.status),
            )
        )
