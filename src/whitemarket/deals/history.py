"""`DealHistoryFilter` and `DealHistorySort`: conditions of `deals.history()` (SDK_SPEC 3.4)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from whitemarket._mappers.wire import (
    require_sendable,
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
