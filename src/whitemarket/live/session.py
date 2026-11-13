"""`LiveSession`: live updates for the sync `WhiteMarketClient` (SDK_SPEC 3.11, ADR 0005).

The connection code is async (the Centrifugo client is asyncio-only). This session runs the
async engine on a private event loop in a background thread and is driven by blocking calls
from the caller's thread: `connect()`, `poll(timeout)`, `run()`, iteration, `close()`. Handlers
and lifecycle callbacks run on the CALLER's thread, inside the call that returned the event, so
an exception from one propagates to the caller exactly as in the async session.
"""

import asyncio
import threading
from collections import deque
from collections.abc import Callable, Coroutine, Iterator
from concurrent.futures import Future
from types import TracebackType
from typing import Any, Self, TypeVar

from whitemarket._runtime.secret import Secret
from whitemarket._sync.tokens import TokenProvider
from whitemarket.live._connection import Connection
from whitemarket.live._engine import Engine
from whitemarket.live._handlers import LiveDisconnected, LiveHandlers
from whitemarket.live._registry import Registry
from whitemarket.live.async_session import build_connection
from whitemarket.live.events import DealEvent, LiveEvent
from whitemarket.live.options import LiveOptions, LiveTransport

_T = TypeVar("_T")
_JOIN_SECONDS = 10.0


class _ThreadTokens:
    """The sync token provider, called off the loop thread (a blocking exchange must not stall)."""

    def __init__(self, provider: TokenProvider) -> None:
        self._provider = provider

    async def access_token(self) -> Secret:
        return await asyncio.to_thread(self._provider.access_token)

    async def refresh(self) -> Secret:
        return await asyncio.to_thread(self._provider.refresh)


class _QueueSink:
    """Collects what the engine reports (on the loop thread); the caller's thread dispatches it."""

    def __init__(self) -> None:
        self.pending: deque[Callable[[LiveHandlers], Coroutine[Any, Any, None]]] = deque()

    async def event(self, event: LiveEvent) -> None:
        self.pending.append(lambda handlers: handlers.event(event))

    async def connecting(self) -> None:
        self.pending.append(lambda handlers: handlers.connecting())

    async def connected(self, reconnected: bool) -> None:
        self.pending.append(lambda handlers: handlers.connected(reconnected))

    async def disconnected(self, info: LiveDisconnected) -> None:
        self.pending.append(lambda handlers: handlers.disconnected(info))

    async def error(self, error: Exception) -> None:
        self.pending.append(lambda handlers: handlers.error(error))


def _run_plain(coroutine: Coroutine[Any, Any, None]) -> None:
    """Run a notification whose handlers are plain functions, right here (no event loop: the caller
    may be inside one). A handler that returns an awaitable would suspend it: refused."""
    try:
        coroutine.send(None)
    except StopIteration:
        return
    coroutine.close()
    raise TypeError("handlers of the sync live session must be plain functions, not coroutines")


class _Loop:
    """An event loop on its own daemon thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="whitemarket-live", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coroutine: Coroutine[Any, Any, _T]) -> "Future[_T]":
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def call_soon(self, callback: Callable[..., None], *args: Any) -> None:
        self._loop.call_soon_threadsafe(callback, *args)

    def stop(self) -> None:
        if not self._thread.is_alive():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(_JOIN_SECONDS)
        if not self._thread.is_alive():
            self._loop.close()


class LiveSession(Registry):
    """One live session, driven by blocking calls. One consumer thread at a time; `close()` may
    be called from any thread. Use it as a context manager or call `close()`: that stops the
    background thread."""

    def __init__(
        self,
        *,
        tokens: TokenProvider,
        transport: LiveTransport,
        ws_url: str,
        sse_url: str,
        user_agent: str,
        options: LiveOptions | None = None,
    ) -> None:
        self._sink = _QueueSink()
        self._handlers = LiveHandlers()
        self._options = options or LiveOptions()
        self._connection: Connection = build_connection(
            transport,
            ws_url=ws_url,
            sse_url=sse_url,
            user_agent=user_agent,
            options=self._options,
        )
        self._tokens = _ThreadTokens(tokens)
        self._loop: _Loop | None = None
        self._engine = Engine(
            tokens=self._tokens,
            connection=self._connection,
            options=self._options,
            sink=self._sink,
        )
        self._closed = False
        self._lock = threading.Lock()
        super().__init__(self._handlers, self._subscribe_channel)

    @classmethod
    def create(
        cls,
        *,
        tokens: TokenProvider,
        transport: LiveTransport,
        ws_url: str,
        sse_url: str,
        user_agent: str,
        options: LiveOptions | None = None,
    ) -> Self:
        return cls(
            tokens=tokens,
            transport=transport,
            ws_url=ws_url,
            sse_url=sse_url,
            user_agent=user_agent,
            options=options,
        )

    def _subscribe_channel(self, channel: str) -> None:
        with self._lock:
            loop = self._loop
        if loop is None:
            self._engine.subscribe(channel)
        else:  # the engine belongs to the loop thread once it runs
            loop.call_soon(self._engine.subscribe, channel)

    def _started(self) -> tuple[_Loop, Engine]:
        with self._lock:
            if self._loop is None:
                self._loop = _Loop()
            return self._loop, self._engine

    def _call(self, make: Callable[[Engine], Coroutine[Any, Any, _T]]) -> _T:
        loop, engine = self._started()
        try:
            return loop.submit(make(engine)).result()
        finally:
            self._dispatch()

    def _dispatch(self) -> None:
        """Run what the engine reported, in order, on this thread; an exception propagates and
        the rest waits for the next call."""
        while self._sink.pending:
            notify = self._sink.pending.popleft()
            _run_plain(notify(self._handlers))

    def connect(self) -> None:
        """Connect now and return once connected; terminal failures raise."""
        self._call(lambda engine: engine.connect())

    def poll(self, timeout: float | None = None) -> LiveEvent | None:
        """The next event after its handlers ran, `None` after `timeout` seconds or once closed."""
        if timeout is not None and not timeout >= 0:
            raise ValueError("timeout must be a number of seconds, 0 or more")
        return self._call(lambda engine: engine.poll(timeout))

    def run(self, duration: float | None = None) -> None:
        """Dispatch events to the handlers for `duration` seconds (`None`: until `close()`)."""
        if duration is not None and not duration >= 0:
            raise ValueError("duration must be a number of seconds, 0 or more")
        _, engine = self._started()
        until = None if duration is None else engine.now() + duration
        while not self._closed and not engine.closed:
            remaining = None if until is None else until - engine.now()
            if remaining is not None and remaining <= 0:
                return
            self.poll(remaining)

    def __iter__(self) -> Iterator[LiveEvent]:
        while True:
            event = self.poll(None)
            if event is None:
                return
            yield event

    def wait_for_deal_event(self, deal_id: str, timeout: float) -> DealEvent | None:
        """The next deal event of `deal_id`, or `None` after `timeout` seconds (or once closed).

        For `deals.wait_for(..., live=session)`; see `AsyncLiveSession.wait_for_deal_event`.
        """
        if not timeout >= 0:
            raise ValueError("timeout must be a number of seconds, 0 or more")
        _, engine = self._started()
        until = engine.now() + timeout
        while not self._closed and not engine.closed:
            remaining = until - engine.now()
            if remaining <= 0:
                return None
            event = self.poll(remaining)
            if isinstance(event, DealEvent) and event.deal_id == deal_id:
                return event
        return None

    def close(self) -> None:
        """Close the connection and stop the background thread. Idempotent, any thread."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, engine = self._loop, self._engine
        if loop is None:
            return
        try:
            loop.submit(engine.close()).result()
        finally:
            loop.stop()
            self._dispatch()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
