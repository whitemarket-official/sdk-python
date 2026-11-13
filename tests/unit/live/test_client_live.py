"""`client.live()` wiring on both clients."""

import pytest

from support.flavors import jwt
from whitemarket import AsyncWhiteMarketClient, LiveOptions, LiveTransport, WhiteMarketClient
from whitemarket.live import AsyncLiveSession, LiveSession
from whitemarket.live._sse import SseConnection
from whitemarket.live._ws import WsConnection

ACCESS = jwt(exp=4_000_000_000)


def test_sync_client_live_returns_a_threaded_session_with_the_endpoint_of_the_transport() -> None:
    client = WhiteMarketClient(access_token=ACCESS, base_url="https://example.test")
    sse = client.live(LiveTransport.SSE, LiveOptions(connect_timeout=2.0))
    ws = client.live()
    assert isinstance(sse, LiveSession)
    assert isinstance(sse._connection, SseConnection)
    assert sse._connection._url == "https://example.test/sse_endpoint"
    assert isinstance(ws._connection, WsConnection)
    assert ws._connection._url == "wss://example.test/ws_endpoint"


async def test_async_client_live_returns_the_async_session() -> None:
    client = AsyncWhiteMarketClient(access_token=ACCESS, base_url="https://example.test")
    session = client.live(LiveTransport.SSE)
    assert isinstance(session, AsyncLiveSession)
    await session.close()
    await client.aclose()


def test_live_options_are_validated() -> None:
    with pytest.raises(ValueError, match="connect_timeout"):
        LiveOptions(connect_timeout=0)
    with pytest.raises(ValueError, match="max_message_bytes"):
        LiveOptions(max_message_bytes=10)
    with pytest.raises(ValueError, match="max_reconnect_attempts"):
        LiveOptions(max_reconnect_attempts=0)
