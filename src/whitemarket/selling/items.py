"""The inputs of `list_many` / `reprice_many` (SDK_SPEC 3.5 rule 1): an item or a listing is named
by a UUID or a Steam asset id (see `_references.py`); anything else is refused before any request.
"""

from dataclasses import dataclass

from whitemarket._mappers.wire import require_sendable
from whitemarket.models.money import Money
from whitemarket.selling._references import inventory_or_asset, product_or_asset


@dataclass(frozen=True, slots=True)
class Listing:
    """One item to put on sale in `selling.list_many()`.

    `item` is an inventory id (UUID) or a 64-bit Steam asset id (digits, kept as a string).
    Raises `ValueError` for anything else or a price in a currency this SDK cannot send.
    """

    item: str
    price: Money

    def __post_init__(self) -> None:
        inventory_or_asset(self.item)
        require_sendable(self.price)


@dataclass(frozen=True, slots=True)
class PriceChange:
    """One new price in `selling.reprice_many()`.

    `product` is a listing id (UUID) or the 64-bit Steam asset id (digits) of a listed item.
    Raises `ValueError` for anything else or a price in a currency this SDK cannot send.
    """

    product: str
    price: Money

    def __post_init__(self) -> None:
        product_or_asset(self.product)
        require_sendable(self.price)
