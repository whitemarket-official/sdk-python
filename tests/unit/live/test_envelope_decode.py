"""`decode_message` and `printable` (WHITEMARKET_API.md 9; ports the PHP MessageDecoder cases)."""

import json
from decimal import Decimal

import pytest

from whitemarket.errors.base import DecodeError
from whitemarket.live._envelope import (
    ConnectReply,
    Disconnect,
    OtherMessage,
    Ping,
    Publication,
    Reply,
    ReplyError,
    Unsubscribe,
    decode_message,
    printable,
)

_MESSAGE = json.dumps(
    {
        "type": "market_product_added",
        "content": {"id": "p-1", "price": "2.100"},
    }
)
SSE_PUBLICATION = json.dumps(
    {"channel": "market_products_updates", "pub": {"data": {"message": _MESSAGE}}}
)
WS_PUBLICATION = json.dumps({"push": json.loads(SSE_PUBLICATION)})
WS_OBJECT_PUBLICATION = json.dumps(
    {
        "push": {
            "channel": "market_products_updates",
            "pub": {"data": {"message": json.loads(_MESSAGE)}},
        }
    }
)
SSE_CONNECT = (
    '{"connect":{"client":"00000000-0000-4000-8000-000000000000","version":"6.7.2 OSS",'
    '"subs":{"broadcast":{},"#42":{},"market_products_updates":{}},'
    '"expires":true,"ttl":86400,"ping":25,"session":"synthetic-session"}}'
)
WS_CONNECT = (
    '{"id":1,"connect":{"client":"00000000-0000-4000-8000-000000000000","version":"6.7.2 OSS",'
    '"expires":true,"ttl":86400,"subs":{"broadcast":{},"#42":{}},"ping":25,"pong":true}}'
)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("{}", id="empty object"),
        pytest.param(" {} \n", id="surrounding whitespace"),
        pytest.param('{"push":{}}', id="empty push"),
        pytest.param(b"{}", id="bytes"),
    ],
)
def test_empty_object_is_a_ping(raw: str | bytes) -> None:
    assert decode_message(raw) == Ping()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(SSE_PUBLICATION, id="SSE unwrapped"),
        pytest.param(WS_PUBLICATION, id="WS push-wrapped"),
        pytest.param(SSE_PUBLICATION.encode(), id="bytes"),
    ],
)
def test_publication_from_both_transports(raw: str | bytes) -> None:
    publication = decode_message(raw)

    assert isinstance(publication, Publication)
    assert publication.channel == "market_products_updates"
    assert publication.data == {"message": _MESSAGE}


def test_object_message_stays_a_dict() -> None:
    publication = decode_message(WS_OBJECT_PUBLICATION)

    assert isinstance(publication, Publication)
    assert publication.data["message"]["type"] == "market_product_added"


def test_ints_stay_exact_and_floats_become_decimal() -> None:
    raw = (
        '{"channel":"c","pub":{"data":'
        '{"n":9223372036854775808,"m":18446744073709551615,"f":0.020}}}'
    )

    publication = decode_message(raw)

    assert isinstance(publication, Publication)
    assert publication.data["n"] == 2**63
    assert publication.data["m"] == 2**64 - 1
    assert publication.data["f"] == Decimal("0.020")
    assert str(publication.data["f"]) == "0.020"
    assert isinstance(publication.data["n"], int)


@pytest.mark.parametrize(
    ("raw", "ping", "pong", "subs"),
    [
        pytest.param(
            SSE_CONNECT, 25, False, ("broadcast", "#42", "market_products_updates"), id="SSE"
        ),
        pytest.param(WS_CONNECT, 25, True, ("broadcast", "#42"), id="WS with the command id"),
    ],
)
def test_connect_reply_of_both_transports(
    raw: str, ping: int, pong: bool, subs: tuple[str, ...]
) -> None:
    reply = decode_message(raw)

    assert reply == ConnectReply(ping=ping, pong=pong, ttl=86400, expires=True, subs=subs)


def test_minimal_connect_reply_has_defaults() -> None:
    assert decode_message('{"connect":{}}') == ConnectReply(
        ping=None, pong=False, ttl=None, expires=False, subs=()
    )


def test_null_connect_fields_take_the_defaults() -> None:
    raw = '{"connect":{"ping":null,"pong":null,"ttl":null,"expires":null,"subs":null}}'

    assert decode_message(raw) == ConnectReply(
        ping=None, pong=False, ttl=None, expires=False, subs=()
    )


def test_numeric_channel_name_stays_a_string() -> None:
    reply = decode_message('{"connect":{"subs":{"123":{}}}}')

    assert isinstance(reply, ConnectReply)
    assert reply.subs == ("123",)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param('{"id":2,"subscribe":{}}', Reply(2, None), id="subscribe ok"),
        pytest.param(
            '{"id":3,"subscribe":{"recoverable":false}}', Reply(3, None), id="subscribe with result"
        ),
        pytest.param('{"id":4}', Reply(4, None), id="empty reply"),
        pytest.param(
            '{"id":2,"error":{"code":105,"message":"already subscribed","temporary":false}}',
            Reply(2, ReplyError(105, "already subscribed", False)),
            id="already subscribed",
        ),
        pytest.param(
            '{"id":5,"error":{"code":100,"temporary":true}}',
            Reply(5, ReplyError(100, "", True)),
            id="temporary error without message",
        ),
        pytest.param(
            '{"id":6,"error":{"code":100,"message":null,"temporary":null}}',
            Reply(6, ReplyError(100, "", False)),
            id="null message and temporary",
        ),
        pytest.param(
            '{"id":1,"subscribe":{},"future":{"a":1}}', Reply(1, None), id="several result keys"
        ),
        pytest.param('{"id":2,"subscribe":"x"}', Reply(2, None), id="success payload not read"),
    ],
)
def test_command_replies(raw: str, expected: Reply) -> None:
    assert decode_message(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(
            '{"push":{"channel":"","disconnect":{"code":3009,"reason":"shutdown"}}}',
            Disconnect(3009, "shutdown"),
            id="disconnect push",
        ),
        pytest.param('{"disconnect":{"code":3000}}', Disconnect(3000, ""), id="no reason"),
        pytest.param(
            '{"push":{"channel":"market_products_updates",'
            '"unsubscribe":{"code":2500,"reason":"server unsubscribe"}}}',
            Unsubscribe("market_products_updates", 2500),
            id="unsubscribe push",
        ),
    ],
)
def test_disconnect_and_unsubscribe(raw: str, expected: Disconnect | Unsubscribe) -> None:
    assert decode_message(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param('{"push":{"channel":"c","join":{"info":{}}}}', id="join push"),
        pytest.param('{"push":{"channel":"c","leave":{"info":{}}}}', id="leave push"),
        pytest.param('{"push":{"channel":"c","message":{"data":{"a":1}}}}', id="message push"),
        pytest.param('{"push":{"refresh":{"expires":true,"ttl":60}}}', id="refresh push"),
        pytest.param('{"push":{"channel":"c","future_kind":[1]}}', id="unknown push kind"),
        pytest.param('{"hello":1}', id="unknown top-level key"),
        pytest.param('{"channel":"c","join":{}}', id="unknown top-level kind with channel"),
    ],
)
def test_unmodelled_well_formed_kind_is_other_message(raw: str) -> None:
    assert decode_message(raw) == OtherMessage()


@pytest.mark.parametrize(
    ("raw", "path"),
    [
        pytest.param("not json at all", ("live",), id="not JSON"),
        pytest.param("", ("live",), id="empty string"),
        pytest.param('{"channel":"c","pub":', ("live",), id="truncated JSON"),
        pytest.param(b"\xff\xfe{", ("live",), id="bytes that are not UTF-8"),
        pytest.param('{"a":NaN}', ("live",), id="NaN constant"),
        pytest.param("[1,2]", ("live",), id="a list"),
        pytest.param("[]", ("live",), id="an empty list is not a message"),
        pytest.param("5", ("live",), id="a scalar"),
        pytest.param("null", ("live",), id="null"),
        pytest.param('{"push":5}', ("live", "push"), id="push not an object"),
        pytest.param('{"pub":{"data":{}}}', ("live", "channel"), id="pub without a channel"),
        pytest.param('{"channel":5,"pub":{"data":{}}}', ("live", "channel"), id="channel number"),
        pytest.param('{"channel":"c","pub":"x"}', ("live", "pub"), id="pub not an object"),
        pytest.param('{"channel":"c","pub":{}}', ("live", "pub", "data"), id="pub without data"),
        pytest.param('{"channel":"c","pub":{"data":[1]}}', ("live", "pub", "data"), id="data list"),
        pytest.param('{"id":"1","subscribe":{}}', ("live", "id"), id="reply id a string"),
        pytest.param('{"id":true}', ("live", "id"), id="reply id a bool"),
        pytest.param('{"id":1.0}', ("live", "id"), id="reply id a float"),
        pytest.param('{"id":1,"error":{"message":"x"}}', ("live", "error", "code"), id="no code"),
        pytest.param('{"id":1,"error":{"code":"105"}}', ("live", "error", "code"), id="code str"),
        pytest.param('{"id":1,"error":{"code":true}}', ("live", "error", "code"), id="code bool"),
        pytest.param(
            '{"id":1,"error":{"code":1,"message":5}}', ("live", "error", "message"), id="msg number"
        ),
        pytest.param(
            '{"id":1,"error":{"code":1,"temporary":"yes"}}',
            ("live", "error", "temporary"),
            id="temporary string",
        ),
        pytest.param('{"id":1,"error":null}', ("live", "error"), id="error null"),
        pytest.param('{"connect":5}', ("live", "connect"), id="connect not an object"),
        pytest.param('{"connect":{"ping":"25"}}', ("live", "connect", "ping"), id="ping string"),
        pytest.param('{"connect":{"ping":true}}', ("live", "connect", "ping"), id="ping bool"),
        pytest.param('{"connect":{"ttl":1.5}}', ("live", "connect", "ttl"), id="ttl float"),
        pytest.param('{"connect":{"pong":1}}', ("live", "connect", "pong"), id="pong number"),
        pytest.param(
            '{"connect":{"expires":"true"}}', ("live", "connect", "expires"), id="expires string"
        ),
        pytest.param('{"connect":{"subs":5}}', ("live", "connect", "subs"), id="subs scalar"),
        pytest.param('{"connect":{"subs":[]}}', ("live", "connect", "subs"), id="subs list"),
        pytest.param(
            '{"disconnect":{"reason":"x"}}', ("live", "disconnect", "code"), id="no disconnect code"
        ),
        pytest.param(
            '{"disconnect":{"code":3000,"reason":5}}',
            ("live", "disconnect", "reason"),
            id="reason number",
        ),
        pytest.param('{"disconnect":"x"}', ("live", "disconnect"), id="disconnect not an object"),
        pytest.param('{"unsubscribe":{"code":2500}}', ("live", "channel"), id="no channel"),
        pytest.param(
            '{"channel":"c","unsubscribe":{}}', ("live", "unsubscribe", "code"), id="no code"
        ),
        pytest.param(
            '{"push":{"channel":"c","unsubscribe":{"code":"x"}}}',
            ("live", "push", "unsubscribe", "code"),
            id="path inside a push",
        ),
    ],
)
def test_malformed_message_is_a_decode_error_at_the_field(
    raw: str | bytes, path: tuple[str, ...]
) -> None:
    with pytest.raises(DecodeError) as caught:
        decode_message(raw)

    assert caught.value.path == path
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param('{"channel":"SERVER-MARK","pub":"SERVER-MARK"}', id="pub not an object"),
        pytest.param('{"disconnect":{"code":"SERVER-MARK"}}', id="code mistyped"),
        pytest.param("SERVER-MARK", id="not JSON"),
        pytest.param('{"connect":{"ping":"SERVER-MARK"}}', id="ping mistyped"),
        pytest.param('{"SERVER-MARK":' * 80 + "1" + "}" * 80, id="too deep"),
    ],
)
def test_failure_never_holds_server_bytes(raw: str) -> None:
    with pytest.raises(DecodeError) as caught:
        decode_message(raw)

    assert "MARK" not in str(caught.value)
    assert "MARK" not in repr(caught.value)
    assert "MARK" not in repr(caught.value.args)


def _nest(levels: int) -> str:
    return "[" * levels + "]" * levels


@pytest.mark.parametrize(
    ("levels", "accepted"),
    [
        pytest.param(10, True, id="well inside"),
        pytest.param(60, True, id="envelope 3 + 60 = 63 levels accepted"),
        pytest.param(61, False, id="envelope 3 + 61 = 64 levels refused"),
        pytest.param(5000, False, id="beyond the interpreter recursion limit"),
    ],
)
def test_nesting_boundary_matches_php_depth_64(levels: int, accepted: bool) -> None:
    raw = '{"channel":"c","pub":{"data":{"message":' + _nest(levels) + "}}}"

    if accepted:
        assert isinstance(decode_message(raw), Publication)
    else:
        with pytest.raises(DecodeError, match="64") as caught:
            decode_message(raw)
        assert caught.value.reason == "nested deeper than 64 levels"


def test_object_nesting_counts_like_array_nesting() -> None:
    deep = '{"a":' * 63 + "1" + "}" * 63
    deeper = '{"a":' * 64 + "1" + "}" * 64

    assert decode_message(deep) == OtherMessage()
    with pytest.raises(DecodeError):
        decode_message(deeper)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("shutdown", "shutdown", id="printable ascii stays"),
        pytest.param("", "", id="empty"),
        pytest.param("a\nbé" + "c" * 200, "a?b??" + "c" * 123, id="control, non-ASCII, cut"),
        pytest.param("\x1f \x7e\x7f", "? ~?", id="0x20 and 0x7e stay, 0x1f and 0x7f replaced"),
        pytest.param("\U0001f600", "????", id="a 4-byte character is four marks"),
        pytest.param("\ud800", "?", id="a lone surrogate does not raise"),
        pytest.param("a" * 128, "a" * 128, id="exactly 128 bytes"),
        pytest.param("a" * 129, "a" * 128, id="129 bytes cut to 128"),
        pytest.param("é" * 65, "?" * 128, id="cut counts bytes, not characters"),
    ],
)
def test_printable(text: str, expected: str) -> None:
    assert printable(text) == expected


def test_printable_limit_is_a_parameter() -> None:
    assert printable("abcdef", limit=3) == "abc"


@pytest.mark.parametrize("field", ["reason", "message"])
def test_server_text_goes_through_printable(field: str) -> None:
    text = "a\nbé" + "c" * 200
    expected = "a?b??" + "c" * 123

    if field == "reason":
        decoded = decode_message(json.dumps({"disconnect": {"code": 3000, "reason": text}}))
        assert isinstance(decoded, Disconnect)
        assert decoded.reason == expected
    else:
        decoded = decode_message(json.dumps({"id": 1, "error": {"code": 100, "message": text}}))
        assert isinstance(decoded, Reply)
        assert decoded.error is not None
        assert decoded.error.message == expected
