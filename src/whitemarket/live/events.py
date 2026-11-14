"""Typed live events (SDK_SPEC 4).

Live messages carry every scalar as a string, so ids are digit strings, never ints, and `price` is
USD (the messages carry no currency). A blank optional string is `None`; a blank required string is
malformed and becomes an `UnknownEvent` with a decode error. `stickers`, `keychains`, `extra` and
`UnknownEvent.raw_content` hold raw decoded server data: a frozen dataclass cannot freeze them, so
they must not be mutated (`extra` is a read-only mapping).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from whitemarket.models.enums import DealAction, DeliveryPromise, DeliveryType
from whitemarket.models.money import Money


def _no_extra() -> Mapping[str, Any]:
    return MappingProxyType({})


_Items = tuple[dict[str, Any], ...]


def _no_items() -> _Items:
    return ()


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveEvent:
    """Base of every live event; `channel` is the channel the message arrived on."""

    channel: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductAdded(LiveEvent):
    """A lot appeared on the market (`market_product_added`).

    `app_id`, `asset_id`, `class_id` and `instance_id` are digit strings (`app_id` is Steam's
    `"730"`). `price` is USD. `inspect_link`, `float`, `paint_index` and `paint_seed` are None where
    the server sends them blank (a later `ProductEdited` brings them). `stickers` and `keychains`
    are the raw decoded items as tuples (empty when absent). `extra` holds the unmapped keys of the
    message.
    """

    id: str
    app_id: str
    asset_id: str
    class_id: str
    instance_id: str
    price: Money
    market_hash_name: str
    inspect_link: str | None = None
    delivery_type: DeliveryType | None = None
    delivery_promise: DeliveryPromise | None = None
    float: Decimal | None = None
    paint_index: str | None = None
    paint_seed: str | None = None
    stickers: _Items = field(default_factory=_no_items, hash=False)
    keychains: _Items = field(default_factory=_no_items, hash=False)
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductEdited(LiveEvent):
    """A lot changed (`market_product_edited`). The message is partial: only `id` is always set.

    A field the message does not carry is None (`stickers` and `keychains` included, so "not sent"
    differs from "sent empty"). `price` is USD.
    """

    id: str
    app_id: str | None = None
    asset_id: str | None = None
    class_id: str | None = None
    instance_id: str | None = None
    price: Money | None = None
    market_hash_name: str | None = None
    inspect_link: str | None = None
    delivery_type: DeliveryType | None = None
    delivery_promise: DeliveryPromise | None = None
    float: Decimal | None = None
    paint_index: str | None = None
    paint_seed: str | None = None
    stickers: _Items | None = field(default=None, hash=False)
    keychains: _Items | None = field(default=None, hash=False)
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductRemoved(LiveEvent):
    """A lot left the market (`market_product_removed`); `price` is USD."""

    id: str
    app_id: str
    asset_id: str
    class_id: str
    instance_id: str
    price: Money
    market_hash_name: str
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class DealEvent(LiveEvent):
    """A deal on the personal channel changed (`market_deal_*`). A notification only: fetch the
    authoritative state with the deal status methods.

    `action` is the side the partner is on (an unknown value is a pseudo-member, never an error).
    `steam_id` is the counterparty's Steam id as sent: personal data, hidden from `repr`. `extra`
    holds the content keys the SDK does not map.
    """

    deal_id: str
    action: DealAction
    product_name: str | None = None
    steam_id: str | None = field(default=None, repr=False)
    extra: Mapping[str, Any] = field(default_factory=_no_extra, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class DealInitiated(DealEvent):
    """`market_deal_initiated`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealOffered(DealEvent):
    """`market_deal_offered`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealNeedConfirmation(DealEvent):
    """`market_deal_need_confirmation`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealExchanged(DealEvent):
    """`market_deal_exchanged`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCompleted(DealEvent):
    """`market_deal_completed`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealExpired(DealEvent):
    """`market_deal_expired`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCancelled(DealEvent):
    """`market_deal_cancelled`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealHold(DealEvent):
    """`market_deal_hold`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownEvent(LiveEvent):
    """A publication the SDK does not map: an unknown `type` (wallet, order, a newer one), a
    channel without typed events (`broadcast`), a message that is not JSON, or a known type whose
    content is malformed (the decode error travels beside it in `MappedEvent`).

    `type` is None when the message has none. `raw_content` is the decoded `content` (the whole
    decoded message when there is no `content` object), or the raw string when the message is not
    JSON. It is hidden from `repr`: a deal message holds the counterparty's Steam id.
    """

    type: str | None
    raw_content: dict[str, Any] | list[Any] | str = field(hash=False, repr=False)


__all__ = [
    "DealCancelled",
    "DealCompleted",
    "DealEvent",
    "DealExchanged",
    "DealExpired",
    "DealHold",
    "DealInitiated",
    "DealNeedConfirmation",
    "DealOffered",
    "LiveEvent",
    "ProductAdded",
    "ProductEdited",
    "ProductRemoved",
    "UnknownEvent",
]
