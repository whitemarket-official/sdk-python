"""Whole sessions over the fake servers: reconnect, resubscribe, token refresh, close, threads."""

import asyncio
import threading
import time
from typing import Any

import pytest

from support.flavors import jwt
from support.live_fakes import FakeTokens
from support.live_servers import (
    PRODUCT_CONTENT,
    FakeCentrifugoServer,
    FakeSseServer,
    FakeWsConnection,
    SseScript,
    connect_reply,
    pub_message,
    sse_data,
)
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import LiveConnectionError
from whitemarket.errors.http import AuthenticationError, HttpError
from whitemarket.live import (
    AsyncLiveSession,
    DealOffered,
    LiveOptions,
    LiveSession,
    LiveTransport,
    ProductAdded,
)
from whitemarket.live._sse import SseConnection
from whitemarket.live._ws import WsConnection

PRODUCTS = "market_products_updates"
DEAL = {"deal_id": "d1", "deal_action_type": "sell", "market_product_name": "AK"}


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


class JwtTokens(FakeTokens):
    """Hands out distinct, syntactically valid JWTs (a 24 h token)."""

    async def access_token(self) -> Secret:
        await super().access_token()
        return Secret(jwt(exp=4_000_000_000, n=self.access_calls))

    async def refresh(self) -> Secret:
        await super().refresh()
        return Secret(jwt(exp=4_000_000_000, r=self.refresh_calls))


def ws_session(server: FakeCentrifugoServer, tokens: FakeTokens) -> AsyncLiveSession:
    return AsyncLiveSession(
        tokens=tokens,
        connection=WsConnection(server.url, "ua", proxy=None),
        options=LiveOptions(connect_timeout=3.0),
        sleeper=lambda seconds: asyncio.sleep(0),  # no real backoff waits
    )


async def test_ws_session_receives_products_and_personal_events_without_subscribing_personal() -> (
    None
):
    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect(subs=("broadcast", "#42"))
        await c.accept_subscribes(1)
        await c.send({"push": pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT)})
        await c.send({"push": pub_message("#42", "market_deal_offered", DEAL)}, {})
        await c.hold()

    async with FakeCentrifugoServer([script]) as server:
        session = ws_session(server, JwtTokens())
        products: list[Any] = []
        personal: list[Any] = []
        session.subscribe_products(products.append)
        session.subscribe_personal(personal.append)
        async with session:
            await session.poll(3)
            await session.poll(3)
    assert [type(e) for e in products] == [ProductAdded]
    assert [type(e) for e in personal] == [DealOffered]
    channels = [
        c["subscribe"]["channel"] for c in server.connections[0].commands if "subscribe" in c
    ]
    assert channels == [PRODUCTS]


async def test_ws_reconnect_resubscribes_uses_a_fresh_token_and_flags_reconnected() -> None:
    async def first(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(3000, "reconnect please")

    async def second(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.send({"push": pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT)})
        await c.hold()

    tokens = JwtTokens()
    async with FakeCentrifugoServer([first, second]) as server:
        session = ws_session(server, tokens)
        session.subscribe_products()
        flags: list[bool] = []
        session.on_connected(flags.append)
        async with session:
            event = await session.poll(5)
    assert isinstance(event, ProductAdded)
    assert flags == [False, True]
    connects = [conn.commands[0]["connect"]["token"] for conn in server.connections]
    assert connects[0] != connects[1]  # a fresh token for every connect
    assert all(any("subscribe" in c for c in conn.commands) for conn in server.connections)
    assert tokens.access_calls == 2


async def test_ws_token_rejection_refreshes_once_then_the_second_is_terminal() -> None:
    async def reject(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(3500, "invalid token")

    tokens = JwtTokens()
    async with FakeCentrifugoServer([reject]) as server:
        session = ws_session(server, tokens)
        session.subscribe_products()
        with pytest.raises(AuthenticationError):
            await session.poll(10)
    assert tokens.refresh_calls == 1
    assert len(server.connections) == 2


async def test_ws_unknown_close_codes_end_the_session_on_the_sixth_in_a_row() -> None:
    async def drop(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.close(1001, "going away")

    async with FakeCentrifugoServer([drop]) as server:
        session = ws_session(server, JwtTokens())
        session.subscribe_products()
        with pytest.raises(LiveConnectionError) as caught:
            await session.poll(30)
    assert caught.value.code == 1  # the library reports every close below 3000 as code 1
    assert len(server.connections) == 6


async def test_ws_close_leaves_no_task_and_no_open_socket() -> None:
    gone = asyncio.Event()

    async def script(c: FakeWsConnection) -> None:
        await c.accept_connect()
        await c.accept_subscribes(1)
        await c.ws.wait_closed()
        gone.set()

    before = set(asyncio.all_tasks())
    async with FakeCentrifugoServer([script]) as server:
        session = ws_session(server, JwtTokens())
        session.subscribe_products()
        await session.connect()
        await session.close()
        await asyncio.wait_for(gone.wait(), 10)
    assert set(asyncio.all_tasks()) - before - {asyncio.current_task()} == set()


def sse_session(server: FakeSseServer, tokens: FakeTokens) -> AsyncLiveSession:
    options = LiveOptions(connect_timeout=3.0)
    return AsyncLiveSession(
        tokens=tokens,
        connection=SseConnection(server.url, "ua", options, trust_env=False),
        options=options,
        sleeper=lambda seconds: asyncio.sleep(0),
    )


async def test_sse_reconnects_after_the_stream_ends_and_resends_the_channel_list() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    scripts = [
        SseScript(steps=[sse_data(connect_reply())], hold=False),
        SseScript(steps=[sse_data(connect_reply()), message]),
    ]
    tokens = JwtTokens()
    async with FakeSseServer(scripts) as server:
        session = sse_session(server, tokens)
        session.subscribe_products()
        reconnected: list[bool] = []
        session.on_connected(reconnected.append)
        async with session:
            event = await session.poll(5)
    assert isinstance(event, ProductAdded)
    assert reconnected == [False, True]
    assert len(server.requests) == 2
    assert all(r["query"]["cf_connect"][0].count(PRODUCTS) == 1 for r in server.requests)


async def test_sse_401_refreshes_once_and_a_second_401_is_an_authentication_error() -> None:
    tokens = JwtTokens()
    async with FakeSseServer([SseScript(status=401)]) as server:
        session = sse_session(server, tokens)
        with pytest.raises(AuthenticationError):
            await session.poll(5)
    assert tokens.refresh_calls == 1
    assert len(server.requests) == 2


async def test_sse_close_leaves_no_task_and_releases_the_stream() -> None:
    before = set(asyncio.all_tasks())
    async with FakeSseServer([SseScript(steps=[sse_data(connect_reply())])]) as server:
        session = sse_session(server, JwtTokens())
        await session.connect()
        await session.close()
        for _ in range(100):
            if server.open_streams == 0:
                break
            await asyncio.sleep(0.02)
        assert server.open_streams == 0
    assert set(asyncio.all_tasks()) - before - {asyncio.current_task()} == set()


# --- the sync (threaded) session ------------------------------------------------------------


class SyncTokens:
    def __init__(self) -> None:
        self.calls = 0

    def access_token(self) -> Secret:
        self.calls += 1
        return Secret(jwt(exp=4_000_000_000, n=self.calls))

    def refresh(self) -> Secret:
        return self.access_token()


def sync_sse(server_url: str) -> LiveSession:
    return LiveSession(
        tokens=SyncTokens(),
        transport=LiveTransport.SSE,
        ws_url="wss://unused.invalid/ws_endpoint",
        sse_url=server_url,
        user_agent="ua",
        options=LiveOptions(connect_timeout=3.0),
    )


def live_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "whitemarket-live"]


class ServerThread:
    """A fake SSE server on its own loop thread, for tests that block the main thread."""

    def __init__(self, scripts: list[SseScript]) -> None:
        self.server = FakeSseServer(scripts)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self) -> FakeSseServer:
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.server.__aenter__(), self.loop).result(5)
        return self.server

    def __exit__(self, *exc: object) -> None:
        asyncio.run_coroutine_threadsafe(self.server.__aexit__(None, None, None), self.loop).result(
            5
        )
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def test_sync_session_polls_dispatches_on_the_caller_thread_and_close_stops_the_thread() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    with ServerThread([SseScript(steps=[sse_data(connect_reply()), message])]) as server:
        session = sync_sse(server.url)
        handler_threads: list[threading.Thread] = []
        session.subscribe_products(lambda e: handler_threads.append(threading.current_thread()))
        with session:
            event = session.poll(5)
            assert isinstance(event, ProductAdded)
            assert session.poll(0.2) is None
            assert len(live_threads()) == 1
        assert handler_threads == [threading.current_thread()]
    assert live_threads() == []


def test_sync_handler_exception_propagates_out_of_poll_and_the_connection_stays_open() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    with ServerThread([SseScript(steps=[sse_data(connect_reply()), message, message])]) as server:
        session = sync_sse(server.url)

        def boom(event: Any) -> None:
            raise RuntimeError("handler failed")

        session.on(ProductAdded, boom)
        with session:
            with pytest.raises(RuntimeError, match="handler failed"):
                session.poll(5)
            with pytest.raises(RuntimeError, match="handler failed"):
                session.poll(5)
            assert len(server.requests) == 1
    assert live_threads() == []


def test_sync_iteration_ends_when_close_is_called_from_another_thread() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    with ServerThread([SseScript(steps=[sse_data(connect_reply()), message])]) as server:
        session = sync_sse(server.url)
        seen: list[Any] = []
        timer = threading.Timer(0.5, session.close)
        timer.start()
        started = time.monotonic()
        for event in session:
            seen.append(event)
        timer.join()
        assert time.monotonic() - started < 5
    assert len(seen) == 1
    assert live_threads() == []


def test_sync_connect_failure_is_raised_to_the_caller() -> None:
    with ServerThread([SseScript(status=403)]) as server:
        session = sync_sse(server.url)
        with session, pytest.raises(HttpError) as caught:
            session.connect()
        assert caught.value.status == 403
    assert live_threads() == []


def test_sync_run_and_wait_for_deal_event_and_argument_checks() -> None:
    deal = {"deal_id": "d9", "deal_action_type": "buy", "market_product_name": "AK"}
    steps = [
        sse_data(connect_reply()),
        sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT)),
        sse_data(pub_message("#42", "market_deal_offered", deal)),
    ]
    with ServerThread([SseScript(steps=steps)]) as server:
        session = sync_sse(server.url)
        seen: list[Any] = []
        session.on(ProductAdded, seen.append)
        session.subscribe_products()  # before the thread exists: sent with the first connect
        with session:
            event = session.wait_for_deal_event("d9", 5.0)
            assert isinstance(event, DealOffered)
            assert len(seen) == 1  # the product event on the way went to its handler
            assert session.wait_for_deal_event("other", 0.2) is None
            session.run(0.2)
            with pytest.raises(ValueError, match="timeout"):
                session.poll(-1.0)
            with pytest.raises(ValueError, match="duration"):
                session.run(float("nan"))
            with pytest.raises(ValueError, match="timeout"):
                session.wait_for_deal_event("d9", -1.0)
        assert PRODUCTS in server.requests[0]["query"]["cf_connect"][0]
    assert live_threads() == []


def test_sync_close_before_use_is_a_noop_and_idempotent() -> None:
    session = sync_sse("http://127.0.0.1:1/sse_endpoint")
    session.close()
    session.close()
    assert live_threads() == []


async def test_sync_session_handlers_run_inside_a_running_event_loop_and_must_be_plain() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    scripts = [SseScript(steps=[sse_data(connect_reply()), message, message])]
    seen: list[Any] = []
    with ServerThread(scripts) as server, sync_sse(server.url) as session:
        session.on(ProductAdded, seen.append)
        # this test runs inside an event loop: the caller's thread must still be able to dispatch
        assert isinstance(await asyncio.to_thread(session.poll, 5), ProductAdded)
        assert isinstance(session.poll(5), ProductAdded)
        assert len(seen) == 2

        async def coroutine_handler(event: Any) -> None:
            return None

        session.on(ProductAdded, coroutine_handler)
    assert live_threads() == []


def test_sync_subscribe_after_start_reaches_the_engine_on_the_loop_thread() -> None:
    message = sse_data(pub_message(PRODUCTS, "market_product_added", PRODUCT_CONTENT))
    with ServerThread(
        [
            SseScript(steps=[sse_data(connect_reply())]),
            SseScript(steps=[sse_data(connect_reply()), message]),
        ]
    ) as server:
        with sync_sse(server.url) as session:
            session.connect()
            session.subscribe_products()  # SSE: reconnects with the new channel list
            event = session.poll(5)
            assert isinstance(event, ProductAdded)
        assert PRODUCTS not in server.requests[0]["query"]["cf_connect"][0]
        assert PRODUCTS in server.requests[1]["query"]["cf_connect"][0]
