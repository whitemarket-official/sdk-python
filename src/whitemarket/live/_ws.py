"""WebSocket live connection: an own minimal Centrifugo JSON-protocol client over `websockets`.

ADR 0005. One `WsConnection` owns one socket at a time. A reader task decodes frames (split on
`\\n`, `decode_message`), answers the server ping, and hands the protocol messages to the session
through a bounded queue; the session engine (`_engine.py`) owns every other decision: backoff, close
codes, token refresh, the idle deadline, error replies, resubscribing.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from whitemarket._runtime.retry_after import parse_retry_after
from whitemarket._runtime.secret import Secret
from whitemarket._version import __version__
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import (
    ConnectRejectedError,
    Incoming,
    ServerClosedError,
    SlowConsumerError,
    StatusFailureError,
    queue_size,
)
from whitemarket.live._envelope import (
    ConnectReply,
    Disconnect,
    Ping,
    ProtocolMessage,
    Reply,
    Unsubscribe,
    decode_message,
    printable,
)
from whitemarket.live._policy import ALREADY_SUBSCRIBED_REPLY, ConnectInfo, is_personal
from whitemarket.live.options import LiveOptions

try:
    from websockets.asyncio.client import ClientConnection, connect
    from websockets.exceptions import ConnectionClosed, InvalidStatus
except ImportError as error:
    raise ImportError(
        "WebSocket live updates need the `live` extra: pip install 'whitemarket-sdk[live]'"
    ) from error

CLIENT_NAME: Final = "whitemarket-sdk-python"
_CONNECT_ID: Final = 1
_CENTRIFUGO_CODES_FROM: Final = 3000
_ABNORMAL_CLOSURE: Final = 1006
_POLICY_VIOLATION: Final = 1008
_CLOSE_TIMEOUT: Final = 5.0

# `websockets` logs every frame (the connect token, deal events with Steam ids) at DEBUG, decided
# when a connection is created from `logger.isEnabledFor(DEBUG)` [code websockets/protocol.py:108].
# Our own logger, pinned to INFO, makes that impossible whatever the application configures.
_LOGGER: Final = logging.getLogger("whitemarket.live.websockets")
_LOGGER.setLevel(logging.INFO)


@dataclass(frozen=True, slots=True)
class _End:
    """The reader stopped. `code` is the WebSocket close code (the real one), or `None` when the
    reader failed for another reason; `local` is our own `close()`."""

    code: int | None
    reason: str = ""
    local: bool = False


_Item = ProtocolMessage | DecodeError | _End


class _Link:
    """The state of ONE socket. A reader that outlives its connection can only touch its own."""

    def __init__(self, ws: ClientConnection, size: int) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[_Item] = asyncio.Queue(size)
        self.connect: asyncio.Future[ConnectInfo] = asyncio.get_running_loop().create_future()
        self.ready = False
        self.pong = False
        self.overflowed = False
        self.ended: _End | None = None
        self.next_id = _CONNECT_ID
        self.pending: dict[int, str] = {}
        self.subscribed: set[str] = set()
        self.reader: asyncio.Task[None] | None = None

    def command_id(self) -> int:
        command_id = self.next_id
        self.next_id += 1
        return command_id

    def put(self, item: _Item) -> bool:
        """Never waits: a full queue means the consumer is too slow. False after an overflow."""
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.overflowed = True
            return False
        return True


class WsConnection:
    """One WebSocket connection at a time; `open()` starts a new one."""

    can_subscribe_after_connect = True

    def __init__(
        self,
        url: str,
        user_agent: str,
        *,
        proxy: str | Literal[True] | None = True,
        max_message_bytes: int = LiveOptions().max_message_bytes,
    ) -> None:
        self._url = url
        self._user_agent = user_agent
        self._proxy: str | Literal[True] | None = proxy
        self._max_message_bytes = max_message_bytes
        self._link: _Link | None = None

    async def open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo:
        await self.close()
        try:
            async with asyncio.timeout(seconds):
                return await self._open(token, channels)
        except TimeoutError:
            await self.close()
            raise TransportError("the live connection sent no connect reply in time") from None
        except BaseException:
            await self.close()
            raise

    async def _open(self, token: Secret, channels: Sequence[str]) -> ConnectInfo:
        result = await _handshake(self._url, self._user_agent, self._proxy, self._max_message_bytes)
        if isinstance(result, Exception):
            raise result  # raised outside any `except` block: nothing chained
        link = _Link(result, queue_size(self._max_message_bytes))
        self._link = link
        link.reader = asyncio.create_task(_pump(link))
        # Built in the call so that no frame of ours keeps the command; a send failure is
        # dropped to a flag because the exception's traceback would hold the sent text.
        if not await _send(link.ws, _connect_command(token)):
            raise TransportError("the live connection closed while connecting")
        info = await link.connect
        link.ready = True
        for channel in channels:
            await self.subscribe(channel)  # personal channels are skipped there
        return info

    async def read(self, seconds: float | None) -> Incoming | None:
        link = self._link
        if link is None:
            raise TransportError("the live connection is not open")
        if link.overflowed:
            raise SlowConsumerError("the live consumer is too slow")
        if link.ended is not None:
            raise _failure(link.ended, connected=True)
        try:
            item = await asyncio.wait_for(link.queue.get(), seconds)
        except TimeoutError:
            return None
        if link.overflowed:
            raise SlowConsumerError("the live consumer is too slow")
        if isinstance(item, _End):
            link.ended = item
            raise _failure(item, connected=True)
        if isinstance(item, DecodeError):
            raise item
        return item

    async def subscribe(self, channel: str) -> None:
        link = self._link
        if link is None or not link.ready:
            raise TransportError("the live connection is not open")
        if is_personal(channel) or channel in link.subscribed:
            return  # a personal channel is a server-side subscription
        command_id = link.command_id()
        link.subscribed.add(channel)
        link.pending[command_id] = channel
        command = {"id": command_id, "subscribe": {"channel": channel}}
        if not await _send(link.ws, json.dumps(command, separators=(",", ":"))):
            raise TransportError("the live connection closed while subscribing")

    async def close(self) -> None:
        link, self._link = self._link, None
        if link is None:
            return
        link.ready = False
        if link.reader is not None:
            link.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await link.reader
        if not link.connect.done():
            link.connect.cancel()
        elif not link.connect.cancelled():
            link.connect.exception()  # mark a failure nobody awaited as retrieved
        while link.queue.full():  # make room for the item that wakes a blocked `read`
            link.queue.get_nowait()
        link.queue.put_nowait(_End(None, local=True))
        with contextlib.suppress(Exception):
            await link.ws.close()


async def _handshake(
    url: str, user_agent: str, proxy: str | Literal[True] | None, max_size: int
) -> ClientConnection | Exception:
    """The open socket, or the failure to raise (built here, never raised in an `except`)."""
    failure: Exception | None = None
    try:
        return await connect(
            url,
            user_agent_header=user_agent,
            max_size=max_size,
            compression=None,
            ping_interval=None,  # Centrifugo pings at the protocol level, not with WS ping frames
            open_timeout=None,  # `open()` bounds handshake and connect reply together
            close_timeout=_CLOSE_TIMEOUT,
            proxy=proxy,
            logger=_LOGGER,
        )
    except InvalidStatus as error:
        retry_after = parse_retry_after(
            error.response.headers.get("Retry-After"), datetime.now(UTC)
        )
        failure = StatusFailureError(error.response.status_code, retry_after)
    except Exception as error:  # OSError, InvalidHandshake, InvalidURI, ...
        failure = TransportError(f"the live connection failed ({type(error).__name__})")
    return failure


def _connect_command(token: Secret) -> str:
    connect_body = {"token": token.reveal(), "name": CLIENT_NAME, "version": __version__}
    return json.dumps({"id": _CONNECT_ID, "connect": connect_body}, separators=(",", ":"))


async def _send(ws: ClientConnection, text: str) -> bool:
    """False when the connection is closed; the exception is dropped (its frames hold `text`)."""
    try:
        await ws.send(text)
    except ConnectionClosed:
        return False
    return True


def _end_of(closed: ConnectionClosed) -> _End:
    frame = closed.rcvd or closed.sent
    if frame is None:
        return _End(_ABNORMAL_CLOSURE)
    return _End(frame.code, printable(frame.reason))


async def _pump(link: _Link) -> None:
    """Read frames until the socket ends or the consumer is too slow. Never raises."""
    end = _End(None)
    try:
        while await _frame(link, await link.ws.recv()):
            pass
        end = _End(_POLICY_VIOLATION, "consumer too slow")
    except ConnectionClosed as closed:
        end = _end_of(closed)
    except Exception as error:  # a bug or a library failure: reported by class name only
        end = _End(None, type(error).__name__)
    if not link.connect.done():
        link.connect.set_exception(_failure(end, connected=False))
    link.put(end)
    if link.overflowed:
        with contextlib.suppress(Exception):
            await link.ws.close(_POLICY_VIOLATION, "consumer too slow")


async def _frame(link: _Link, raw: str | bytes) -> bool:
    """Handle one WebSocket frame (messages joined with `\\n`); False after a queue overflow."""
    lines = raw.split("\n") if isinstance(raw, str) else raw.split(b"\n")
    for line in lines:
        if not line:
            continue
        try:
            message: ProtocolMessage | DecodeError = decode_message(line)
        except DecodeError as error:
            message = error.with_traceback(None)
        if isinstance(message, DecodeError):
            delivered = link.put(message)
        else:
            delivered = await _message(link, message)
        if not delivered:
            return False
    return True


async def _message(link: _Link, message: ProtocolMessage) -> bool:
    if isinstance(message, ConnectReply) and not link.connect.done():
        link.pong = message.pong
        info = ConnectInfo.from_reply(message.ping, message.pong, message.ttl, message.expires)
        link.connect.set_result(info)
        return True
    if isinstance(message, Reply):
        channel = link.pending.pop(message.id, None)
        error = message.error
        if not link.connect.done() and message.id == _CONNECT_ID and error is not None:
            link.connect.set_exception(ConnectRejectedError(error.code, error.temporary))
            return True
        if error is not None and error.code != ALREADY_SUBSCRIBED_REPLY and channel is not None:
            link.subscribed.discard(channel)  # a later `subscribe()` may try again
    elif isinstance(message, Unsubscribe):
        link.subscribed.discard(message.channel)  # the session decides whether to subscribe again
    elif isinstance(message, Disconnect) and not link.connect.done():
        link.connect.set_exception(ServerClosedError(message.code, message.reason))
        return True
    elif isinstance(message, Ping) and link.pong:
        await _send(link.ws, "{}")
    return link.put(message)


def _failure(end: _End, *, connected: bool) -> Exception:
    """The session-level failure for the end of a connection (`connected`) or of an attempt."""
    if end.local:
        return TransportError("the live connection is closed")
    if end.code is None:
        return TransportError(f"the live connection failed ({end.reason or 'unknown error'})")
    if end.code >= _CENTRIFUGO_CODES_FROM or connected:
        # A close below 3000 or a dropped link (1006) is a code outside the Centrifugo ranges:
        # the session counts it (SDK_SPEC 3.11). While connecting it is only a failed attempt.
        return ServerClosedError(end.code, printable(end.reason))
    return TransportError("the live connection was lost")
