"""`map_publication`: live messages to events (ports the PHP EventMapper cases)."""

import copy
import json
from decimal import Decimal
from typing import Any

import pytest

from whitemarket.errors.base import DecodeError
from whitemarket.live._envelope import MappedEvent, Publication, decode_message, map_publication
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
    ProductAdded,
    ProductEdited,
    ProductRemoved,
    UnknownEvent,
)
from whitemarket.models.enums import DealAction, DeliveryPromise, DeliveryType
from whitemarket.models.money import Money

PRODUCTS = "market_products_updates"
PERSONAL = "#42"
ADDED = "market_product_added"
EDITED = "market_product_edited"
REMOVED = "market_product_removed"

ADDED_CONTENT: dict[str, Any] = {
    "id": "11111111-1111-4111-8111-111111111111",
    "app_id": "730",
    "asset_id": "7000000001",
    "class_id": "7000000002",
    "instance_id": "0",
    "price": "2.100",
    "name_hash": "AK-47 | Test (Field-Tested)",
    "inspect_url": "steam://run/730//+csgo_econ_action_preview%20SYNTHETIC",
    "delivery_type": "semi",
    "delivery_promise": "10min",
    "float": "0.152345",
    "paint_index": "282",
    "paint_seed": "661",
    "stickers": [{"slot": 0, "name": "Sticker | Test", "wear": "0.1"}],
    "keychains": [{"slot": 0, "name": "Charm | Test", "pattern": "42"}],
}
EDITED_PARTIAL: dict[str, Any] = {"id": "11111111-1111-4111-8111-111111111111", "price": "2.10"}
REMOVED_CONTENT: dict[str, Any] = {
    key: ADDED_CONTENT[key]
    for key in ("id", "app_id", "asset_id", "class_id", "instance_id", "price", "name_hash")
}
DEAL_CONTENT: dict[str, Any] = {
    "deal_id": "22222222-2222-4222-8222-222222222222",
    "deal_action_type": "buy",
    "market_product_name": "AK-47 | Test (Field-Tested)",
    "deal_steam_id": "SYNTHETIC-STEAM-ID",
}
BASE: dict[str, dict[str, Any]] = {
    ADDED: ADDED_CONTENT,
    EDITED: EDITED_PARTIAL,
    REMOVED: REMOVED_CONTENT,
    "market_deal_completed": DEAL_CONTENT,
}


def message(kind: str, **overrides: Any) -> dict[str, Any]:
    """`{type, content}` of a base sample; an override of `...` drops the key."""
    content = copy.deepcopy(BASE[kind])
    for key, value in overrides.items():
        if value is ...:
            content.pop(key, None)
        else:
            content[key] = value
    return {"type": kind, "content": content}


def publication(msg: Any, channel: str = PRODUCTS) -> Publication:
    """A publication whose `message` is the JSON string of `msg`, as the server sends it."""
    return Publication(channel=channel, data={"message": json.dumps(msg)})


def mapped(msg: Any, channel: str = PRODUCTS) -> MappedEvent:
    return map_publication(publication(msg, channel))


def product_added(result: MappedEvent) -> ProductAdded:
    assert result.error is None
    assert isinstance(result.event, ProductAdded)
    return result.event


def test_product_added_from_the_wire_envelope() -> None:
    raw = json.dumps(
        {"channel": PRODUCTS, "pub": {"data": {"message": json.dumps(message(ADDED))}}}
    )
    envelope = decode_message(raw)
    assert isinstance(envelope, Publication)

    event = product_added(map_publication(envelope))

    assert event.channel == PRODUCTS
    assert event.id == "11111111-1111-4111-8111-111111111111"
    assert (event.app_id, event.asset_id, event.class_id, event.instance_id) == (
        "730",
        "7000000001",
        "7000000002",
        "0",
    )
    assert event.price == Money.usd("2.100")
    assert str(event.price.amount) == "2.100"
    assert event.market_hash_name == "AK-47 | Test (Field-Tested)"
    assert event.inspect_link == "steam://run/730//+csgo_econ_action_preview%20SYNTHETIC"
    assert event.delivery_type is DeliveryType.SEMI
    assert event.delivery_promise is DeliveryPromise.MINUTES10
    assert event.float == Decimal("0.152345")
    assert (event.paint_index, event.paint_seed) == ("282", "661")
    assert event.stickers == ({"slot": 0, "name": "Sticker | Test", "wear": "0.1"},)
    assert event.keychains == ({"slot": 0, "name": "Charm | Test", "pattern": "42"},)
    assert dict(event.extra) == {}


def test_string_and_object_message_map_to_the_same_event() -> None:
    from_string = map_publication(publication(message(ADDED)))
    from_object = map_publication(Publication(PRODUCTS, {"message": message(ADDED)}))

    assert from_string == from_object
    assert isinstance(from_object.event, ProductAdded)


def test_unmapped_keys_are_kept_in_extra() -> None:
    event = product_added(mapped(message(ADDED, new_field={"a": 1}, rarity="rare")))

    assert dict(event.extra) == {"new_field": {"a": 1}, "rarity": "rare"}


def test_extra_is_read_only() -> None:
    event = product_added(mapped(message(ADDED, new_field=1)))

    mutate: Any = event.extra
    with pytest.raises(TypeError):
        mutate["x"] = 1


@pytest.mark.parametrize(
    "ids",
    [
        pytest.param(
            {
                "asset_id": "18446744073709551615",
                "class_id": "9223372036854775808",
                "instance_id": "9007199254740993",
            },
            id="beyond 2**63 and 2**53",
        ),
        pytest.param(
            {"asset_id": "00012", "class_id": "0", "instance_id": "0"}, id="leading zeros"
        ),
    ],
)
def test_ids_stay_exact_digit_strings(ids: dict[str, str]) -> None:
    event = product_added(mapped(message(ADDED, **ids)))

    assert (event.asset_id, event.class_id, event.instance_id) == (
        ids["asset_id"],
        ids["class_id"],
        ids["instance_id"],
    )
    assert all(isinstance(v, str) for v in (event.asset_id, event.class_id, event.instance_id))


def test_ids_survive_the_wire_decode_as_strings() -> None:
    text = json.dumps(message(ADDED, asset_id="18446744073709551615"))
    envelope = decode_message(
        json.dumps({"channel": PRODUCTS, "pub": {"data": {"message": json.loads(text)}}})
    )
    assert isinstance(envelope, Publication)

    assert product_added(map_publication(envelope)).asset_id == "18446744073709551615"


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        pytest.param("0.020", "0.020", id="trailing zero kept"),
        pytest.param("2", "2", id="integer"),
        pytest.param(
            "0.1000000000000000055511151231257827",
            "0.1000000000000000055511151231257827",
            id="more digits than a float holds",
        ),
    ],
)
def test_price_is_an_exact_usd_decimal(amount: str, text: str) -> None:
    event = product_added(mapped(message(ADDED, price=amount)))

    assert str(event.price.amount) == text
    assert event.price.currency.value == "USD"


def test_blank_optionals_and_missing_lists_are_none_and_empty() -> None:
    blank = {
        "inspect_url": "",
        "float": "",
        "paint_index": "",
        "paint_seed": " ",
        "delivery_type": "",
        "delivery_promise": "",
        "stickers": ...,
        "keychains": ...,
    }

    event = product_added(mapped(message(ADDED, **blank)))

    assert (event.inspect_link, event.float, event.paint_index, event.paint_seed) == (None,) * 4
    assert (event.delivery_type, event.delivery_promise) == (None, None)
    assert (event.stickers, event.keychains) == ((), ())


def test_missing_optional_keys_are_none() -> None:
    drop = dict.fromkeys(
        ("inspect_url", "float", "paint_index", "paint_seed", "delivery_type", "delivery_promise"),
        ...,
    )

    event = product_added(mapped(message(ADDED, **drop)))

    assert event.delivery_type is None
    assert event.float is None


@pytest.mark.parametrize(
    ("key", "wire", "expected", "unknown"),
    [
        pytest.param("delivery_type", "auto", "AUTO", False, id="type auto"),
        pytest.param("delivery_type", "semi", "SEMI", False, id="type semi"),
        pytest.param("delivery_type", "manual", "MANUAL", False, id="type manual"),
        pytest.param("delivery_type", "SEMI", "SEMI", False, id="type upper case"),
        pytest.param("delivery_type", "drone", "DRONE", True, id="type unknown, upper-cased"),
        pytest.param("delivery_promise", "10min", "MINUTES10", False, id="promise 10min"),
        pytest.param("delivery_promise", "1hour", "HOUR1", False, id="promise 1hour"),
        pytest.param("delivery_promise", "12hours", "HOURS12", False, id="promise 12hours"),
        pytest.param("delivery_promise", "24hours", "HOURS24", False, id="promise 24hours"),
        pytest.param("delivery_promise", "3days", "3days", True, id="promise unknown, raw value"),
        # Same as the export mapper: an unlisted wire value is looked up as the schema value.
        pytest.param("delivery_promise", "MINUTES10", "MINUTES10", False, id="promise enum name"),
    ],
)
def test_delivery_values(key: str, wire: str, expected: str, unknown: bool) -> None:
    event = product_added(mapped(message(ADDED, **{key: wire})))

    value = event.delivery_type if key == "delivery_type" else event.delivery_promise
    assert value is not None
    assert value.value == expected
    assert value.is_unknown is unknown
    if key == "delivery_promise" and not unknown:
        assert value in set(DeliveryPromise)


def test_partial_product_edited() -> None:
    result = mapped(message(EDITED))

    assert result.error is None
    event = result.event
    assert isinstance(event, ProductEdited)
    assert event.id == "11111111-1111-4111-8111-111111111111"
    assert event.price == Money.usd("2.10")
    assert str(event.price.amount) == "2.10"
    assert (event.app_id, event.asset_id, event.class_id, event.instance_id) == (None,) * 4
    assert (event.market_hash_name, event.inspect_link, event.float) == (None,) * 3
    assert (event.delivery_type, event.delivery_promise) == (None, None)
    assert (event.paint_index, event.paint_seed) == (None, None)
    assert (event.stickers, event.keychains) == (None, None)
    assert dict(event.extra) == {}


def test_full_product_edited() -> None:
    full = {
        "type": EDITED,
        "content": {**ADDED_CONTENT, "price": "2.050", "delivery_promise": "1hour"},
    }

    event = mapped(full).event

    assert isinstance(event, ProductEdited)
    assert event.price == Money.usd("2.050")
    assert event.delivery_promise is DeliveryPromise.HOUR1
    assert (event.app_id, event.asset_id, event.class_id, event.instance_id) == (
        "730",
        "7000000001",
        "7000000002",
        "0",
    )
    assert event.stickers is not None
    assert len(event.stickers) == 1


def test_edited_stickers_sent_empty_differ_from_not_sent() -> None:
    event = mapped(message(EDITED, stickers=[])).event

    assert isinstance(event, ProductEdited)
    assert event.stickers == ()
    assert event.keychains is None


def test_blank_price_in_an_edit_is_not_a_change() -> None:
    result = mapped(message(EDITED, price=""))

    assert result.error is None
    assert isinstance(result.event, ProductEdited)
    assert result.event.price is None


def test_product_removed() -> None:
    result = mapped(message(REMOVED))

    assert result.error is None
    event = result.event
    assert isinstance(event, ProductRemoved)
    assert event.id == "11111111-1111-4111-8111-111111111111"
    assert (event.app_id, event.asset_id, event.class_id, event.instance_id) == (
        "730",
        "7000000001",
        "7000000002",
        "0",
    )
    assert event.price == Money.usd("2.100")
    assert event.market_hash_name == "AK-47 | Test (Field-Tested)"
    assert dict(event.extra) == {}


def test_removed_keeps_unmapped_keys_in_extra() -> None:
    event = mapped(message(REMOVED, inspect_url="x")).event

    assert isinstance(event, ProductRemoved)
    assert dict(event.extra) == {"inspect_url": "x"}


@pytest.mark.parametrize(
    ("kind", "cls"),
    [
        pytest.param("market_deal_initiated", DealInitiated, id="initiated"),
        pytest.param("market_deal_offered", DealOffered, id="offered"),
        pytest.param("market_deal_need_confirmation", DealNeedConfirmation, id="need_confirmation"),
        pytest.param("market_deal_exchanged", DealExchanged, id="exchanged"),
        pytest.param("market_deal_completed", DealCompleted, id="completed"),
        pytest.param("market_deal_expired", DealExpired, id="expired"),
        pytest.param("market_deal_cancelled", DealCancelled, id="cancelled"),
        pytest.param("market_deal_hold", DealHold, id="hold"),
    ],
)
def test_each_deal_type_maps_to_its_class(kind: str, cls: type[DealEvent]) -> None:
    result = mapped({"type": kind, "content": DEAL_CONTENT}, PERSONAL)

    assert result.error is None
    event = result.event
    assert type(event) is cls
    assert isinstance(event, DealEvent)
    assert event.channel == PERSONAL
    assert event.deal_id == "22222222-2222-4222-8222-222222222222"
    assert event.action is DealAction.BUY
    assert event.product_name == "AK-47 | Test (Field-Tested)"
    assert event.steam_id == "SYNTHETIC-STEAM-ID"
    assert dict(event.extra) == {}
    assert "SYNTHETIC-STEAM-ID" not in repr(event)


@pytest.mark.parametrize(
    ("wire", "expected", "unknown"),
    [
        pytest.param("buy", "BUY", False, id="buy"),
        pytest.param("sell", "SELL", False, id="sell"),
        pytest.param("SELL", "SELL", False, id="upper case"),
        pytest.param("swap", "SWAP", True, id="unknown is tolerated and upper-cased"),
    ],
)
def test_deal_action(wire: str, expected: str, unknown: bool) -> None:
    event = mapped(message("market_deal_completed", deal_action_type=wire), PERSONAL).event

    assert isinstance(event, DealCompleted)
    assert event.action == expected
    assert event.action.is_unknown is unknown


def test_deal_without_optionals_has_nones_and_keeps_extra() -> None:
    msg = message("market_deal_completed", market_product_name="", deal_steam_id=..., extra_key=7)

    result = mapped(msg, PERSONAL)

    assert result.error is None
    assert isinstance(result.event, DealCompleted)
    assert result.event.product_name is None
    assert result.event.steam_id is None
    assert dict(result.event.extra) == {"extra_key": 7}


def _malformed_cases() -> list[Any]:
    cases: list[Any] = []

    def add(label: str, kind: str, overrides: dict[str, Any], path: tuple[str | int, ...]) -> None:
        cases.append(pytest.param(kind, overrides, ("live", kind, *path), id=label))

    required = ("id", "app_id", "asset_id", "class_id", "instance_id", "price", "name_hash")
    for key in required:
        add(f"added: {key} missing", ADDED, {key: ...}, (key,))
        add(f"added: {key} blank", ADDED, {key: " "}, (key,))
        add(f"added: {key} a number", ADDED, {key: 5}, (key,))
        add(f"added: {key} null", ADDED, {key: None}, (key,))
    for key in ("app_id", "asset_id", "class_id", "instance_id"):
        add(f"added: {key} not digits", ADDED, {key: "12ab"}, (key,))
        add(f"added: {key} negative", ADDED, {key: "-5"}, (key,))
        add(f"added: {key} unicode digits", ADDED, {key: "١٢"}, (key,))
    add("added: price with an exponent", ADDED, {"price": "2e1"}, ("price",))
    add("added: price not a number", ADDED, {"price": "free"}, ("price",))
    add("added: price with a comma", ADDED, {"price": "1,5"}, ("price",))
    add("added: price NaN", ADDED, {"price": "NaN"}, ("price",))
    add("added: float not a number", ADDED, {"float": "NaN"}, ("float",))
    add("added: float a JSON number", ADDED, {"float": 0.15}, ("float",))
    add("added: inspect_url a number", ADDED, {"inspect_url": 1}, ("inspect_url",))
    add("added: delivery_type an object", ADDED, {"delivery_type": ["x"]}, ("delivery_type",))
    add("added: paint_seed a number", ADDED, {"paint_seed": 661}, ("paint_seed",))
    add("added: stickers an object", ADDED, {"stickers": {"a": 1}}, ("stickers",))
    add("added: stickers a string", ADDED, {"stickers": "none"}, ("stickers",))
    add("added: a sticker a string", ADDED, {"stickers": ["x"]}, ("stickers", 0))
    add("added: second sticker empty", ADDED, {"stickers": [{"a": 1}, {}]}, ("stickers", 1))
    add("added: a keychain a list", ADDED, {"keychains": [[1]]}, ("keychains", 0))

    add("edited: id missing", EDITED, {"id": ...}, ("id",))
    add("edited: id blank", EDITED, {"id": ""}, ("id",))
    add("edited: id a number", EDITED, {"id": 7}, ("id",))
    add("edited: price not a number", EDITED, {"price": "x"}, ("price",))
    add("edited: price a number", EDITED, {"price": 2.1}, ("price",))
    add("edited: asset_id not digits", EDITED, {"asset_id": "abc"}, ("asset_id",))
    add("edited: stickers not a list", EDITED, {"stickers": "x"}, ("stickers",))

    for key in required:
        add(f"removed: {key} missing", REMOVED, {key: ...}, (key,))
    add("removed: price not a number", REMOVED, {"price": "1,5"}, ("price",))
    add("removed: class_id not digits", REMOVED, {"class_id": "1.5"}, ("class_id",))

    deal = "market_deal_completed"
    for key in ("deal_id", "deal_action_type"):
        add(f"deal: {key} missing", deal, {key: ...}, (key,))
        add(f"deal: {key} blank", deal, {key: ""}, (key,))
        add(f"deal: {key} a number", deal, {key: 5}, (key,))
    add("deal: product name a number", deal, {"market_product_name": 5}, ("market_product_name",))
    add("deal: steam id a number", deal, {"deal_steam_id": 5}, ("deal_steam_id",))
    return cases


@pytest.mark.parametrize(("kind", "overrides", "path"), _malformed_cases())
def test_malformed_known_type_is_unknown_event_with_decode_error(
    kind: str, overrides: dict[str, Any], path: tuple[str | int, ...]
) -> None:
    msg = message(kind, **overrides)

    result = mapped(msg)

    assert isinstance(result.error, DecodeError)
    assert result.error.path == path
    assert isinstance(result.event, UnknownEvent)
    assert result.event.type == kind
    assert result.event.raw_content == json.loads(json.dumps(msg["content"]), parse_float=Decimal)
    assert result.event.channel == PRODUCTS


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(..., id="content missing"),
        pytest.param("text", id="content a string"),
        pytest.param([1, 2], id="content a list"),
        pytest.param(5, id="content a number"),
        pytest.param(None, id="content null"),
    ],
)
def test_known_type_without_a_content_object_is_malformed(content: Any) -> None:
    msg: dict[str, Any] = {"type": REMOVED}
    if content is not ...:
        msg["content"] = content

    result = mapped(msg)

    assert isinstance(result.error, DecodeError)
    assert result.error.path == ("live", REMOVED)
    assert isinstance(result.event, UnknownEvent)


@pytest.mark.parametrize(
    "overrides",
    [{"price": "SERVER-PRICE-MARK"}, {"asset_id": "SERVER-ID-MARK"}, {"stickers": "SERVER-MARK"}],
)
def test_decode_error_never_holds_server_values(overrides: dict[str, Any]) -> None:
    result = mapped(message(ADDED, **overrides))

    assert result.error is not None
    assert "MARK" not in str(result.error)
    assert "MARK" not in repr(result.error.args)
    assert "MARK" not in result.error.reason
    assert all("MARK" not in str(part) for part in result.error.path)


def test_unknown_type_is_an_unknown_event_without_error() -> None:
    content = {"balance": "10.00", "currency": "USD"}

    result = mapped({"type": "wallet_balance_updated", "content": content}, PERSONAL)

    assert result == MappedEvent(
        UnknownEvent(channel=PERSONAL, type="wallet_balance_updated", raw_content=content)
    )


@pytest.mark.parametrize(
    ("msg", "type_", "raw"),
    [
        pytest.param(
            {"type": "x_new"},
            "x_new",
            {"type": "x_new"},
            id="type without content keeps the message",
        ),
        pytest.param(
            {"type": "x_new", "content": "hi"},
            "x_new",
            {"type": "x_new", "content": "hi"},
            id="content a string",
        ),
        pytest.param({"type": "x_new", "content": [1]}, "x_new", [1], id="content a list"),
        pytest.param({"content": {"a": 1}}, None, {"a": 1}, id="no type"),
        pytest.param({"type": 5, "content": {"a": 1}}, None, {"a": 1}, id="type a number"),
        pytest.param({}, None, {}, id="empty object"),
    ],
)
def test_shapes_without_a_known_type_are_unknown_events(
    msg: Any, type_: str | None, raw: Any
) -> None:
    result = mapped(msg, "broadcast")

    assert result == MappedEvent(UnknownEvent(channel="broadcast", type=type_, raw_content=raw))


def test_known_type_on_broadcast_is_still_mapped_by_type() -> None:
    event = mapped(message(REMOVED), "broadcast").event

    assert isinstance(event, ProductRemoved)
    assert event.channel == "broadcast"


@pytest.mark.parametrize(
    ("data", "raw"),
    [
        pytest.param({"message": "maintenance at noon"}, "maintenance at noon", id="plain text"),
        pytest.param(
            {"message": '{"type":"market_product_added"'},
            '{"type":"market_product_added"',
            id="truncated JSON",
        ),
        pytest.param({"message": "5"}, "5", id="JSON scalar"),
        pytest.param({"message": "null"}, "null", id="JSON null string"),
        pytest.param({"message": "[1]"}, "[1]", id="JSON list string"),
        pytest.param({"message": ""}, "", id="empty string"),
        pytest.param({"text": "hi"}, {"text": "hi"}, id="no message key: the data is the message"),
        pytest.param({"message": 5}, {"message": 5}, id="message a number"),
        pytest.param({"message": [1, 2]}, {"message": [1, 2]}, id="message a list"),
        pytest.param({"message": True}, {"message": True}, id="message a bool"),
    ],
)
def test_publication_without_a_message_object_is_an_unknown_event(
    data: dict[str, Any], raw: Any
) -> None:
    result = map_publication(Publication("broadcast", data))

    assert result == MappedEvent(UnknownEvent(channel="broadcast", type=None, raw_content=raw))


def test_null_message_falls_back_to_the_data_object() -> None:
    result = map_publication(Publication(PRODUCTS, {"message": None, "type": "x_new"}))

    assert isinstance(result.event, UnknownEvent)
    assert result.event.type == "x_new"
    assert result.error is None


def test_data_object_can_itself_be_the_typed_message() -> None:
    result = map_publication(Publication(PRODUCTS, message(REMOVED)))

    assert isinstance(result.event, ProductRemoved)


def test_message_nested_beyond_the_limit_is_an_unknown_event_with_the_raw_string() -> None:
    deep = '{"type":"x","content":' + "[" * 70 + "]" * 70 + "}"

    result = map_publication(Publication(PRODUCTS, {"message": deep}))

    assert result == MappedEvent(UnknownEvent(channel=PRODUCTS, type=None, raw_content=deep))


def test_message_string_with_floats_maps_prices_exactly() -> None:
    raw = '{"type":"market_product_removed","content":' + json.dumps(REMOVED_CONTENT) + "}"

    event = map_publication(Publication(PRODUCTS, {"message": raw})).event

    assert isinstance(event, ProductRemoved)
    assert str(event.price.amount) == "2.100"


def test_map_publication_never_raises_on_hostile_shapes() -> None:
    shapes: list[Any] = [
        {"message": json.dumps({"type": ADDED, "content": {"id": "x" * 10_000}})},
        {"message": json.dumps({"type": ADDED, "content": {**ADDED_CONTENT, "price": "9" * 5000}})},
        {
            "message": json.dumps(
                {"type": "market_deal_hold", "content": {"deal_id": "d", "deal_action_type": "ß"}}
            )
        },
        {"message": "\ud800"},
        {},
    ]

    for data in shapes:
        assert isinstance(map_publication(Publication(PERSONAL, data)), MappedEvent)


def test_an_unknown_deal_action_is_a_pseudo_member_not_an_error() -> None:
    content = {**DEAL_CONTENT, "deal_action_type": "teleport"}

    result = mapped({"type": "market_deal_offered", "content": content}, PERSONAL)

    assert result.error is None
    assert isinstance(result.event, DealEvent)
    assert result.event.action.value == "TELEPORT"
    assert result.event.action.is_unknown


def test_the_unknown_event_repr_does_not_show_the_raw_content() -> None:
    content = {**DEAL_CONTENT, "deal_action_type": 5}  # malformed: becomes an UnknownEvent

    result = mapped({"type": "market_deal_offered", "content": content}, PERSONAL)

    assert isinstance(result.event, UnknownEvent)
    assert result.error is not None
    assert "SYNTHETIC-STEAM-ID" not in repr(result.event)
