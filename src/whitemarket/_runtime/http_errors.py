"""The error for a non-2xx status (SDK_SPEC 1.5, WHITEMARKET_API 2)."""

from typing import Final

from whitemarket._runtime.retry_after import RETRY_AFTER_STATUSES
from whitemarket.errors.http import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)

BAD_REQUEST: Final = 400
UNAUTHORIZED: Final = 401
TOO_MANY_REQUESTS: Final = 429
UNAVAILABLE: Final = 503
SERVER_ERRORS: Final = range(500, 600)


def http_error_for(status: int, body: bytes = b"", retry_after: float | None = None) -> HttpError:
    """The error class of `status`; `retry_after` is kept for 429 and 503 only.

    A 3xx (redirects are never followed) and any other status is a plain `HttpError`.
    """
    if status not in RETRY_AFTER_STATUSES:
        retry_after = None
    if status == BAD_REQUEST:
        return BadRequestError(body)
    if status == UNAUTHORIZED:
        return AuthenticationError(body)
    if status == TOO_MANY_REQUESTS:
        return RateLimitError(body, retry_after=retry_after)
    if status == UNAVAILABLE:
        return ServiceUnavailableError(body, retry_after=retry_after)
    if status in SERVER_ERRORS:
        return ServerError(body, status=status)
    return HttpError(status, body)
