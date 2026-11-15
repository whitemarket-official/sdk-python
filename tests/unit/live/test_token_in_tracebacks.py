"""The live token must not be reachable from a raised error: no traceback frame, no exception in
the `__context__` / `__cause__` chain may hold it in a local (a log handler or an error tracker
that captures locals would leak it)."""

import asyncio
import traceback
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

import whitemarket
from support.flavors import jwt
from support.live_servers import FakeCentrifugoServer, FakeSseServer, FakeWsConnection, SseScript
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import LiveConnectionError, TransportError, WhiteMarketError
from whitemarket.live._sse import SseConnection
from whitemarket.live._ws import WsConnection
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.live.options import LiveOptions

ISSUED: list[str] = []
_SDK_DIR = Path(whitemarket.__file__).parent


class _Tokens:
    """Synthetic JWTs; every issued one is remembered to look for in the error."""

    def __init__(self) -> None:
        self.issued = asyncio.Event()

    async def access_token(self) -> Secret:
        return await self.refresh()

    async def refresh(self) -> Secret:
        token = jwt(exp=4_000_000_000, sub=f"synthetic-{len(ISSUED)}")
        ISSUED.append(token)
        self.issued.set()
        return Secret(token)


def _chain_text(error: BaseException) -> str:
    """Every frame local of every exception on the chain, as a traceback tool would print it,
    plus every string reachable from those locals (`Response.request.url` is not in a `repr`)."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(
            "".join(
                traceback.TracebackException.from_exception(current, capture_locals=True).format()
            )
        )
        parts.extend(_reachable_strings(current))
        tb = current.__traceback__
        while tb is not None:
            sdk_frame = _SDK_DIR in Path(tb.tb_frame.f_code.co_filename).parents
            for value in tb.tb_frame.f_locals.values():
                parts.append(repr(value))
                if sdk_frame:  # a test frame holds the fake server, which records the token
                    parts.extend(_reachable_strings(value))
            tb = tb.tb_next
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def _reachable_strings(root: object, depth: int = 8, budget: int = 50_000) -> list[str]:
    """Strings reachable from `root` through attributes, slots and containers (bounded)."""
    found: list[str] = []
    seen: set[int] = set()
    stack: list[tuple[object, int]] = [(root, 0)]
    while stack and len(seen) < budget:
        value, level = stack.pop()
        if id(value) in seen or level > depth:
            continue
        seen.add(id(value))
        if isinstance(value, str):
            found.append(value)
            continue
        if isinstance(value, bytes | bytearray):
            found.append(bytes(value).decode("latin-1"))
            continue
        # `Secret` is the sanctioned holder (it never prints its value), so it is not walked.
        if isinstance(value, Secret | type) or (callable(value) and not hasattr(value, "__dict__")):
            continue
        children: list[object] = []
        if isinstance(value, dict):
            children.extend(value.keys())
            children.extend(value.values())
        elif isinstance(value, list | tuple | set | frozenset | deque):
            children.extend(value)
        children.extend(getattr(value, "__dict__", {}).values())
        for klass in type(value).__mro__:
            for slot in getattr(klass, "__slots__", ()):
                if isinstance(slot, str) and hasattr(value, slot):
                    children.append(getattr(value, slot))
        stack.extend((child, level + 1) for child in children)
    return found


def _token_part(text: str) -> bool:
    return any(token in text for token in ISSUED)


@pytest.fixture(autouse=True)
def _reset_issued() -> None:
    ISSUED.clear()


async def _until_terminal(session: AsyncLiveSession) -> None:
    await session.connect()
    while True:  # a server close after a good connect surfaces from poll()
        await session.poll(5)


async def _failure(session: AsyncLiveSession) -> BaseException:
    with pytest.raises(WhiteMarketError) as caught:
        await _until_terminal(session)
    assert ISSUED, "the scenario must have issued a token"
    return caught.value


async def test_ws_upgrade_403_twice_keeps_the_token_out_of_the_error() -> None:
    async with FakeCentrifugoServer([], upgrade_status={0: (403, {}), 1: (403, {})}) as server:
        session = AsyncLiveSession(
            tokens=_Tokens(), connection=WsConnection(server.url, "ua", proxy=None)
        )
        error = await _failure(session)
        await session.close()
    assert not _token_part(_chain_text(error))


async def test_ws_rejected_token_twice_keeps_the_token_out_of_the_error() -> None:
    async def reject(connection: FakeWsConnection) -> None:
        await connection.accept_connect()
        await connection.ws.close(3500, "bad")

    async with FakeCentrifugoServer([reject, reject]) as server:
        session = AsyncLiveSession(
            tokens=_Tokens(), connection=WsConnection(server.url, "ua", proxy=None)
        )
        error = await _failure(session)
        await session.close()
    assert not _token_part(_chain_text(error))


async def test_sse_401_twice_keeps_the_token_out_of_the_error() -> None:
    async with FakeSseServer([SseScript(status=401), SseScript(status=401)]) as server:
        session = AsyncLiveSession(
            tokens=_Tokens(), connection=SseConnection(server.url, "ua", LiveOptions())
        )
        error = await _failure(session)
        await session.close()
    assert not _token_part(_chain_text(error))


async def test_sse_exhausted_attempts_keep_the_token_out_of_the_error() -> None:
    async with FakeSseServer([SseScript(status=500)] * 3) as server:
        session = AsyncLiveSession(
            tokens=_Tokens(),
            connection=SseConnection(server.url, "ua", LiveOptions()),
            options=LiveOptions(max_reconnect_attempts=1),
            sleeper=_no_sleep,
        )
        errors: list[Exception] = []
        session.on_error(errors.append)
        error = await _failure(session)
        await session.close()
    assert not _token_part("\n".join(_chain_text(e) for e in [error, *errors]))


async def _no_sleep(seconds: float) -> None:
    del seconds


async def _start_silent_server() -> tuple[asyncio.Server, str]:
    """A server that accepts the connection and never answers; returns it and its SSE URL."""

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}/sse"


async def test_an_sse_connect_timeout_during_the_request_keeps_the_token_out_of_the_error() -> None:
    # The server accepts the connection and never answers: the timeout fires inside the request,
    # whose frame holds the URL with the token (on Windows a refused connect takes that long too).
    server, url = await _start_silent_server()
    connection = SseConnection(url, "ua", LiveOptions(), trust_env=False)
    try:
        with pytest.raises(TransportError, match="no connect reply in time") as caught:
            await connection.open(await _Tokens().access_token(), [], 0.3)
    finally:
        await connection.close()
        server.close()
        await server.wait_closed()
    assert caught.value.__context__ is None
    assert not _token_part(_chain_text(caught.value))


async def test_a_ws_connect_timeout_keeps_the_token_out_of_the_error() -> None:
    async with FakeCentrifugoServer([FakeWsConnection.hold]) as server:
        connection = WsConnection(server.url, "ua", proxy=None)
        try:
            with pytest.raises(TransportError, match="no connect reply in time") as caught:
                await connection.open(await _Tokens().access_token(), [], 0.3)
        finally:
            await connection.close()
    assert caught.value.__context__ is None
    assert not _token_part(_chain_text(caught.value))


class _Opaque:
    """Holds a value behind a `repr` that does not show it, as `httpx.Response` does."""

    __slots__ = ("inner",)

    def __init__(self, inner: object) -> None:
        self.inner = inner

    def __repr__(self) -> str:
        return "<opaque>"


def test_the_detector_finds_a_token_behind_attributes_and_containers() -> None:
    # Control check for `_reachable_strings`: not visible in any `repr`, only by walking.
    token = jwt(exp=4_000_000_000, sub="synthetic-control")
    ISSUED.append(token)
    holder = _Opaque(SimpleNamespace(url={"query": [_Opaque(token.encode())]}))
    assert not _token_part(repr(holder))
    assert _token_part("\n".join(_reachable_strings(holder)))


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/sse\x00", id="NUL in the path -> httpx.InvalidURL"),
        pytest.param("/sse\x7f", id="DEL in the path -> httpx.InvalidURL"),
    ],
)
async def test_an_sse_url_httpx_refuses_keeps_the_token_out_of_the_error(path: str) -> None:
    # `Endpoints` accepts such a URL (`urlsplit` does), httpx refuses it while building the
    # request with the token in the query; `httpx.InvalidURL` is not an `httpx.HTTPError`.
    session = AsyncLiveSession(
        tokens=_Tokens(),
        connection=SseConnection(f"http://127.0.0.1:9{path}", "ua", LiveOptions()),
        options=LiveOptions(max_reconnect_attempts=1),
        sleeper=_no_sleep,
    )
    errors: list[Exception] = []
    session.on_error(errors.append)
    error = await _failure(session)
    await session.close()
    assert isinstance(error, LiveConnectionError)
    assert [str(e) for e in errors] == ["the live HTTP request failed (InvalidURL)"]
    assert not _token_part("\n".join(_chain_text(e) for e in [error, *errors]))


async def _cancelled_connect(session: AsyncLiveSession, tokens: _Tokens) -> BaseException:
    task = asyncio.create_task(session.connect())
    await tokens.issued.wait()
    await asyncio.sleep(0.1)  # the request is in flight
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    await session.close()
    return caught.value


async def test_cancelling_an_sse_connect_keeps_the_token_out_of_the_error() -> None:
    server, url = await _start_silent_server()
    try:
        tokens = _Tokens()
        session = AsyncLiveSession(
            tokens=tokens, connection=SseConnection(url, "ua", LiveOptions(), trust_env=False)
        )
        error = await _cancelled_connect(session, tokens)
    finally:
        server.close()
        await server.wait_closed()
    assert not _token_part(_chain_text(error))


async def test_cancelling_a_ws_connect_keeps_the_token_out_of_the_error() -> None:
    async with FakeCentrifugoServer([FakeWsConnection.hold]) as server:
        tokens = _Tokens()
        session = AsyncLiveSession(
            tokens=tokens, connection=WsConnection(server.url, "ua", proxy=None)
        )
        error = await _cancelled_connect(session, tokens)
    assert not _token_part(_chain_text(error))
