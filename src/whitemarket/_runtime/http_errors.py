"""The error for a non-2xx status (SDK_SPEC 1.5, WHITEMARKET_API 2)."""

from whitemarket.errors.http import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)
from whitemarket.retry import RETRY_AFTER_STATUSES

_BAD_REQUEST = 400
_UNAUTHORIZED = 401
_TOO_MANY_REQUESTS = 429
_UNAVAILABLE = 503
_SERVER_ERRORS = range(500, 600)


def http_error_for(status: int, body: bytes, retry_after: float | None = None) -> HttpError:
    """The error class of `status`; `retry_after` is kept for 429 and 503 only.

    A 3xx (redirects are never followed) and any other status is a plain `HttpError`.
    """
    if status not in RETRY_AFTER_STATUSES:
        retry_after = None
    if status == _BAD_REQUEST:
        return BadRequestError(body)
    if status == _UNAUTHORIZED:
        return AuthenticationError(body)
    if status == _TOO_MANY_REQUESTS:
        return RateLimitError(body, retry_after=retry_after)
    if status == _UNAVAILABLE:
        return ServiceUnavailableError(body, retry_after=retry_after)
    if status in _SERVER_ERRORS:
        return ServerError(body, status=status)
    return HttpError(status, body)
