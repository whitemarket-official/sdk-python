"""WebSocket live connection over the official Centrifugo client (`centrifuge-python`, ADR 0005).

The library is used as the transport and protocol codec of ONE connection attempt: a fresh
`Client` per `open()`, and its own reconnect is switched off by disconnecting it on the first
loss. The session owns every reconnect decision (backoff, close-code rules, token refresh), see
`_engine.py`. The library keeps the ping/pong answers, the idle deadline (`ping + 10 s`),
multi-message frames and resubscribing on its own connection.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

from whitemarket._runtime.jwt import seconds_left
from whitemarket._runtime.secret import Secret
from whitemarket._version import __version__
from whitemarket.errors.base import TransportError
from whitemarket.live._connection import (
    ConnectRejectedError,
    Incoming,
    ServerClosedError,
    StatusFailureError,
)
from whitemarket.live._policy import IDLE_GRACE_SECONDS, ConnectInfo
from whitemarket.live.envelope import Publication, Unsubscribe, printable
from whitemarket.retry import parse_retry_after

try:
    from centrifuge import (
        Client,
        ClientEventHandler,
        ConnectedContext,
        ConnectingContext,
        DisconnectedContext,
        ErrorContext,
        PublicationContext,
        ServerPublicationContext,
        SubscriptionEventHandler,
        UnsubscribedContext,
    )
    from centrifuge import ReplyError as CentrifugeReplyError
    from websockets.exceptions import InvalidStatus
except ImportError as error:
    raise ImportError(
        "WebSocket live updates need the `live` extra: pip install 'whitemarket-sdk[live]'"
    ) from error

# Publications waiting for the consumer. The library awaits our handler, so a full queue stops
# it reading the socket (TCP backpressure) instead of growing memory.
QUEUE_SIZE: Final = 4096
# The library reports its own reasons as small codes: connecting 0 connect called, 1 transport
# closed (any WebSocket close below 3000), 2 no ping, 3 subscribe timeout, 4 unsubscribe error;
# disconnected 0 disconnect called, 1 unauthorized, 2 bad protocol, 3 message size limit.
# [code] centrifuge/codes.py. A server error reply keeps its own code (100-199).
_TRANSPORT_CLOSED: Final = 1
_SERVER_ERROR_CODES: Final = range(100, 2000)
_CENTRIFUGO_CODES_FROM: Final = 3000
_CODE_OWN_UNSUBSCRIBE_MAX: Final = 2  # 0 unsubscribe called, 1 unauthorized, 2 client closed
_ALREADY_SUBSCRIBED: Final = 105
_SILENCED_LOGGERS: Final = ("centrifuge", "websockets.client")


class _DropDebug(logging.Filter):
    """The libraries log every sent command (the connect token) and every received message
    (deal events with Steam ids) at DEBUG: those records are dropped (SDK_SPEC 1.3, 8)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno > logging.DEBUG


_DROP_DEBUG: Final = _DropDebug()


def _silence_library_debug() -> None:
    for name in _SILENCED_LOGGERS:
        logger = logging.getLogger(name)
        if _DROP_DEBUG not in logger.filters:
            logger.addFilter(_DROP_DEBUG)


@dataclass(frozen=True, slots=True)
class _Connected:
    pass


@dataclass(frozen=True, slots=True)
class _Lost:
    """The connection ended: `code`/`reason` as the library reports them."""

    code: int
    reason: str


@dataclass(frozen=True, slots=True)
class _Failed:
    """An error before the connect reply."""

    error: BaseException


_Item = Publication | Unsubscribe | _Connected | _Lost | _Failed


class _ClientEvents(ClientEventHandler):
    """Connection-level callbacks: everything goes to the queue, nothing is raised."""

    def __init__(self, owner: "WsConnection", queue: "asyncio.Queue[_Item]") -> None:
        self._owner = owner
        self._queue = queue

    async def on_connecting(self, ctx: ConnectingContext) -> None:
        # Code 0 is the initial `connect()`. Any later one is a lost connection the library would
        # reconnect by itself: stop it, the session decides.
        if ctx.code != 0:
            await self._queue.put(_Lost(ctx.code, ctx.reason))
            await self._owner.stop_client()

    async def on_connected(self, ctx: ConnectedContext) -> None:
        await self._queue.put(_Connected())

    async def on_disconnected(self, ctx: DisconnectedContext) -> None:
        # Code 0 is our own `disconnect()`.
        if ctx.code != 0:
            await self._queue.put(_Lost(ctx.code, ctx.reason))

    async def on_error(self, ctx: ErrorContext) -> None:
        # Before the connect reply an error ends the attempt (the library would retry). After
        # it every fatal problem is followed by a connecting/disconnected event.
        if not self._owner.connected:
            await self._queue.put(_Failed(ctx.error))
            await self._owner.stop_client()

    async def on_publication(self, ctx: ServerPublicationContext) -> None:
        await self._queue.put(_publication(ctx.channel, ctx.pub.data))


class _ChannelEvents(SubscriptionEventHandler):
    """Callbacks of one explicit subscription (`market_products_updates`)."""

    def __init__(self, channel: str, queue: "asyncio.Queue[_Item]") -> None:
        self._channel = channel
        self._queue = queue

    async def on_publication(self, ctx: PublicationContext) -> None:
        await self._queue.put(_publication(self._channel, ctx.pub.data))

    async def on_unsubscribed(self, ctx: UnsubscribedContext) -> None:
        # 0-2 are the client's own codes (our teardown); 105 "already subscribed" is a success
        # (SDK_SPEC 3.11). Anything else is the server refusing or ending the subscription.
        if ctx.code > _CODE_OWN_UNSUBSCRIBE_MAX and ctx.code != _ALREADY_SUBSCRIBED:
            await self._queue.put(Unsubscribe(self._channel, ctx.code))


def _publication(channel: str, data: Any) -> Publication:
    return Publication(channel, cast("dict[str, Any]", data) if isinstance(data, dict) else {})


class WsConnection:
    """One WebSocket connection at a time; `open()` makes a new library `Client` for it."""

    can_subscribe_after_connect = True

    def __init__(
        self,
        url: str,
        user_agent: str,
        *,
        proxy: str | Literal[True] | None = True,
        idle_grace: float = IDLE_GRACE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._url = url
        self._user_agent = user_agent
        self._proxy: str | Literal[True] | None = proxy
        self._idle_grace = idle_grace
        self._now = clock or (lambda: datetime.now(UTC))
        self._client: Client | None = None
        self._queue: asyncio.Queue[_Item] = asyncio.Queue(QUEUE_SIZE)
        self.connected = False
        self.closing = False
        self._subscriptions: dict[str, Any] = {}

    async def open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo:
        await self.close()
        _silence_library_debug()
        self.closing = False
        self.connected = False
        queue: asyncio.Queue[_Item] = asyncio.Queue(QUEUE_SIZE)
        self._queue = queue
        secret = token.reveal()
        client = Client(
            self._url,
            events=_ClientEvents(self, queue),
            token=secret,
            name="whitemarket-sdk-python",
            version=__version__,
            timeout=seconds,
            max_server_ping_delay=self._idle_grace,
            headers={"User-Agent": self._user_agent},
            proxy=self._proxy,
        )
        self._client = client
        for channel in channels:
            if channel.startswith("#"):
                continue  # personal channels are server-side subscriptions: never subscribed
            sub = client.new_subscription(channel, _ChannelEvents(channel, queue))
            self._subscriptions[channel] = sub
            await sub.subscribe()
        await client.connect()
        try:
            async with asyncio.timeout(seconds):
                await self._until_connected(queue)
        except TimeoutError:
            await self.close()
            raise TransportError("the live connection sent no connect reply in time") from None
        except BaseException:
            await self.close()
            raise
        left = seconds_left(secret, self._now())
        return ConnectInfo(ping=None, pong=True, ttl=left)

    async def _until_connected(self, queue: "asyncio.Queue[_Item]") -> None:
        backlog: list[_Item] = []
        while True:
            item = await queue.get()
            if isinstance(item, _Connected):
                self.connected = True
                for kept in backlog:
                    queue.put_nowait(kept)
                return
            if isinstance(item, Publication | Unsubscribe):
                backlog.append(item)
                continue
            raise _failure(item, connected=False)

    async def read(self, seconds: float | None) -> Incoming | None:
        try:
            item = await asyncio.wait_for(self._queue.get(), seconds)
        except TimeoutError:
            return None
        if isinstance(item, Publication | Unsubscribe):
            return item
        if isinstance(item, _Connected):
            return None
        raise _failure(item, connected=True)

    async def subscribe(self, channel: str) -> None:
        client = self._client
        if client is None or not self.connected:
            raise TransportError("the live connection is not open")
        if channel.startswith("#") or channel in self._subscriptions:
            return
        sub = client.new_subscription(channel, _ChannelEvents(channel, self._queue))
        self._subscriptions[channel] = sub
        await sub.subscribe()

    async def stop_client(self) -> None:
        """Stop the library's own reconnect (called from its event handlers)."""
        client = self._client
        if client is not None:
            await client.disconnect()

    async def close(self) -> None:
        client, self._client = self._client, None
        self.closing = True
        self.connected = False
        self._subscriptions.clear()
        if client is None:
            return
        with contextlib.suppress(Exception):
            await client.disconnect()
        # `disconnect()` closes the socket in a background task of the client, and the task that
        # runs our handlers may be blocked on a full queue: drain it, then wait for every task of
        # the client so that nothing outlives `close()`. [code] centrifuge/client.py `_spawn`.
        for _ in range(50):
            pending = {t for t in getattr(client, "_background_tasks", ()) if not t.done()}
            if not pending:
                break
            while not self._queue.empty():
                self._queue.get_nowait()
            await asyncio.wait(pending, timeout=0.1)
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(_Lost(0, ""))  # wakes a reader blocked in `read`


def _failure(item: _Item, *, connected: bool) -> Exception:
    """The session-level failure for a queue item that ends a connection or an attempt."""
    if isinstance(item, _Lost):
        if item.code >= _CENTRIFUGO_CODES_FROM:
            return ServerClosedError(item.code, printable(item.reason))
        if item.code == _TRANSPORT_CLOSED and connected:
            # A close below 3000 or a dropped link, not told apart by the library: SDK_SPEC 3.11
            # counts it like a code outside the Centrifugo ranges.
            return ServerClosedError(item.code, printable(item.reason))
        if item.code in _SERVER_ERROR_CODES:
            return ConnectRejectedError(item.code, temporary=False)
        return TransportError("the live connection was lost")
    if isinstance(item, _Failed):
        return _from_error(item.error)
    return TransportError("unexpected live connection state")


def _from_error(error: BaseException) -> Exception:
    if isinstance(error, CentrifugeReplyError):
        return ConnectRejectedError(error.code, error.temporary)
    if isinstance(error, InvalidStatus):
        retry_after = parse_retry_after(
            error.response.headers.get("Retry-After"), datetime.now(UTC)
        )
        return StatusFailureError(error.response.status_code, retry_after)
    return TransportError(f"the live connection failed ({type(error).__name__})")
