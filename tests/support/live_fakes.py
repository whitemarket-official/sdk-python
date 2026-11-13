"""Scripted connection, clock and token source for the live session tests (no IO, no real time)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from whitemarket._runtime.secret import Secret
from whitemarket.live._connection import Incoming
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.live.options import LiveOptions

DEFAULT_INFO = ConnectInfo(ping=25, pong=True, ttl=None)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class Wait:
    """Time passes on the connection before the next item (a quiet connection)."""

    seconds: float


class FakeTokens:
    def __init__(self) -> None:
        self.access_calls = 0
        self.refresh_calls = 0
        self.access_error: Exception | None = None
        self.refresh_error: Exception | None = None

    async def access_token(self) -> Secret:
        self.access_calls += 1
        if self.access_error is not None:
            raise self.access_error
        return Secret(f"jwt-access-{self.access_calls}")

    async def refresh(self) -> Secret:
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error
        return Secret(f"jwt-refresh-{self.refresh_calls}")


@dataclass
class FakeConnection:
    """`opens` has one outcome per `open()` (an Exception is raised); `reads[i]` is what the i-th
    successful connection yields: messages, exceptions to raise or `Wait`. A quiet connection (empty
    script) lets the read deadline pass."""

    clock: FakeClock
    can_subscribe_after_connect: bool = True
    opens: list[ConnectInfo | Exception] = field(default_factory=list)
    reads: list[list[Any]] = field(default_factory=list)
    open_calls: list[tuple[str, list[str]]] = field(default_factory=list)
    open_times: list[float] = field(default_factory=list)
    closes: int = 0
    subscribed: list[str] = field(default_factory=list)
    block: asyncio.Event | None = None  # when set, `read` waits for it (a blocked consumer)
    _current: int = -1

    async def open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo:
        self.open_calls.append((token.reveal(), list(channels)))
        self.open_times.append(self.clock.now)
        outcome = self.opens.pop(0) if self.opens else DEFAULT_INFO
        if isinstance(outcome, Exception):
            raise outcome
        self._current += 1
        return outcome

    async def read(self, seconds: float | None) -> Incoming | None:
        if self.block is not None:
            await self.block.wait()
            return None
        script = self.reads[self._current] if 0 <= self._current < len(self.reads) else []
        while script and isinstance(script[0], Wait):
            self.clock.now += script.pop(0).seconds
        if not script:
            assert seconds is not None, "the session would block forever"
            self.clock.now += seconds
            return None
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def close(self) -> None:
        self.closes += 1


@dataclass
class Rig:
    clock: FakeClock
    connection: FakeConnection
    tokens: FakeTokens
    session: AsyncLiveSession
    calls: list[tuple[str, Any]]


def make_rig(
    *, can_subscribe: bool = True, options: LiveOptions | None = None, random_value: float = 1.0
) -> Rig:
    clock = FakeClock()
    connection = FakeConnection(clock, can_subscribe_after_connect=can_subscribe)
    tokens = FakeTokens()
    session = AsyncLiveSession(
        tokens=tokens,
        connection=connection,
        options=options,
        clock=clock,
        sleeper=clock.sleep,
        random_source=lambda: random_value,
    )
    calls: list[tuple[str, Any]] = []
    session.on_connecting(lambda: calls.append(("connecting", None)))
    session.on_connected(lambda reconnected: calls.append(("connected", reconnected)))
    session.on_disconnected(lambda info: calls.append(("disconnected", info)))
    session.on_error(lambda error: calls.append(("error", error)))
    return Rig(clock, connection, tokens, session, calls)
