"""Mappers of the market models: `Product`, `ProductHistory`, `InventoryItem`, stickers."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast, runtime_checkable

from whitemarket._mappers.common import (
    ConnectionSource,
    MoneySource,
    Path,
    convert_enum,
    map_page,
    money,
    optional_enum,
)
from whitemarket._runtime.decimals import parse_decimal
from whitemarket.errors import DecodeError
from whitemarket.models.enums import DeliveryPromise, DeliveryType, ProductStatus, StickerFilm
from whitemarket.models.page import Page
from whitemarket.models.products import (
    InventoryItem,
    Product,
    ProductHistory,
    Sticker,
    StickerSuggestion,
    StickerSuggestions,
)


class ProductSource(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def slug(self) -> str: ...
    @property
    def price(self) -> MoneySource: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def is_owner(self) -> bool: ...
    @property
    def delivery_type(self) -> DeliveryType: ...
    @property
    def delivery_promise(self) -> DeliveryPromise: ...
    @property
    def item(self) -> object: ...


class ProductHistorySource(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def price(self) -> MoneySource: ...
    @property
    def archived_at(self) -> datetime: ...
    @property
    def delivery_type(self) -> DeliveryType: ...
    @property
    def asset_id(self) -> str: ...
    @property
    def class_id(self) -> str: ...
    @property
    def instance_id(self) -> str: ...
    @property
    def description(self) -> object: ...
    @property
    def params(self) -> object: ...


class StickerSource(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def wear(self) -> str | None: ...


@runtime_checkable
class ItemSource(Protocol):
    """The fields of `CSGOInventoryItem` this SDK reads: a type that lacks them (an item type the
    server added later, selected as `__typename` only) is not an item."""

    @property
    def id(self) -> str: ...
    @property
    def asset_id(self) -> str: ...
    @property
    def class_id(self) -> str: ...
    @property
    def instance_id(self) -> str: ...
    @property
    def name_hash(self) -> str | None: ...
    @property
    def float_(self) -> str | None: ...
    @property
    def paint_seed(self) -> str | None: ...
    @property
    def paint_index(self) -> str | None: ...
    @property
    def phase(self) -> str | None: ...
    @property
    def link(self) -> str | None: ...


@runtime_checkable
class SteamItemSource(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def is_stat_trak(self) -> bool: ...
    @property
    def is_souvenir(self) -> bool: ...


class StickerSuggestionSource(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def icon(self) -> str | None: ...
    @property
    def film(self) -> str | None: ...
    @property
    def total(self) -> int: ...


class StickerSuggestionsSource(Protocol):
    @property
    def more_count(self) -> int: ...
    @property
    def suggestions(self) -> Sequence[StickerSuggestionSource | None] | None: ...


def map_product(source: ProductSource, path: Path) -> Product:
    """A listing; an item of a type this SDK does not know maps to `item=None`."""
    return Product(
        id=source.id,
        slug=source.slug,
        price=money(source.price, (*path, "price")),
        created_at=source.created_at,
        is_owner=source.is_owner,
        delivery_type=source.delivery_type,
        delivery_promise=source.delivery_promise,
        item=map_inventory_item(source.item, None, (*path, "item")),
    )


def map_product_page(connection: ConnectionSource[ProductSource], path: Path) -> Page[Product]:
    return map_page(connection, map_product, path)


def map_product_history(source: ProductHistorySource, path: Path) -> ProductHistory:
    """An archived listing. Its item is `params`; the Steam description sits on the product."""
    return ProductHistory(
        id=source.id,
        status=convert_enum(ProductStatus, source.status),
        price=money(source.price, (*path, "price")),
        archived_at=source.archived_at,
        delivery_type=source.delivery_type,
        asset_id=source.asset_id,
        class_id=source.class_id,
        instance_id=source.instance_id,
        item=map_inventory_item(source.params, source.description, (*path, "params")),
    )


def map_batch_product(product: object, path: Path) -> Product | ProductHistory | None:
    """The product of a `*_multiple` row: a live listing, an archived one, or None.

    None for an absent product, a type this SDK does not know, and a product whose values cannot
    be read (a malformed amount): the outcome the server reported for the row stands either way.
    """
    kind: object = getattr(product, "typename__", None)
    try:
        if kind == "MarketProduct":
            return map_product(cast("ProductSource", product), path)
        if kind == "MarketProductHistory":
            return map_product_history(cast("ProductHistorySource", product), path)
    except DecodeError:
        return None
    return None


def map_inventory_item(item: object, description: object, path: Path) -> InventoryItem | None:
    """None when `item` is not a CS2 inventory item (null, or a type this SDK does not know).

    The Steam description is the item's own when its selection has a known one, otherwise
    `description` (a product history describes its item on the product); stickers come only from
    the item's own selection.
    """
    if not isinstance(item, ItemSource):
        return None
    own: object = getattr(item, "description", None)
    steam = own if isinstance(own, SteamItemSource) else None
    if steam is None and isinstance(description, SteamItemSource):
        steam = description
    wear = item.float_
    return InventoryItem(
        id=item.id,
        asset_id=item.asset_id,
        class_id=item.class_id,
        instance_id=item.instance_id,
        name_hash=item.name_hash,
        name=None if steam is None else steam.name,
        float=None if wear is None else parse_decimal(wear, (*path, "float")),
        paint_seed=item.paint_seed,
        paint_index=item.paint_index,
        phase=item.phase,
        inspect_link=item.link,
        is_stat_trak=None if steam is None else steam.is_stat_trak,
        is_souvenir=None if steam is None else steam.is_souvenir,
        stickers=_stickers(getattr(item, "stickers", None) or (), (*path, "stickers")),
    )


def _stickers(stickers: Sequence[StickerSource | None], path: Path) -> tuple[Sticker, ...]:
    """A null entry carries no sticker and is skipped (the schema allows it)."""
    mapped: list[Sticker] = []
    for index, sticker in enumerate(stickers):
        if sticker is not None:
            wear = sticker.wear
            mapped.append(
                Sticker(
                    name=sticker.name,
                    title=sticker.title,
                    wear=None if wear is None else parse_decimal(wear, (*path, index, "wear")),
                )
            )
    return tuple(mapped)


def map_sticker_suggestions(source: StickerSuggestionsSource) -> StickerSuggestions:
    return StickerSuggestions(
        items=tuple(
            StickerSuggestion(
                name=s.name,
                title=s.title,
                icon=s.icon,
                film=optional_enum(StickerFilm, s.film),
                total=s.total,
            )
            for s in source.suggestions or ()
            if s is not None
        ),
        more_count=source.more_count,
    )
