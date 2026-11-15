"""SseConnection against a fake SSE server on loopback."""

import asyncio
import contextlib
import json
import logging
import tracemalloc
from collections.abc import AsyncIterator
from typing import Any

import pytest

from support.flavors import jwt
from support.live_servers import FakeSseServer, SseScript, connect_reply, pub_message, sse_data
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import (
    BUFFER_BYTES,
    ServerClosedError,
    StatusFailureError,
    queue_size,
)
from whitemarket.live._envelope import Ping, Publication
from whitemarket.live._policy import MAX_TTL_SECONDS
from whitemarket.live._sse import SseConnection
from whitemarket.live.options import LiveOptions

TOKEN = jwt(exp=4_000_000_000, sub="synthetic-user")
CONTENT = {
    "id": "1",
    "app_id": "730",
    "asset_id": "2",
    "class_id": "3",
    "instance_id": "0",
    "price": "1.5",
    "name_hash": "AK",
}


def connection(
    server: FakeSseServer,
    options: LiveOptions | None = None,
    *,
    early_text_limit: int = BUFFER_BYTES,
) -> SseConnection:
    return SseConnection(
        server.url,
        "test-agent/1",
        options or LiveOptions(),
        trust_env=False,
        early_text_limit=early_text_limit,
    )


def product_message(product_id: str) -> dict[str, Any]:
    content = {**CONTENT, "id": product_id}
    return pub_message("market_products_updates", "market_product_added", content)


def product_event(product_id: str) -> bytes:
    return sse_data(product_message(product_id))


def published_product_id(message: object) -> str:
    assert isinstance(message, Publication)
    return str(json.loads(message.data["message"])["content"]["id"])


@contextlib.asynccontextmanager
async def serving(
    scripts: list[SseScript], *, early_text_limit: int = BUFFER_BYTES
) -> AsyncIterator[SseConnection]:
    """A connection to a fake server, closed even when the test fails: a stream left open would
    make the server's shutdown wait forever."""
    async with FakeSseServer(scripts) as server:
        conn = connection(server, early_text_limit=early_text_limit)
        try:
            yield conn
        finally:
            await conn.close()


async def test_the_request_is_a_get_with_cf_connect_and_no_compression() -> None:
    script = SseScript(steps=[sse_data(connect_reply())])
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        info = await conn.open(Secret(TOKEN), ["market_products_updates", "#42"], 5.0)
        await conn.close()
    request = server.requests[0]
    assert (request["method"], request["path"]) == ("GET", "/sse_endpoint")
    assert json.loads(request["query"]["cf_connect"][0]) == {
        "token": TOKEN,
        "subs": {"market_products_updates": {}},  # the personal channel is never requested
    }
    assert request["headers"]["accept"] == "text/event-stream"
    assert request["headers"]["accept-encoding"] == "identity"
    assert request["headers"]["user-agent"] == "test-agent/1"
    assert (info.ping, info.pong, info.ttl) == (25, True, 86400.0)


async def test_a_connect_reply_ttl_beyond_a_float_is_capped() -> None:
    # A faulty server: `float(10**400)` overflows; the connect must still succeed.
    script = SseScript(steps=[sse_data(connect_reply(ttl=10**400))])
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        info = await conn.open(Secret(TOKEN), [], 5.0)
        await conn.close()
    assert info.ttl == float(MAX_TTL_SECONDS)


@pytest.mark.parametrize(
    "ttl",
    [
        pytest.param("5", id="ttl as a JSON string of digits"),
        pytest.param(5.0, id="ttl as a JSON fraction"),
        pytest.param(True, id="ttl as a JSON boolean"),
    ],
)
async def test_a_connect_reply_ttl_that_is_not_a_json_integer_is_never_a_connect(
    ttl: Any,
) -> None:
    # PHP parity (2026-11-15): a ttl in any other JSON type is a decode error, like any integer
    # field, never read as a number. The reply then never counts as the connect reply.
    script = SseScript(steps=[sse_data(connect_reply(ttl=ttl))])
    async with serving([script]) as conn:
        with pytest.raises(TransportError, match="no connect reply"):
            await conn.open(Secret(TOKEN), [], 0.3)


async def test_connect_reply_then_publications_pings_and_split_chunks() -> None:
    message = sse_data(pub_message("market_products_updates", "market_product_added", CONTENT))
    script = SseScript(
        steps=[
            sse_data(connect_reply(pong=None)),
            b"data: {}\n\n",
            message[:17],
            0.05,
            message[17:],
        ]
    )
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        info = await conn.open(Secret(TOKEN), [], 5.0)
        assert info.pong is False
        assert isinstance(await conn.read(2.0), Ping)
        publication = await conn.read(2.0)
        assert isinstance(publication, Publication)
        assert publication.channel == "market_products_updates"
        assert await conn.read(0.05) is None  # nothing more: a timeout, not an error
        await conn.close()


async def test_a_malformed_message_raises_decode_error_and_the_stream_continues() -> None:
    script = SseScript(steps=[sse_data(connect_reply()), b"data: not json\n\n", b"data: {}\n\n"])
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        with pytest.raises(DecodeError):
            await conn.read(2.0)
        assert isinstance(await conn.read(2.0), Ping)
        await conn.close()


@pytest.mark.parametrize(
    ("status", "headers", "retry_after"),
    [
        (401, {}, None),
        (429, {"Retry-After": "7"}, 7),
        (503, {"Retry-After": "bogus"}, None),
        (500, {}, None),
    ],
    ids=["401", "429-retry-after", "503-unparsable", "500"],
)
async def test_a_non_2xx_status_is_a_status_failure(
    status: int, headers: dict[str, str], retry_after: int | None
) -> None:
    async with FakeSseServer([SseScript(status=status, headers=headers)]) as server:
        conn = connection(server)
        with pytest.raises(StatusFailureError) as caught:
            await conn.open(Secret(TOKEN), [], 5.0)
    assert (caught.value.status, caught.value.retry_after) == (status, retry_after)


async def test_a_redirect_is_never_followed() -> None:
    scripts = [
        SseScript(status=302, headers={"Location": "/elsewhere"}),
        SseScript(steps=[sse_data(connect_reply())]),
    ]
    async with FakeSseServer(scripts) as server:
        conn = connection(server)
        with pytest.raises(StatusFailureError) as caught:
            await conn.open(Secret(TOKEN), [], 5.0)
    assert caught.value.status == 302
    assert len(server.requests) == 1


async def test_a_content_encoding_that_was_not_asked_for_is_refused() -> None:
    script = SseScript(headers={"Content-Encoding": "gzip"}, steps=[sse_data(connect_reply())])
    async with FakeSseServer([script]) as server:
        with pytest.raises(TransportError, match="content encoding"):
            await connection(server).open(Secret(TOKEN), [], 5.0)


async def test_no_connect_reply_in_time_is_a_transport_error() -> None:
    async with FakeSseServer([SseScript()]) as server:
        with pytest.raises(TransportError, match="no connect reply"):
            await connection(server).open(Secret(TOKEN), [], 0.2)
        await asyncio.sleep(0.05)
        assert server.open_streams == 0


async def test_messages_before_the_connect_reply_are_kept_and_read_first_in_order() -> None:
    # [observed 2026-11-15] the live SSE endpoint sometimes sends publications before the reply.
    script = SseScript(
        steps=[
            product_event("early-1"),
            b"data: {}\n\n",
            b"data: nope\n\n",
            product_event("early-2"),
            sse_data(connect_reply(ttl=None)),
            product_event("late"),
        ]
    )
    async with serving([script]) as conn:
        info = await conn.open(Secret(TOKEN), [], 5.0)
        assert (info.ping, info.ttl) == (25, None)  # the connect reply, wherever it came
        assert published_product_id(await conn.read(2.0)) == "early-1"
        assert isinstance(await conn.read(2.0), Ping)
        with pytest.raises(DecodeError):  # as after the reply: reported, the stream continues
            await conn.read(2.0)
        assert published_product_id(await conn.read(2.0)) == "early-2"
        assert published_product_id(await conn.read(2.0)) == "late"
        assert await conn.read(0.05) is None


async def test_more_messages_before_the_connect_reply_than_the_queue_holds_are_all_kept() -> None:
    # [observed 2026-11-15] the live endpoint sent more than 64 publications (the default queue
    # size) before the reply: a count limit failed the connect.
    count = 2 * queue_size(LiveOptions().max_message_bytes)
    early = [product_event(f"p{n:04}") for n in range(count)]
    async with serving([SseScript(steps=[*early, sse_data(connect_reply())])]) as conn:
        await conn.open(Secret(TOKEN), [], 5.0)
        assert [published_product_id(await conn.read(2.0)) for _ in range(count)] == [
            f"p{n:04}" for n in range(count)
        ]


@pytest.mark.parametrize(
    ("count", "accepted"),
    [(3, True), (4, False)],
    ids=["text exactly at the limit -> connected", "one message over -> transport error"],
)
async def test_messages_before_the_connect_reply_are_bounded_by_their_text_size(
    count: int, accepted: bool
) -> None:
    # the raw `data:` text, serialised as `sse_data` does; every `pN` below has the same length
    limit = 3 * len(json.dumps(product_message("p0")))
    early = [product_event(f"p{n}") for n in range(count)]
    script = SseScript(steps=[*early, sse_data(connect_reply())])
    async with serving([script], early_text_limit=limit) as conn:
        if accepted:
            await conn.open(Secret(TOKEN), [], 5.0)
            assert published_product_id(await conn.read(2.0)) == "p0"
        else:
            with pytest.raises(TransportError, match="before the connect reply"):
                await conn.open(Secret(TOKEN), [], 5.0)


async def test_a_stream_that_ends_before_the_connect_reply_is_a_transport_error() -> None:
    async with serving([SseScript(steps=[product_event("early")], hold=False)]) as conn:
        with pytest.raises(TransportError, match="ended before the connect reply"):
            await conn.open(Secret(TOKEN), [], 5.0)


async def test_a_disconnect_before_the_connect_reply_is_a_server_close() -> None:
    disconnect = sse_data({"disconnect": {"code": 3501, "reason": "bad request"}})
    script = SseScript(steps=[product_event("early"), disconnect, sse_data(connect_reply())])
    async with serving([script]) as conn:
        with pytest.raises(ServerClosedError) as caught:
            await conn.open(Secret(TOKEN), [], 5.0)
    assert (caught.value.code, caught.value.reason) == (3501, "bad request")


async def test_a_read_after_close_does_not_return_early_messages_never_read() -> None:
    script = SseScript(steps=[product_event("early"), sse_data(connect_reply())])
    async with serving([script]) as conn:
        await conn.open(Secret(TOKEN), [], 5.0)
        await conn.close()
        with pytest.raises(TransportError):
            await conn.read(2.0)


async def test_a_reopened_connection_does_not_replay_the_early_messages_of_the_last_one() -> None:
    scripts = [
        SseScript(steps=[product_event("old"), sse_data(connect_reply())]),
        SseScript(steps=[sse_data(connect_reply()), product_event("new")]),
    ]
    async with serving(scripts) as conn:
        await conn.open(Secret(TOKEN), [], 5.0)
        await conn.open(Secret(TOKEN), [], 5.0)
        assert published_product_id(await conn.read(2.0)) == "new"


async def test_the_end_of_the_stream_is_a_transport_error_on_read() -> None:
    script = SseScript(steps=[sse_data(connect_reply())], hold=False)
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        with pytest.raises(TransportError, match="ended"):
            await conn.read(2.0)
        await conn.close()


async def test_close_releases_the_stream_wakes_a_blocked_reader_and_leaks_no_task() -> None:
    before = set(asyncio.all_tasks())
    async with FakeSseServer([SseScript(steps=[sse_data(connect_reply())])]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), [], 5.0)
        reader = asyncio.create_task(conn.read(None))
        await asyncio.sleep(0.05)
        await conn.close()
        with pytest.raises(TransportError):
            await asyncio.wait_for(reader, 2)
        for _ in range(100):
            if server.open_streams == 0:
                break
            await asyncio.sleep(0.02)
        assert server.open_streams == 0
    assert set(asyncio.all_tasks()) - before - {asyncio.current_task()} == set()


async def test_an_oversized_event_ends_the_stream() -> None:
    big = b"data: " + b"x" * 5000 + b"\n\n"
    script = SseScript(steps=[sse_data(connect_reply()), big])
    async with FakeSseServer([script]) as server:
        conn = connection(server, LiveOptions(max_message_bytes=1024))
        await conn.open(Secret(TOKEN), [], 5.0)
        with pytest.raises(TransportError):
            await conn.read(2.0)
        await conn.close()


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO], ids=["debug", "info"])
async def test_the_token_never_appears_in_any_log_record(
    caplog: pytest.LogCaptureFixture, level: int
) -> None:
    caplog.set_level(level)
    logging.getLogger("httpx").setLevel(level)
    logging.getLogger("httpcore").setLevel(level)
    script = SseScript(
        steps=[
            sse_data(connect_reply()),
            sse_data(pub_message("market_products_updates", "market_product_added", CONTENT)),
        ]
    )
    async with FakeSseServer([script]) as server:
        conn = connection(server)
        await conn.open(Secret(TOKEN), ["market_products_updates"], 5.0)
        await conn.read(2.0)
        await conn.close()
    text = "\n".join(record.getMessage() + repr(record.args) for record in caplog.records)
    assert caplog.records, "the httpx request record must exist for the check to mean anything"
    assert TOKEN not in text
    assert "eyJhbGciOiJub25lIn0" not in text
    assert "cf_connect=%7B" not in text


async def test_a_failed_request_error_does_not_chain_the_httpx_error_that_holds_the_token_url() -> (
    None
):
    async with FakeSseServer([SseScript()]) as server:
        url = server.url
    conn = SseConnection(url, "ua", LiveOptions(), trust_env=False)  # nothing listens any more
    with pytest.raises(TransportError) as caught:
        await conn.open(Secret(TOKEN), [], 2.0)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    ("max_message_bytes", "expected"),
    [(1024, 4096), (1_048_576, 64), (64 * 1024 * 1024, 2)],
    ids=["small-messages-count-cap", "default-1MiB", "huge-messages-floor"],
)
def test_the_event_queue_is_bounded_by_bytes(max_message_bytes: int, expected: int) -> None:
    connection = SseConnection(
        "http://localhost/sse", "ua", LiveOptions(max_message_bytes=max_message_bytes)
    )
    assert connection._queue.maxsize == expected


async def test_a_flood_of_nested_events_keeps_memory_bounded_by_the_raw_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("whitemarket.live._connection.BUFFER_BYTES", 8 * 1024 * 1024)  # 8 messages
    limit = 1_048_576
    head, tail = '{"push":{"channel":"products","pub":{"data":{"a":[', "]}}}}"
    body = head + ",".join(["[]"] * ((limit - len(head) - len(tail) - 10) // 3)) + tail
    event = b"data: " + body.encode() + b"\n\n"
    script = SseScript(steps=[sse_data(connect_reply())] + [event] * 20)
    async with FakeSseServer([script]) as server:
        conn = connection(server, LiveOptions(max_message_bytes=limit))
        tracemalloc.start()
        try:
            await conn.open(Secret(TOKEN), [], 10.0)
            for _ in range(400):  # the consumer does not read: wait until the buffer is full
                if conn._queue.full():
                    break
                await asyncio.sleep(0.05)
            assert conn._queue.full()
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        message = await conn.read(2.0)  # one decoded message at a time still works
        await conn.close()
    assert isinstance(message, Publication)
    assert peak < 64 * 1024 * 1024


async def test_nested_messages_before_the_connect_reply_keep_memory_bounded_by_the_raw_text() -> (
    None
):
    # The decoded form of nested empty lists is ~20x its text: early messages are kept as text.
    # Peak [observed 2026-11-15]: ~20 MB kept as text (one decode at a time), ~52 MB decoded.
    size = 256 * 1024
    head, tail = '{"push":{"channel":"products","pub":{"data":{"a":[', "]}}}}"
    body = head + ",".join(["[]"] * ((size - len(head) - len(tail) - 10) // 3)) + tail
    event = b"data: " + body.encode() + b"\n\n"
    script = SseScript(steps=[*[event] * 8, sse_data(connect_reply())])
    async with serving([script], early_text_limit=16 * size) as conn:
        tracemalloc.start()
        try:
            await conn.open(Secret(TOKEN), [], 60.0)  # tracemalloc slows decoding a lot
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert isinstance(await conn.read(2.0), Publication)  # decoded one at a time on read
    assert peak < 32 * 1024 * 1024
