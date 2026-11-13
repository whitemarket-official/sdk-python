"""HTTP status errors (SDK_SPEC 1.5)."""

from whitemarket.errors.base import WhiteMarketError


class HttpError(WhiteMarketError):
    """A non-2xx answer not covered by a more specific class.

    `body_excerpt` is meant to be safe to log; the redactor that guarantees it arrives with the
    transport (P2), so until then callers must pass an already redacted excerpt.
    """

    def __init__(self, status: int, body_excerpt: str = "") -> None:
        self.status = status
        self.body_excerpt = body_excerpt
        super().__init__(f"HTTP {status}")


class BadRequestError(HttpError):
    """HTTP 400: bad JSON, bad GraphQL syntax or several mutations in a request; never retried."""

    def __init__(self, body_excerpt: str = "", *, status: int = 400) -> None:
        super().__init__(status, body_excerpt)


class AuthenticationError(HttpError):
    """HTTP 401 after one refresh and replay, or an invalid Partner Token."""

    def __init__(self, body_excerpt: str = "", *, status: int = 401) -> None:
        super().__init__(status, body_excerpt)


class RateLimitError(HttpError):
    """HTTP 429. `retry_after` is the `Retry-After` header in seconds, if the server sent one."""

    def __init__(
        self, body_excerpt: str = "", *, retry_after: float | None = None, status: int = 429
    ) -> None:
        super().__init__(status, body_excerpt)
        self.retry_after = retry_after


class ServerError(HttpError):
    """HTTP 5xx."""

    def __init__(self, body_excerpt: str = "", *, status: int = 500) -> None:
        super().__init__(status, body_excerpt)


class ServiceUnavailableError(ServerError):
    """HTTP 503. `retry_after` is the `Retry-After` header in seconds, if the server sent one."""

    def __init__(
        self, body_excerpt: str = "", *, retry_after: float | None = None, status: int = 503
    ) -> None:
        super().__init__(body_excerpt, status=status)
        self.retry_after = retry_after
