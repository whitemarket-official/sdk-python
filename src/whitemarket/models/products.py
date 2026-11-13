"""Models of the market: `Product`, `ProductHistory`, `InventoryItem`, sticker suggestions
(SDK_SPEC 3.2, 4)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from whitemarket.models.enums import DeliveryPromise, DeliveryType, ProductStatus, StickerFilm
from whitemarket.models.money import Money


@dataclass(frozen=True, slots=True, kw_only=True)
class Sticker:
    """A sticker applied to an item. `wear` is the scrape level as an exact decimal, or None when
    the server does not report it."""

    name: str
    title: str
    wear: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class InventoryItem:
    """A CS2 item: in an inventory, behind a listing or in a deal.

    Steam ids (`asset_id`, `class_id`, `instance_id`) are 64-bit numbers kept as strings (CLAUDE.md
    rule 3). `float` is the wear value as an exact decimal (pattern hunters compare many digits).
    `name`, `is_stat_trak` and `is_souvenir` come from the item's Steam description and are None
    when the server sends none. `inspect_link` is the Steam inspect link.
    """

    id: str
    asset_id: str
    class_id: str
    instance_id: str
    name_hash: str | None
    name: str | None
    float: Decimal | None
    paint_seed: str | None
    paint_index: str | None
    phase: str | None
    inspect_link: str | None
    is_stat_trak: bool | None
    is_souvenir: bool | None
    stickers: tuple[Sticker, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Product:
    """A listing on the market (SDK_SPEC 3.2).

    `slug` is the listing's id in market URLs; `market.get()` accepts it as well as `id`.
    `is_owner` is true when the listing belongs to the authenticated account. `item` is None when
    the server sends an item type this SDK version does not know.
    """

    id: str
    slug: str
    price: Money
    created_at: datetime
    is_owner: bool
    delivery_type: DeliveryType
    delivery_promise: DeliveryPromise
    item: InventoryItem | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductHistory:
    """A listing that left the market: sold (the product of a deal), removed or expired.

    `item` is None when the server sends an item type this SDK version does not know.
    """

    id: str
    status: ProductStatus
    price: Money
    archived_at: datetime
    delivery_type: DeliveryType
    asset_id: str
    class_id: str
    instance_id: str
    item: InventoryItem | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StickerSuggestion:
    """A sticker name that matches a search text. `name` is the value for
    `ProductFilter(sticker_names=...)`; `icon` is an icon URL when the server has one; `total` is
    how many listings carry the sticker."""

    name: str
    title: str
    icon: str | None
    film: StickerFilm | None
    total: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StickerSuggestions:
    """The answer of `market.sticker_suggestions()`: one window of matching stickers and how many
    more there are (`more_count`, beyond this window)."""

    items: tuple[StickerSuggestion, ...]
    more_count: int
