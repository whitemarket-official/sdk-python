"""`AsyncLiveSession`: live updates for `AsyncWhiteMarketClient` (SDK_SPEC 3.11)."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Self

from whitemarket.live import _policy as policy
from whitemarket.live._connection import Connection, build_connection
from whitemarket.live._engine import Engine, TokenSource
from whitemarket.live._handlers import LiveHandlers
from whitemarket.live._registry import Registry
from whitemarket.live.events import DealEvent, LiveEvent
from whitemarket.live.options import LiveOptions, LiveTransport


class AsyncLiveSession(Registry):
    """One live session. Register handlers, then `await connect()` or consume events with
    `async for event in session`, `await session.poll(timeout)` or `await session.run()`.

    All work happens inside those calls, on the calling task: one consumer at a time, and a
    handler exception propagates out of the call that dispatched it. `await close()` (or
    `async with`) closes the connection and stops everything. See ADR 0005.
    """

    def __init__(
        self,
        *,
        tokens: TokenSource,
        connection: Connection,
        options: LiveOptions | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = policy.SYSTEM_RANDOM,
    ) -> None:
        handlers = LiveHandlers()
        self._engine = Engine(
            tokens=tokens,
            connection=connection,
            options=options or LiveOptions(),
            sink=handlers,
            clock=clock,
            sleeper=sleeper,
            random_source=random_source,
        )
        super().__init__(handlers, self._engine.subscribe)

    @classmethod
    def create(
        cls,
        *,
        tokens: TokenSource,
        transport: LiveTransport,
        ws_url: str,
        sse_url: str,
        user_agent: str,
        options: LiveOptions | None = None,
    ) -> Self:
        opts = options or LiveOptions()
        connection = build_connection(
            transport, ws_url=ws_url, sse_url=sse_url, user_agent=user_agent, options=opts
        )
        return cls(tokens=tokens, connection=connection, options=opts)

    async def connect(self) -> None:
        """Connect now and return once connected (backoffs are waited out); failures raise."""
        await self._engine.connect()

    async def poll(self, timeout: float | None = None) -> LiveEvent | None:
        """The next event after its handlers ran, `None` after `timeout` seconds or once closed."""
        policy.check_seconds("timeout", timeout)
        return await self._engine.poll(timeout)

    async def run(self, duration: float | None = None) -> None:
        """Dispatch events to the handlers for `duration` seconds (`None`: until `close()`)."""
        policy.check_seconds("duration", duration)
        until = None if duration is None else self._engine.now() + duration
        while not self._engine.closed:
            remaining = None if until is None else until - self._engine.now()
            if remaining is not None and remaining <= 0:
                return
            await self._engine.poll(remaining)

    def __aiter__(self) -> AsyncIterator[LiveEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[LiveEvent]:
        while not self._engine.closed:
            event = await self._engine.poll(None)
            if event is not None:
                yield event

    async def wait_for_deal_event(self, deal_id: str, timeout: float) -> DealEvent | None:
        """The next deal event of `deal_id`, or `None` after `timeout` seconds (or once closed).

        For `deals.wait_for(..., live=session)`: wake up on the event, then fetch the GraphQL
        state. Other events met on the way are dispatched to the handlers as usual. It consumes
        the session like `poll()` does: do not run another consumer at the same time. A live
        event is a hint, never the state.
        """
        policy.check_seconds("timeout", timeout)
        until = self._engine.now() + timeout
        while not self._engine.closed:
            remaining = until - self._engine.now()
            if remaining <= 0:
                return None
            event = await self._engine.poll(remaining)
            if isinstance(event, DealEvent) and event.deal_id == deal_id:
                return event
        return None

    async def close(self) -> None:
        """Close the connection and stop all work. Idempotent; may be called from a handler or
        another task."""
        await self._engine.close()

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
