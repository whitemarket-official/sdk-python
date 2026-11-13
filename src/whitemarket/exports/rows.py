"""Row models of the export files (SDK_SPEC 3.10 rules 5 and 8, SDK_SPEC 4)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from whitemarket.models.enums import DeliveryPromise, DeliveryType, ItemCategory
from whitemarket.models.money import Money


def _no_extra() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceRow:
    """The cheapest lot of one `(market_hash_name, paint_index)` group (one row of
    `prices/<app>.json`).

    Ids and the paint index and seed are strings (the file holds 64-bit numbers); `cheapest_float`
    is an exact decimal or None; an empty `inspect_link` is None. `extra` holds every key the SDK
    does not know, raw.
    """

    market_hash_name: str
    price: Money
    market_product_link: str
    market_product_count: int
    cheapest_asset_id: str
    cheapest_float: Decimal | None
    paint_index: str
    paint_seed: str
    inspect_link: str | None
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductRow:
    """One lot (one row of `products/<app>.json`).

    `float` is the wear value as an exact decimal or None; `category`, `delivery_type` and
    `delivery_promise` are enums whose unknown values decode to the unknown variant. `extra` holds
    every key the SDK does not know, raw.
    """

    product_id: str
    market_hash_name: str
    price: Money
    category: ItemCategory
    type: str | None
    subtype: str | None
    class_id: str
    instance_id: str
    asset_id: str
    float: Decimal | None
    paint_index: str | None
    paint_seed: str | None
    phase: str | None
    delivery_type: DeliveryType | None
    delivery_promise: DeliveryPromise | None
    inspect_link: str | None
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)
