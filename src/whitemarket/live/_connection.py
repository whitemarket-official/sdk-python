"""What a session needs from one live connection, and the failures a connection reports."""

from collections.abc import Sequence
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

# Messages a connection may buffer for a consumer that does not read.
QUEUE_SIZE: Final = 4096

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

    return WsConnection(ws_url, user_agent)
