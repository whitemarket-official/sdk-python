"""WsConnection (centrifuge-python) against a fake Centrifugo server on loopback."""

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

import pytest

from support.flavors import jwt
from support.live_servers import (
    PRODUCT_CONTENT,
    FakeCentrifugoServer,
    FakeWsConnection,
    pub_message,
)
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import TransportError
from whitemarket.live._connection import (
    ConnectRejectedError,
    ServerClosedError,
    StatusFailureError,
)
from whitemarket.live._ws import WsConnection
from whitemarket.live.envelope import Publication, Unsubscribe

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


async def test_connect_command_subscribes_to_products_only_and_never_to_personal() -> None:
    async with FakeCentrifugoServer([serve_basic]) as server:
        conn = connection(server)
        info = await conn.open(Secret(TOKEN), [PRODUCTS, "#42"], 5.0)
        await asyncio.sleep(0.2)
        await conn.close()
    commands = server.connections[0].commands
    assert commands[0]["connect"]["token"] == TOKEN
    assert commands[0]["connect"]["name"] == "whitemarket-sdk-python"
    subscribes = [c["subscribe"]["channel"] for c in commands if "subscribe" in c]
    assert subscribes == [PRODUCTS]
    assert info.ping is None  # the library enforces the idle deadline itself
    assert info.ttl is not None
    assert info.ttl > 600


async def test_ttl_comes_from_the_jwt_exp() -> None:
    token = jwt(exp=int(time.time()) + 300)
    async with FakeCentrifugoServer([serve_basic]) as server:
        conn = connection(server)
        info = await conn.open(Secret(token), [PRODUCTS], 5.0)
        await conn.close()
    assert info.ttl == pytest.approx(300, abs=5)


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
        got = [await conn.read(2.0) for _ in range(3)]
        await conn.close()
    pubs = [m for m in got if isinstance(m, Publication)]
    assert [m.channel for m in pubs] == [PRODUCTS, PRODUCTS, "#42"]
    assert isinstance(pubs[0].data["message"], str)
    assert isinstance(pubs[1].data["message"], dict)


async def test_a_server_ping_is_answered_with_an_empty_message_when_pong_is_set() -> None:
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


async def test_no_server_ping_within_ping_plus_grace_drops_the_connection() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect(ping=1)
        await c.accept_subscribes(1)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server, idle_grace=0.3)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        with pytest.raises(TransportError):
            await conn.read(5.0)
        await conn.close()


@pytest.mark.parametrize("code", [3000, 3005, 3500, 3999, 4500], ids=str)
async def test_a_websocket_close_code_from_3000_is_reported_as_it_is(code: int) -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(code, "server says bye")

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        with pytest.raises(ServerClosedError) as caught:
            await conn.read(5.0)
        await conn.close()
    assert (caught.value.code, caught.value.reason) == (code, "server says bye")


async def test_a_disconnect_push_is_reported_with_its_code() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push({"disconnect": {"code": 3500, "reason": "invalid token"}}))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        with pytest.raises(ServerClosedError) as caught:
            await conn.read(5.0)
        await conn.close()
    assert caught.value.code == 3500


async def test_a_close_below_3000_is_reported_as_transport_closed_code_1() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(1000, "normal")

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        with pytest.raises(ServerClosedError) as caught:
            await conn.read(5.0)
        await conn.close()
    assert caught.value.code == 1  # the library collapses every close below 3000 (ADR 0005)


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


async def test_105_already_subscribed_is_a_success_and_other_subscribe_errors_are_reported() -> (
    None
):
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        first = await c.recv_command()
        await c.send({"id": first["id"], "error": {"code": 105, "message": "already subscribed"}})
        second = await c.recv_command()
        await c.send({"id": second["id"], "error": {"code": 103, "message": "permission denied"}})
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS, "other_channel"], 5.0)
        message = await conn.read(3.0)
        assert message == Unsubscribe("other_channel", 103)
        assert await conn.read(0.3) is None  # nothing for the 105 one
        await conn.close()


async def test_subscribe_after_connect_sends_a_subscribe_command() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(2)
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.subscribe("second_channel")
        await conn.subscribe("#42")  # personal: never sent
        await asyncio.sleep(0.3)
        await conn.close()
    channels = [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ]
    assert channels == [PRODUCTS, "second_channel"]


async def test_an_unsubscribe_push_below_2500_is_reported_and_from_2500_resubscribes() -> None:
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push({"channel": PRODUCTS, "unsubscribe": {"code": 2500, "reason": "again"}}))
        await c.accept_subscribes(1)  # the library subscribes again by itself
        await c.send(push({"channel": PRODUCTS, "unsubscribe": {"code": 2400, "reason": "no"}}))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        assert await conn.read(3.0) == Unsubscribe(PRODUCTS, 2400)
        await conn.close()
    assert [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ] == [PRODUCTS, PRODUCTS]


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
        reader = asyncio.create_task(conn.read(None))
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
    for name in ("centrifuge", "websockets.client"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    deal = {"deal_id": "d1", "deal_action_type": "buy", "deal_steam_id": "synthetic-steam-id"}

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send(push(pub_message("#42", "market_deal_offered", deal)))
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [PRODUCTS], 5.0)
        await conn.read(2.0)
        await conn.close()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in text
    assert "synthetic-steam-id" not in text
    assert "eyJhbGciOiJub25lIn0" not in text
