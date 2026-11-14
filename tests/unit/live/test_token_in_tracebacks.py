"""The live token must not be reachable from a raised error: no traceback frame, no exception in
the `__context__` / `__cause__` chain may hold it in a local (a log handler or an error tracker
that captures locals would leak it)."""

import traceback

import pytest

from support.flavors import jwt
from support.live_servers import FakeCentrifugoServer, FakeSseServer, FakeWsConnection, SseScript
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import WhiteMarketError
from whitemarket.live._sse import SseConnection
from whitemarket.live._ws import WsConnection
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.live.options import LiveOptions

ISSUED: list[str] = []


class _Tokens:
    """Synthetic JWTs; every issued one is remembered to look for in the error."""

    async def access_token(self) -> Secret:
        return await self.refresh()

    async def refresh(self) -> Secret:
        token = jwt(exp=4_000_000_000, sub=f"synthetic-{len(ISSUED)}")
        ISSUED.append(token)
        return Secret(token)


def _chain_text(error: BaseException) -> str:
    """Every frame local of every exception on the chain, as a traceback tool would print it."""
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
        tb = current.__traceback__
        while tb is not None:
            parts.extend(repr(value) for value in tb.tb_frame.f_locals.values())
            tb = tb.tb_next
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


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
