"""HTTP status errors (SDK_SPEC 1.5)."""

from whitemarket.errors._redact import redact_body_excerpt
from whitemarket.errors.base import WhiteMarketError


class HttpError(WhiteMarketError):
    """A non-2xx answer not covered by a more specific class.

    `body_excerpt` is safe to log: the only way to set it is the raw response `body`, which is
    redacted here (at most 512 bytes of valid UTF-8, credentials replaced by `***`, SDK_SPEC 1.5).
    """

    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self.body_excerpt: str = redact_body_excerpt(body)
        super().__init__(f"HTTP {status}")


class BadRequestError(HttpError):
    """HTTP 400: bad JSON, bad GraphQL syntax or several mutations in a request; never retried."""

    def __init__(self, body: bytes = b"", *, status: int = 400) -> None:
        super().__init__(status, body)


class AuthenticationError(HttpError):
    """HTTP 401 after one refresh and replay, or an invalid Partner Token."""

    def __init__(self, body: bytes = b"", *, status: int = 401) -> None:
        super().__init__(status, body)


class RateLimitError(HttpError):
    """HTTP 429. `retry_after` is the `Retry-After` header in seconds, if the server sent one."""

    def __init__(
        self, body: bytes = b"", *, retry_after: float | None = None, status: int = 429
    ) -> None:
        super().__init__(status, body)
        self.retry_after = retry_after


class ServerError(HttpError):
    """HTTP 5xx."""

    def __init__(self, body: bytes = b"", *, status: int = 500) -> None:
        super().__init__(status, body)


class ServiceUnavailableError(ServerError):
    """HTTP 503. `retry_after` is the `Retry-After` header in seconds, if the server sent one."""

    def __init__(
        self, body: bytes = b"", *, retry_after: float | None = None, status: int = 503
    ) -> None:
        super().__init__(body, status=status)
        self.retry_after = retry_after
