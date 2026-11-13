"""Callback registry of a live session: event handlers and lifecycle callbacks."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from whitemarket.live.events import LiveEvent

EventHandler = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class LiveDisconnected:
    """Why a connection ended. `code` is the close or disconnect code (`None`: none, e.g. a read
    failure or `close()`); `reason` is server text reduced to printable ASCII (not redacted);
    `will_reconnect` is False when the session ends."""

    code: int | None
    reason: str
    will_reconnect: bool


async def settle(result: object) -> None:
    """Await a callback's result when it is awaitable (an `async def` handler)."""
    if inspect.isawaitable(result):
        await result


class LiveHandlers:
    """Handlers in registration order. A handler's exception propagates to the caller."""

    def __init__(self) -> None:
        self._events: list[tuple[EventHandler, Callable[[str], bool] | None]] = []
        self._connecting: list[Callable[[], Any]] = []
        self._connected: list[Callable[[bool], Any]] = []
        self._disconnected: list[Callable[[LiveDisconnected], Any]] = []
        self._errors: list[Callable[[Exception], Any]] = []

    def add_event(
        self, handler: EventHandler, accepts_channel: Callable[[str], bool] | None = None
    ) -> None:
        self._events.append((handler, accepts_channel))

    def add_connecting(self, handler: Callable[[], Any]) -> None:
        self._connecting.append(handler)

    def add_connected(self, handler: Callable[[bool], Any]) -> None:
        self._connected.append(handler)

    def add_disconnected(self, handler: Callable[[LiveDisconnected], Any]) -> None:
        self._disconnected.append(handler)

    def add_error(self, handler: Callable[[Exception], Any]) -> None:
        self._errors.append(handler)

    async def event(self, event: LiveEvent) -> None:
        for handler, accepts in list(self._events):
            if accepts is None or accepts(event.channel):
                await settle(handler(event))

    async def connecting(self) -> None:
        for handler in list(self._connecting):
            await settle(handler())

    async def connected(self, reconnected: bool) -> None:
        for handler in list(self._connected):
            await settle(handler(reconnected))

    async def disconnected(self, info: LiveDisconnected) -> None:
        for handler in list(self._disconnected):
            await settle(handler(info))

    async def error(self, error: Exception) -> None:
        for handler in list(self._errors):
            await settle(handler(error))
