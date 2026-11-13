"""What a session needs from one live connection, and the failures a connection reports."""

from collections.abc import Sequence
from typing import Final, Protocol

from whitemarket._runtime.secret import Secret
from whitemarket.errors.http import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.envelope import (
    ConnectReply,
    Disconnect,
    OtherMessage,
    Ping,
    Publication,
    Reply,
    Unsubscribe,
)

HTTP_BAD_REQUEST: Final = 400
HTTP_UNAUTHORIZED: Final = 401
HTTP_TOO_MANY_REQUESTS: Final = 429
HTTP_UNAVAILABLE: Final = 503
HTTP_SERVER_ERRORS: Final = range(500, 600)

Incoming = Publication | Disconnect | Unsubscribe | Reply | Ping | ConnectReply | OtherMessage


class ServerClosedError(Exception):
    """The server closed the connection or sent a disconnect; `reason` is printable ASCII."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(f"closed with code {code}")
        self.code = code
        self.reason = reason


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


def http_error(status: int, retry_after: float | None = None) -> HttpError:
    """The SDK's error class of a status, for a terminal failure (no body is kept)."""
    if status == HTTP_UNAUTHORIZED:
        return AuthenticationError()
    if status == HTTP_TOO_MANY_REQUESTS:
        return RateLimitError(retry_after=retry_after)
    if status == HTTP_UNAVAILABLE:
        return ServiceUnavailableError(retry_after=retry_after)
    if status == HTTP_BAD_REQUEST:
        return BadRequestError()
    if status in HTTP_SERVER_ERRORS:
        return ServerError(status=status)
    return HttpError(status)


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
