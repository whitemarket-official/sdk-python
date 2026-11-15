"""What a session needs from one live connection, and the failures a connection reports."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Final, Protocol

from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import TransportError
from whitemarket.live._envelope import (
    ConnectReply,
    Disconnect,
    OtherMessage,
    Ping,
    Publication,
    Reply,
    Unsubscribe,
)
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.options import LiveOptions, LiveTransport

# Messages a connection may buffer for a consumer that does not read, lowered so that
# messages x `max_message_bytes` stays within BUFFER_BYTES.
QUEUE_SIZE: Final = 4096
BUFFER_BYTES: Final = 64 * 1024 * 1024
MIN_QUEUE_SIZE: Final = 2


def queue_size(max_message_bytes: int) -> int:
    """How many messages a connection buffers (WebSocket and SSE share the rule)."""
    return max(MIN_QUEUE_SIZE, min(QUEUE_SIZE, BUFFER_BYTES // max_message_bytes))


async def open_in_time(
    seconds: float,
    attempt: Callable[[], Awaitable[ConnectInfo]],
    close: Callable[[], Awaitable[None]],
) -> ConnectInfo:
    """Run `attempt` within `seconds`; on any failure `close` before the error leaves.

    The timeout error is raised outside the `except` block: the timeout can fire inside the
    request, whose frame holds the token (the SSE URL), and a raise inside the block would chain
    that frame as `__context__` (`from None` only hides it from the printout). SDK_SPEC 8."""
    try:
        async with asyncio.timeout(seconds):
            return await attempt()
    except TimeoutError:
        pass  # raised below, outside this block
    except BaseException:
        await close()
        raise
    await close()
    raise TransportError("the live connection sent no connect reply in time")


Incoming = Publication | Disconnect | Unsubscribe | Reply | Ping | ConnectReply | OtherMessage


class ServerClosedError(Exception):
    """The server closed the connection or sent a disconnect; `reason` is printable ASCII."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(f"closed with code {code}")
        self.code = code
        self.reason = reason


class SlowConsumerError(TransportError):
    """The consumer did not keep up and the connection buffer overflowed: the connection was
    dropped, messages are lost (resync through GraphQL)."""


class ConnectRejectedError(Exception):
    """The server answered the connect command with an error reply."""

    def __init__(self, code: int, temporary: bool) -> None:
        super().__init__(f"connect rejected with code {code}")
        self.code = code
        self.temporary = temporary


class StatusFailureError(Exception):
    """The connect request got a non-2xx HTTP answer (SSE request or WebSocket upgrade)."""

    def __init__(self, status: int, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


class Connection(Protocol):
    """One live connection: open it, read from it, close it. `open` may follow `close`.

    Failures: `ConnectRejectedError`, `ServerClosedError`, `StatusFailureError` and `TransportError`
    (and `DecodeError` from `read`, a malformed message that does not end the connection).
    """

    can_subscribe_after_connect: bool
    """False when channels can only be chosen at connect time (SSE): a new channel reconnects."""

    async def open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo: ...

    async def read(self, seconds: float | None) -> Incoming | None:
        """The next protocol message, or `None` after `seconds` (`None`: no limit)."""
        ...

    async def subscribe(self, channel: str) -> None: ...

    async def close(self) -> None: ...


def build_connection(
    transport: LiveTransport,
    *,
    ws_url: str,
    sse_url: str,
    user_agent: str,
    options: LiveOptions,
) -> Connection:
    """The connection of a transport; the WebSocket one needs the `live` extra."""
    # Imported here: `_ws` needs the optional `live` extra (SSE does not), and both import this
    # module.
    if transport is LiveTransport.SSE:
        from whitemarket.live._sse import SseConnection  # noqa: PLC0415 - import cycle with _sse, see #0

        return SseConnection(sse_url, user_agent, options)
    from whitemarket.live._ws import WsConnection  # noqa: PLC0415 - optional live extra and import cycle, see #0

    return WsConnection(ws_url, user_agent, max_message_bytes=options.max_message_bytes)
