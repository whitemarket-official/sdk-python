"""SseConnection against a fake SSE server on loopback."""

import asyncio
import json
import logging

import pytest

from support.flavors import jwt
from support.live_servers import FakeSseServer, SseScript, connect_reply, pub_message, sse_data
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import StatusFailureError
from whitemarket.live._envelope import Ping, Publication
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


def connection(server: FakeSseServer) -> SseConnection:
    return SseConnection(server.url, "test-agent/1", LiveOptions(), trust_env=False)


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


@pytest.mark.parametrize(
    "first", [b"data: {}\n\n", b"data: nope\n\n"], ids=["not-a-connect-reply", "not-json"]
)
async def test_a_first_message_that_is_not_a_connect_reply_is_a_transport_error(
    first: bytes,
) -> None:
    async with FakeSseServer([SseScript(steps=[first])]) as server:
        with pytest.raises(TransportError):
            await connection(server).open(Secret(TOKEN), [], 5.0)


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
        conn = SseConnection(server.url, "ua", LiveOptions(max_message_bytes=1024), trust_env=False)
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
