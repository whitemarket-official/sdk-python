"""WsConnection (own Centrifugo JSON client over websockets) against a fake server on loopback."""

import asyncio
import contextlib
import io
import json
import logging
import logging.config
import tracemalloc
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from support.flavors import jwt
from support.live_servers import (
    PRODUCT_CONTENT,
    FakeCentrifugoServer,
    FakeWsConnection,
    pub_message,
)
from whitemarket._runtime.secret import Secret
from whitemarket._version import __version__
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import (
    ConnectRejectedError,
    ServerClosedError,
    SlowConsumerError,
    StatusFailureError,
)
from whitemarket.live._envelope import Disconnect, Ping, Publication, Reply, Unsubscribe
from whitemarket.live._policy import MAX_TTL_SECONDS
from whitemarket.live._ws import WsConnection, _end_of

TOKEN = jwt(exp=4_000_000_000, sub="synthetic-user")
PRODUCTS = "market_products_updates"


def connection(server: FakeCentrifugoServer, **options: Any) -> WsConnection:
    return WsConnection(server.url, "test-agent/1", proxy=None, **options)


def push(publication: dict[str, Any]) -> dict[str, Any]:
    return {"push": publication}


async def serve_basic(c: FakeWsConnection) -> None:
    await c.accept_connect()
    await c.accept_subscribes(1)
    await c.hold()


async def read_until(conn: WsConnection, kind: type, seconds: float = 3.0) -> Any:
    """The next message of `kind`; pings and replies in between are skipped."""
    while True:
        message = await conn.read(seconds)
        assert message is not None, f"no {kind.__name__} arrived"
        if isinstance(message, kind):
            return message


async def test_connect_command_carries_token_name_version_and_subscribes_to_products_only() -> None:
    async with FakeCentrifugoServer([serve_basic]) as server:
        conn = connection(server)
        info = await conn.open(Secret(TOKEN), [PRODUCTS, "#42"], 5.0)
        await asyncio.sleep(0.2)
        await conn.close()
    commands = server.connections[0].commands
    assert commands[0]["id"] == 1
    assert commands[0]["connect"] == {
        "token": TOKEN,
        "name": "whitemarket-sdk-python",
        "version": __version__,
    }
    assert [c["subscribe"]["channel"] for c in commands if "subscribe" in c] == [PRODUCTS]
    assert (info.ping, info.pong, info.ttl) == (25, True, 86400.0)


async def test_user_agent_header_is_sent() -> None:
    seen: list[str] = []

    async def script(c: FakeWsConnection) -> None:
        seen.append(c.ws.request.headers["User-Agent"] if c.ws.request else "")
        await c.accept_connect()
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        await conn.close()
    assert seen == ["test-agent/1"]


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ({"ttl": 300}, (25, True, 300.0)),
        ({"ttl": None}, (25, True, None)),  # no `expires`: the token does not expire
        ({"ping": 1000}, (300, True, 86400.0)),  # clamped to 300 s
        ({"ping": None, "pong": None}, (25, False, 86400.0)),  # defaults
        ({"ttl": MAX_TTL_SECONDS}, (25, True, float(MAX_TTL_SECONDS))),
        ({"ttl": MAX_TTL_SECONDS + 1}, (25, True, float(MAX_TTL_SECONDS))),
        ({"ttl": 10**400}, (25, True, float(MAX_TTL_SECONDS))),  # beyond a float
        ({"ttl": -(10**400)}, (25, True, 0.0)),  # below a float: already expired
    ],
    ids=[
        "ttl-from-reply",
        "no-expiry",
        "ping-clamped",
        "defaults",
        "ttl at the cap -> kept",
        "ttl over the cap -> the cap",
        "ttl beyond a float -> the cap",
        "ttl below a float -> 0",
    ],
)
async def test_the_connect_reply_decides_ping_pong_and_ttl(
    reply: dict[str, Any], expected: tuple[int, bool, float | None]
) -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect(**reply)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        info = await conn.open(Secret(jwt(exp=4_000_000_000)), [], 5.0)
        await conn.close()
    assert (info.ping, info.pong, info.ttl) == expected  # never derived from the JWT `exp`


async def test_string_and_object_messages_and_several_messages_in_one_frame() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        first = push(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
        second = push(
            pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT, as_string=False)
        )
        await c.send(
            first, second, {}, push(pub_message("#42", "market_deal_offered", {"deal_id": "d"}))
        )
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        got = [await conn.read(2.0) for _ in range(5)]  # the subscribe reply, then the frame
        await conn.close()
    assert isinstance(got[0], Reply)
    assert [type(m) for m in got[1:]] == [Publication, Publication, Ping, Publication]
    pubs = [m for m in got if isinstance(m, Publication)]
    assert [m.channel for m in pubs] == [PRODUCTS, PRODUCTS, "#42"]
    assert isinstance(pubs[0].data["message"], str)
    assert isinstance(pubs[1].data["message"], dict)


async def test_a_server_ping_is_answered_with_an_empty_message_without_a_reader() -> None:
    answered = asyncio.Event()

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect(pong=True)
        await c.accept_subscribes(1)
        await c.send({})
        raw = await c.ws.recv()
        if json.loads(raw) == {}:
            answered.set()
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        # nobody calls `read`: the pong is the connection's own duty
        await asyncio.wait_for(answered.wait(), 3)
        await conn.close()


async def test_a_ping_is_not_answered_when_the_connect_reply_has_no_pong() -> None:
    received: list[str] = []

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect(pong=None)
        await c.accept_subscribes(1)
        await c.send({})
        with contextlib.suppress(TimeoutError):
            received.append(str(await asyncio.wait_for(c.ws.recv(), 0.5)))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await asyncio.sleep(0.7)
        await conn.close()
    assert received == []


@pytest.mark.parametrize("code", [3000, 3005, 3500, 3999, 4500], ids=str)
async def test_a_websocket_close_code_from_3000_is_reported_as_it_is(code: int) -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(code, "server says bye")

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        error = await read_error(conn)
        await conn.close()
    assert (error.code, error.reason) == (code, "server says bye")


async def drain(conn: WsConnection) -> None:
    for _ in range(100):  # bounded: a connection that never ends fails the test
        await conn.read(0.5)


async def read_error(conn: WsConnection) -> ServerClosedError:
    with pytest.raises(ServerClosedError) as caught:
        await drain(conn)
    return caught.value


@pytest.mark.parametrize("code", [1000, 1001, 1011, 1012], ids=str)
async def test_a_close_below_3000_keeps_its_real_code(code: int) -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(code, "bye")

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        error = await read_error(conn)
        await conn.close()
    assert (error.code, error.reason) == (code, "bye")


async def test_a_dropped_link_is_code_1006() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        c.ws.transport.abort()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        error = await read_error(conn)
        await conn.close()
    assert error.code == 1006


async def test_a_long_or_non_ascii_close_reason_is_printable_ascii_cut_to_128_bytes() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.ws.close(3000, "é" + "x" * 120)  # a close reason may hold up to 123 bytes

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        error = await read_error(conn)
        await conn.close()
    assert error.reason == "??" + "x" * 120


async def test_a_disconnect_push_is_passed_with_its_code_and_reason() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push({"disconnect": {"code": 3500, "reason": "invalid token"}}))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        message = await read_until(conn, Disconnect)
        await conn.close()
    assert message == Disconnect(3500, "invalid token")


async def test_a_close_while_connecting_is_a_failed_attempt_below_3000_and_a_close_above() -> None:
    async def below(c: FakeWsConnection) -> None:
        await c.recv_command()
        await c.ws.close(1011, "oops")

    async def above(c: FakeWsConnection) -> None:
        await c.recv_command()
        await c.ws.close(3500, "invalid token")

    async with FakeCentrifugoServer([below, above]) as server:
        conn = connection(server)
        with pytest.raises(TransportError):
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        with pytest.raises(ServerClosedError) as caught:
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.close()
    assert caught.value.code == 3500


async def test_a_disconnect_push_while_connecting_is_a_close() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.recv_command()
        await c.send(push({"disconnect": {"code": 3503, "reason": "force"}}))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        with pytest.raises(ServerClosedError) as caught:
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.close()
    assert (caught.value.code, caught.value.reason) == (3503, "force")


@pytest.mark.parametrize(("code", "temporary"), [(109, True), (100, True), (111, True)], ids=str)
async def test_a_temporary_connect_error_is_a_connect_rejection(code: int, temporary: bool) -> None:
    async def script(c: FakeWsConnection) -> None:
        command = await c.recv_command()
        await c.send(
            {"id": command["id"], "error": {"code": code, "message": "m", "temporary": temporary}}
        )
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        with pytest.raises(ConnectRejectedError) as caught:
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.close()
    assert (caught.value.code, caught.value.temporary) == (code, temporary)


async def test_a_permanent_connect_error_is_a_permanent_rejection() -> None:
    async def script(c: FakeWsConnection) -> None:
        command = await c.recv_command()
        await c.send({"id": command["id"], "error": {"code": 101, "message": "unauthorized"}})
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        with pytest.raises(ConnectRejectedError) as caught:
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.close()
    assert (caught.value.code, caught.value.temporary) == (101, False)


async def test_a_rejected_upgrade_is_a_status_failure_with_retry_after() -> None:
    async with FakeCentrifugoServer(
        [serve_basic], upgrade_status={0: (429, {"Retry-After": "7"})}
    ) as server:
        conn = connection(server)
        with pytest.raises(StatusFailureError) as caught:
            await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.close()
    assert (caught.value.status, caught.value.retry_after) == (429, 7)


async def test_a_refused_tcp_connection_is_a_transport_error() -> None:
    async with FakeCentrifugoServer([serve_basic]) as server:
        url = server.url
    conn = WsConnection(url, "ua", proxy=None)
    with pytest.raises(TransportError):
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
    await conn.close()


async def test_no_connect_reply_in_time_is_a_transport_error() -> None:
    async def silent(c: FakeWsConnection) -> None:
        await c.hold()

    async with FakeCentrifugoServer([silent]) as server:
        conn = connection(server)
        with pytest.raises(TransportError):
            await conn.open(Secret(TOKEN), [PRODUCTS], 0.3)
        await conn.close()


async def test_105_is_passed_as_a_reply_and_other_subscribe_errors_free_the_channel() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        first = await c.recv_command()
        await c.send({"id": first["id"], "error": {"code": 105, "message": "already subscribed"}})
        second = await c.recv_command()
        await c.send({"id": second["id"], "error": {"code": 103, "message": "permission denied"}})
        await c.accept_subscribes(1)  # the retry of the refused channel
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS, "other_channel"], 5.0)
        replies = [await read_until(conn, Reply) for _ in range(2)]
        assert [r.error.code for r in replies if r.error] == [105, 103]  # the engine decides
        await conn.subscribe("other_channel")  # refused earlier: subscribing again is allowed
        await conn.subscribe(PRODUCTS)  # 105 counts as subscribed: not sent again
        await asyncio.sleep(0.2)
        await conn.close()
    channels = [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ]
    assert channels == [PRODUCTS, "other_channel", "other_channel"]


async def test_subscribe_after_connect_sends_a_subscribe_command_once() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(2)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.subscribe("second_channel")
        await conn.subscribe("second_channel")  # already subscribed: not sent again
        await conn.subscribe("#42")  # personal: never sent
        await asyncio.sleep(0.3)
        await conn.close()
    channels = [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ]
    assert channels == [PRODUCTS, "second_channel"]


async def test_subscribe_on_a_connection_that_is_not_open_is_a_transport_error() -> None:
    conn = WsConnection("ws://127.0.0.1:1/x", "ua", proxy=None)
    with pytest.raises(TransportError):
        await conn.subscribe(PRODUCTS)


async def test_an_unsubscribe_push_is_passed_on_and_the_channel_can_be_subscribed_again() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push({"channel": PRODUCTS, "unsubscribe": {"code": 2500, "reason": "again"}}))
        await c.accept_subscribes(1)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        assert await read_until(conn, Unsubscribe) == Unsubscribe(PRODUCTS, 2500)
        await conn.subscribe(PRODUCTS)  # the session's resubscribe for a code from 2500
        await asyncio.sleep(0.3)
        await conn.close()
    assert [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ] == [PRODUCTS, PRODUCTS]


async def test_a_malformed_line_is_a_decode_error_and_the_stream_continues() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        good = json.dumps(push(pub_message("#42", "market_deal_offered", {"deal_id": "d"})))
        await c.send_raw("not json at all\n" + good + "\n[1]\n" + good)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        outcomes: list[str] = []
        for _ in range(4):
            try:
                message = await conn.read(3.0)
            except DecodeError:
                outcomes.append("error")
            else:
                outcomes.append(type(message).__name__)
        await conn.close()
    assert outcomes == ["error", "Publication", "error", "Publication"]


async def test_a_frame_over_max_message_bytes_ends_the_connection_with_1009() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.send(push(pub_message("#42", "market_deal_offered", {"deal_id": "ok"})))
        await c.send(push(pub_message("#42", "market_deal_offered", {"deal_id": "x" * 5000})))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server, max_message_bytes=2000)
        await conn.open(Secret(TOKEN), [], 5.0)
        assert isinstance(await read_until(conn, Publication), Publication)  # under the limit
        error = await read_error(conn)
        await conn.close()
    assert error.code == 1009


async def test_a_frame_within_max_message_bytes_is_delivered() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.send(push(pub_message("#42", "market_deal_offered", {"deal_id": "x" * 1500})))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server, max_message_bytes=2000)
        await conn.open(Secret(TOKEN), [], 5.0)
        message = await read_until(conn, Publication)
        await conn.close()
    assert message.channel == "#42"


async def test_a_flood_with_a_consumer_that_does_not_read_stays_bounded_and_drops_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("whitemarket.live._connection.QUEUE_SIZE", 8)
    frame = push(pub_message("#42", "market_deal_offered", {"deal_id": "d"}))
    closed_by_client = asyncio.Event()

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        try:
            for _ in range(500):
                await c.send(frame)
            await c.ws.wait_closed()
        finally:
            closed_by_client.set()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        await asyncio.sleep(1.0)  # the consumer does not read
        assert conn._link is not None
        assert conn._link.queue.qsize() <= 8
        with pytest.raises(SlowConsumerError):
            await conn.read(1.0)
        await asyncio.wait_for(closed_by_client.wait(), 5)  # the socket was closed by us
        await conn.close()


async def test_close_stops_every_task_and_closes_the_socket() -> None:
    closed = asyncio.Event()

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        try:
            await c.ws.wait_closed()
        finally:
            closed.set()

    before = set(asyncio.all_tasks())
    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)

        async def consume() -> None:
            while True:
                await conn.read(None)

        reader = asyncio.create_task(consume())
        await asyncio.sleep(0.1)
        await conn.close()
        with pytest.raises(TransportError):
            await asyncio.wait_for(reader, 2)
        await asyncio.wait_for(closed.wait(), 10)
    leaked = set(asyncio.all_tasks()) - before - {asyncio.current_task()}
    assert leaked == set()


async def test_the_token_and_deal_data_never_appear_in_debug_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("websockets").setLevel(logging.DEBUG)
    logging.getLogger("websockets.client").setLevel(logging.DEBUG)
    deal = {"deal_id": "d1", "deal_action_type": "buy", "deal_steam_id": "synthetic-steam-id"}

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push(pub_message("#42", "market_deal_offered", deal)))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await read_until(conn, Publication)
        await conn.close()
    # the fake server's own logger shows the client's frames: it is not part of the SDK
    records = [r for r in caplog.records if not r.name.startswith("fake-centrifugo")]
    text = "\n".join(r.getMessage() for r in records)
    assert TOKEN not in text
    assert "synthetic-steam-id" not in text
    assert "eyJhbGciOiJub25lIn0" not in text
    assert not any(r.name.startswith("websockets") for r in records)


@pytest.fixture
def debug_logging_config() -> Any:
    """What an application may do after our import: `dictConfig` naming `whitemarket` at DEBUG."""
    stream = io.StringIO()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {"h": {"class": "logging.StreamHandler", "stream": stream}},
            "loggers": {"whitemarket": {"level": "DEBUG", "handlers": ["h"]}},
            "root": {"level": "DEBUG", "handlers": ["h"]},
        }
    )
    try:
        yield stream
    finally:
        for name in ("whitemarket", "websockets"):
            logging.getLogger(name).handlers.clear()
            logging.getLogger(name).setLevel(logging.NOTSET)
        logging.getLogger().handlers.clear()
        logging.getLogger().setLevel(logging.WARNING)


async def test_frames_are_never_logged_even_when_the_application_enables_debug(
    debug_logging_config: io.StringIO,
) -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.send(push(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT)))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        await read_until(conn, Publication)
        await conn.close()
    logged = debug_logging_config.getvalue()
    assert TOKEN[:20] not in logged
    assert '"connect"' not in logged
    assert "market_product_added" not in logged


async def test_a_reader_cancelled_with_the_callers_task_propagates_the_cancellation() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        closing = asyncio.create_task(conn.close())
        await asyncio.sleep(0)  # `close` is now waiting for the reader
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing


@pytest.mark.parametrize(
    ("rcvd_then_sent", "expected"),
    [
        pytest.param(False, 1008, id="we closed first -> our code"),
        pytest.param(True, 1001, id="the server closed first -> its code"),
    ],
)
def test_the_close_code_is_the_one_of_the_side_that_closed_first(
    rcvd_then_sent: bool, expected: int
) -> None:
    closed = ConnectionClosed(Close(1001, "echo"), Close(1008, "ours"), rcvd_then_sent)
    assert _end_of(closed).code == expected


async def test_a_flood_of_nested_publications_keeps_memory_bounded_by_the_raw_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("whitemarket.live._connection.BUFFER_BYTES", 8 * 1024 * 1024)  # 8 messages
    limit = 1_048_576
    head, tail = '{"push":{"channel":"products","pub":{"data":{"a":[', "]}}}}"
    payload = head + ",".join(["[]"] * ((limit - len(head) - len(tail) - 10) // 3)) + tail
    assert len(payload) <= limit

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        for _ in range(20):  # more than the 8 messages the buffer holds
            await c.send_raw(payload)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server, max_message_bytes=limit)
        tracemalloc.start()
        try:
            await conn.open(Secret(TOKEN), [], 10.0)
            assert conn._link is not None
            link = conn._link
            for _ in range(400):  # the consumer does not read: wait until the buffer is full
                if link.overflowed:
                    break
                await asyncio.sleep(0.05)
            assert link.overflowed
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        await conn.close()
    assert peak < 64 * 1024 * 1024  # eight decoded messages were ~190 MiB
