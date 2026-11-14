"""Centrifugo messages to protocol values and publications to live events (SDK_SPEC 4).

`decode_message` turns one raw JSON message (one WebSocket line, one SSE `data` payload) into a
protocol value; `map_publication` turns a `Publication` into a `LiveEvent`. Both are pure. A failure
is a `DecodeError` holding a path and a fixed reason, never a byte of the message (CLAUDE.md
rule 13); server text kept in values (close reasons, error messages) goes through `printable`.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, TypeVar, cast

from whitemarket._runtime.decimals import parse_decimal
from whitemarket._runtime.decode import DecodePath
from whitemarket._runtime.json_codec import decode as _decode_json
from whitemarket._runtime.wire_text import DIGITS, delivery_promise, unmapped
from whitemarket.errors.base import DecodeError
from whitemarket.live.events import (
    DealCancelled,
    DealCompleted,
    DealEvent,
    DealExchanged,
    DealExpired,
    DealHold,
    DealInitiated,
    DealNeedConfirmation,
    DealOffered,
    LiveEvent,
    ProductAdded,
    ProductEdited,
    ProductRemoved,
    UnknownEvent,
)
from whitemarket.models.enums import DealAction, DeliveryPromise, DeliveryType
from whitemarket.models.money import Money

Path = DecodePath

MAX_TEXT_BYTES = 128
# Same rule as PHP's `json_decode(depth: 64)`: a container nested 64 levels deep is refused.
_MAX_DEPTH = 64

_NON_PRINTABLE = re.compile(rb"[^\x20-\x7e]")
_BLANK_CHARS = " \t\n\r\0\x0b"
_ROOT: Path = ("live",)
_T = TypeVar("_T")


def printable(text: str, limit: int = MAX_TEXT_BYTES) -> str:
    """Server text reduced to printable ASCII, cut to `limit` bytes.

    Every UTF-8 byte outside 0x20-0x7E becomes `?` (so one non-ASCII character is two or more
    `?`), then the result is cut. The one implementation for close reasons and error messages.
    """
    data = text.encode("utf-8", "replace")
    return _NON_PRINTABLE.sub(b"?", data)[:limit].decode("ascii")


# --- protocol values ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ping:
    """The empty server message `{}`. Any message resets the idle timer; on WebSocket with
    `pong: true` the client answers with `{}`."""


@dataclass(frozen=True, slots=True)
class ReplyError:
    """The `error` of a failed command reply; `message` is printable ASCII cut to 128 bytes."""

    code: int
    message: str
    temporary: bool


@dataclass(frozen=True, slots=True)
class Reply:
    """The reply to a client command; `error` is set when the server rejected it. The payload of a
    success is not kept. A reply to `connect` is a `ConnectReply` instead."""

    id: int
    error: ReplyError | None


@dataclass(frozen=True, slots=True)
class Publication:
    """A message published to a channel; `data` is the decoded `pub.data` object."""

    channel: str
    data: dict[str, Any] = field(hash=False)


@dataclass(frozen=True, slots=True)
class Disconnect:
    """The server ends the connection; `reason` is printable ASCII cut to 128 bytes."""

    code: int
    reason: str


@dataclass(frozen=True, slots=True)
class Unsubscribe:
    """The server removed the client from `channel`; codes from 2500 allow resubscribing."""

    channel: str
    code: int


@dataclass(frozen=True, slots=True)
class ConnectReply:
    """The reply to `connect`. `ping` and `ttl` are seconds; `subs` are the channels the server
    subscribed the client to."""

    ping: int | None
    pong: bool
    ttl: int | None
    expires: bool
    subs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OtherMessage:
    """A well-formed message of a kind this SDK does not model (`join`, `leave`, `message`,
    `refresh`, keys of a newer server): ignored, never an error (CLAUDE.md rule 5)."""


ProtocolMessage = (
    Ping | Reply | Publication | Disconnect | Unsubscribe | ConnectReply | OtherMessage
)


# --- wire JSON ------------------------------------------------------------------------------------


def _too_deep(value: object) -> bool:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children: list[object] = list(cast("dict[str, object]", item).values())
        elif isinstance(item, list):
            children = list(cast("list[object]", item))
        else:
            continue
        if depth >= _MAX_DEPTH:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def _decode_wire(text: str | bytes, path: Path) -> Any:
    """The one JSON decode of the live module: floats are `Decimal`, integers exact, nesting at
    most 63 containers deep. The error holds no server bytes and no chained cause."""
    reason = None
    value: Any = None
    try:
        value = _decode_json(text)
    except RecursionError:
        reason = "nested deeper than 64 levels"
    except ValueError:  # JSONDecodeError, bad UTF-8, non-finite constant, huge int
        reason = "not valid JSON"
    if reason is None and _too_deep(value):
        reason = "nested deeper than 64 levels"
    if reason is not None:
        raise DecodeError(reason, path)
    return value


def _object(value: object, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecodeError("not an object", path)
    return cast("dict[str, Any]", value)


def _string(value: object, path: Path) -> str:
    if not isinstance(value, str):
        raise DecodeError("not a string", path)
    return value


def _int(value: object, path: Path) -> int:
    # A JSON bool is a Python int; it is not a number here.
    if not isinstance(value, int) or isinstance(value, bool):
        raise DecodeError("not an integer", path)
    return value


def _bool(value: object, path: Path) -> bool:
    if not isinstance(value, bool):
        raise DecodeError("not a boolean", path)
    return value


def _nullable(value: object, path: Path, convert: Callable[[object, Path], _T]) -> _T | None:
    return None if value is None else convert(value, path)


# --- decode_message -------------------------------------------------------------------------------


def decode_message(raw: str | bytes) -> ProtocolMessage:
    """One raw Centrifugo JSON message to a protocol value.

    Accepts the WebSocket push wrapper (`{"push": {...}}`) and the unwrapped SSE push, the connect
    reply with (`{"id": 1, "connect": {...}}`) or without an id, command replies, and the empty
    ping `{}`. A well-formed message of an unmodelled kind is an `OtherMessage`.

    Raises `DecodeError` for text that is not JSON, not an object or nested too deep, and for a
    known kind with a malformed field.
    """
    message = _object(_decode_wire(raw, _ROOT), _ROOT)
    path = _ROOT
    if "push" in message:
        path = (*path, "push")
        message = _object(message["push"], path)

    if not message:
        return Ping()
    for key, handler in _HANDLERS:  # the order is the precedence of the kinds
        if key in message:
            return handler(message, path)
    return OtherMessage()


def _disconnect(message: Mapping[str, Any], path: Path) -> Disconnect:
    path = (*path, "disconnect")
    disconnect = _object(message["disconnect"], path)
    reason = _nullable(disconnect.get("reason"), (*path, "reason"), _string)
    return Disconnect(_int(disconnect.get("code"), (*path, "code")), printable(reason or ""))


def _unsubscribe(message: Mapping[str, Any], path: Path) -> Unsubscribe:
    at = (*path, "unsubscribe")
    unsubscribe = _object(message["unsubscribe"], at)
    return Unsubscribe(
        _string(message.get("channel"), (*path, "channel")),
        _int(unsubscribe.get("code"), (*at, "code")),
    )


def _publication(message: Mapping[str, Any], path: Path) -> Publication:
    pub = _object(message["pub"], (*path, "pub"))
    data = _object(pub.get("data"), (*path, "pub", "data"))
    return Publication(_string(message.get("channel"), (*path, "channel")), data)


def _reply(message: Mapping[str, Any], path: Path) -> Reply:
    reply_id = _int(message["id"], (*path, "id"))
    if "error" not in message:
        return Reply(reply_id, None)
    at = (*path, "error")
    error = _object(message["error"], at)
    text = _nullable(error.get("message"), (*at, "message"), _string)
    temporary = error.get("temporary")
    return Reply(
        reply_id,
        ReplyError(
            _int(error.get("code"), (*at, "code")),
            printable(text or ""),
            False if temporary is None else _bool(temporary, (*at, "temporary")),
        ),
    )


def _connect_reply(message: Mapping[str, Any], path: Path) -> ConnectReply:
    path = (*path, "connect")
    connect = _object(message["connect"], path)
    subs = connect.get("subs")
    channels = _object({} if subs is None else subs, (*path, "subs"))
    pong = connect.get("pong")
    expires = connect.get("expires")
    return ConnectReply(
        ping=_nullable(connect.get("ping"), (*path, "ping"), _int),
        pong=False if pong is None else _bool(pong, (*path, "pong")),
        ttl=_nullable(connect.get("ttl"), (*path, "ttl"), _int),
        expires=False if expires is None else _bool(expires, (*path, "expires")),
        subs=tuple(channels),
    )


_HANDLERS: tuple[tuple[str, Callable[[Mapping[str, Any], Path], ProtocolMessage]], ...] = (
    ("connect", _connect_reply),
    ("id", _reply),
    ("pub", _publication),
    ("disconnect", _disconnect),
    ("unsubscribe", _unsubscribe),
)


# --- map_publication ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MappedEvent:
    """The event of a publication; `error` is set when a known type had malformed content (the
    event is then an `UnknownEvent` with the raw content)."""

    event: LiveEvent
    error: DecodeError | None = None


_ADDED = "market_product_added"
_EDITED = "market_product_edited"
_REMOVED = "market_product_removed"
_PRODUCT_KEYS = frozenset(
    (
        "id",
        "app_id",
        "asset_id",
        "class_id",
        "instance_id",
        "price",
        "name_hash",
        "inspect_url",
        "delivery_type",
        "delivery_promise",
        "float",
        "paint_index",
        "paint_seed",
        "stickers",
        "keychains",
    )
)
_REMOVED_KEYS = frozenset(
    ("id", "app_id", "asset_id", "class_id", "instance_id", "price", "name_hash")
)
_DEAL_KEYS = frozenset(("deal_id", "deal_action_type", "market_product_name", "deal_steam_id"))
_DEALS: Mapping[str, type[DealEvent]] = MappingProxyType(
    {
        "market_deal_initiated": DealInitiated,
        "market_deal_offered": DealOffered,
        "market_deal_need_confirmation": DealNeedConfirmation,
        "market_deal_exchanged": DealExchanged,
        "market_deal_completed": DealCompleted,
        "market_deal_expired": DealExpired,
        "market_deal_cancelled": DealCancelled,
        "market_deal_hold": DealHold,
    }
)


def map_publication(publication: Publication) -> MappedEvent:
    """A publication to a live event; never raises.

    `pub.data.message` is a JSON string (observed) or an already decoded object (docs); the decoded
    message is `{type, content}`. An unknown type, a channel without typed events (`broadcast`) or
    a message that is not JSON gives an `UnknownEvent`; a known type with a missing or mistyped
    field gives an `UnknownEvent` plus the `DecodeError` (path like
    `live.market_product_added.price`, never a server value).
    """
    channel = publication.channel
    message = publication.data.get("message")
    if isinstance(message, str):
        try:
            decoded = _decode_wire(message, ("live", "message"))
        except DecodeError:
            return MappedEvent(UnknownEvent(channel=channel, type=None, raw_content=message))
    else:
        decoded = publication.data if message is None else message
    if not isinstance(decoded, dict):
        raw_text: dict[str, Any] | str = message if isinstance(message, str) else publication.data
        return MappedEvent(UnknownEvent(channel=channel, type=None, raw_content=raw_text))

    obj = cast("dict[str, Any]", decoded)
    kind = obj.get("type")
    message_type = kind if isinstance(kind, str) else None
    content = obj.get("content")
    raw = cast("dict[str, Any] | list[Any]", content if isinstance(content, dict | list) else obj)
    if message_type is None or not _is_known(message_type):
        return MappedEvent(UnknownEvent(channel=channel, type=message_type, raw_content=raw))

    path: Path = ("live", message_type)
    try:
        if not isinstance(content, dict):
            raise DecodeError("content is not an object", path)
        event = _known(channel, message_type, cast("dict[str, Any]", content), path)
    except DecodeError as error:
        return MappedEvent(UnknownEvent(channel=channel, type=message_type, raw_content=raw), error)
    return MappedEvent(event)


def _is_known(message_type: str) -> bool:
    return message_type in (_ADDED, _EDITED, _REMOVED) or message_type in _DEALS


def _known(channel: str, message_type: str, c: Mapping[str, Any], path: Path) -> LiveEvent:
    if message_type in _DEALS:
        return _deal(_DEALS[message_type], channel, c, path)
    if message_type == _ADDED:
        return _added(channel, c, path)
    if message_type == _EDITED:
        return _edited(channel, c, path)
    return _removed(channel, c, path)


def _added(channel: str, c: Mapping[str, Any], path: Path) -> ProductAdded:
    return ProductAdded(
        channel=channel,
        id=_required(c, "id", path),
        app_id=_required_id(c, "app_id", path),
        asset_id=_required_id(c, "asset_id", path),
        class_id=_required_id(c, "class_id", path),
        instance_id=_required_id(c, "instance_id", path),
        price=_price(c, path),
        market_hash_name=_required(c, "name_hash", path),
        inspect_link=_optional(c, "inspect_url", path),
        delivery_type=_delivery_type(c, path),
        delivery_promise=_delivery_promise(c, path),
        float=_wear(c, path),
        paint_index=_optional(c, "paint_index", path),
        paint_seed=_optional(c, "paint_seed", path),
        stickers=_list(c, "stickers", path) or (),
        keychains=_list(c, "keychains", path) or (),
        extra=unmapped(c, _PRODUCT_KEYS),
    )


def _edited(channel: str, c: Mapping[str, Any], path: Path) -> ProductEdited:
    return ProductEdited(
        channel=channel,
        id=_required(c, "id", path),
        app_id=_optional_id(c, "app_id", path),
        asset_id=_optional_id(c, "asset_id", path),
        class_id=_optional_id(c, "class_id", path),
        instance_id=_optional_id(c, "instance_id", path),
        # A blank price in an edit is "no change", not an error.
        price=None if _optional(c, "price", path) is None else _price(c, path),
        market_hash_name=_optional(c, "name_hash", path),
        inspect_link=_optional(c, "inspect_url", path),
        delivery_type=_delivery_type(c, path),
        delivery_promise=_delivery_promise(c, path),
        float=_wear(c, path),
        paint_index=_optional(c, "paint_index", path),
        paint_seed=_optional(c, "paint_seed", path),
        stickers=_list(c, "stickers", path),
        keychains=_list(c, "keychains", path),
        extra=unmapped(c, _PRODUCT_KEYS),
    )


def _removed(channel: str, c: Mapping[str, Any], path: Path) -> ProductRemoved:
    return ProductRemoved(
        channel=channel,
        id=_required(c, "id", path),
        app_id=_required_id(c, "app_id", path),
        asset_id=_required_id(c, "asset_id", path),
        class_id=_required_id(c, "class_id", path),
        instance_id=_required_id(c, "instance_id", path),
        price=_price(c, path),
        market_hash_name=_required(c, "name_hash", path),
        extra=unmapped(c, _REMOVED_KEYS),
    )


def _deal(cls: type[DealEvent], channel: str, c: Mapping[str, Any], path: Path) -> DealEvent:
    action = _required(c, "deal_action_type", path).upper()
    return cls(
        channel=channel,
        deal_id=_required(c, "deal_id", path),
        action=DealAction(action),
        product_name=_optional(c, "market_product_name", path),
        steam_id=_optional(c, "deal_steam_id", path),
        extra=unmapped(c, _DEAL_KEYS),
    )


def _optional(c: Mapping[str, Any], key: str, path: Path) -> str | None:
    """A non-blank string; None when the key is missing, null or blank."""
    value = c.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DecodeError("not a string", (*path, key))
    return None if not value.strip(_BLANK_CHARS) else value


def _required(c: Mapping[str, Any], key: str, path: Path) -> str:
    value = _optional(c, key, path)
    if value is None:
        raise DecodeError("missing or blank", (*path, key))
    return value


def _optional_id(c: Mapping[str, Any], key: str, path: Path) -> str | None:
    """A 64-bit id as a digit string, never converted to a number."""
    value = _optional(c, key, path)
    if value is not None and DIGITS.fullmatch(value) is None:
        raise DecodeError("not an integer", (*path, key))
    return value


def _required_id(c: Mapping[str, Any], key: str, path: Path) -> str:
    value = _optional_id(c, key, path)
    if value is None:
        raise DecodeError("missing or blank", (*path, key))
    return value


def _price(c: Mapping[str, Any], path: Path) -> Money:
    return Money.usd(parse_decimal(_required(c, "price", path), (*path, "price")))


def _wear(c: Mapping[str, Any], path: Path) -> Decimal | None:
    value = _optional(c, "float", path)
    return None if value is None else parse_decimal(value, (*path, "float"))


def _delivery_type(c: Mapping[str, Any], path: Path) -> DeliveryType | None:
    value = _optional(c, "delivery_type", path)
    return None if value is None else DeliveryType(value.upper())


def _delivery_promise(c: Mapping[str, Any], path: Path) -> DeliveryPromise | None:
    value = _optional(c, "delivery_promise", path)
    return None if value is None else delivery_promise(value)


def _list(c: Mapping[str, Any], key: str, path: Path) -> tuple[dict[str, Any], ...] | None:
    """A tuple of non-empty objects; None when the key is missing or null."""
    value = c.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise DecodeError("not a list", (*path, key))
    items = cast("list[object]", value)
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item:
            raise DecodeError("not an object", (*path, key, index))
    return tuple(cast("list[dict[str, Any]]", items))
