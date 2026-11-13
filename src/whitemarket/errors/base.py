"""Errors that are not tied to HTTP status codes or GraphQL answers (SDK_SPEC 1.5).

No error here carries a token, a request body or response data: messages are built from names,
ids the caller chose and JSON paths only.
"""

from collections.abc import Sequence
from datetime import datetime


class WhiteMarketError(Exception):
    """Base of every error the SDK raises on purpose; never raised directly."""


class TransportError(WhiteMarketError):
    """DNS, TLS, connect, timeout or body read failure."""


def render_path(path: Sequence[str | int]) -> str:
    """`("prices", 3, "price")` as `prices[3].price`: an integer is an index, a name is a key."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text


class DecodeError(WhiteMarketError):
    """The response has an unexpected JSON shape.

    Holds the path of the first offending value and the reason, never the response itself (SDK_SPEC
    8).
    """

    def __init__(self, reason: str, path: Sequence[str | int] = ()) -> None:
        self.reason = reason
        self.path: tuple[str | int, ...] = tuple(path)
        location = render_path(self.path)
        super().__init__(f"{location}: {reason}" if location else reason)


class PurchaseOutcomeUnknownError(WhiteMarketError):
    """Buy reconciliation found no deal for the `custom_id`; the purchase may have happened."""

    def __init__(self, custom_id: str) -> None:
        self.custom_id = custom_id
        super().__init__(f"purchase outcome unknown for custom_id {custom_id!r}")


class MutationOutcomeUnknownError(WhiteMarketError):
    """A money-moving mutation failed ambiguously: it may have been applied (SDK_SPEC 3.8)."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"outcome of mutation {operation!r} is unknown")


class ExportError(WhiteMarketError):
    """An export download or parse failure."""


class GeneralExportError(ExportError):
    """An export failure that is not staleness."""


class StaleExportError(ExportError):
    """The export file is older than the caller allows (`max_age`).

    `data_as_of` is the age marker the server reported (timezone-aware), `max_age_seconds` the
    limit the caller set.
    """

    def __init__(self, data_as_of: datetime, max_age_seconds: float) -> None:
        self.data_as_of = data_as_of
        self.max_age_seconds = max_age_seconds
        super().__init__(
            f"the export data is older than {max_age_seconds:g} s "
            f"(data_as_of {data_as_of.isoformat()})"
        )


class LiveConnectionError(WhiteMarketError):
    """SSE or WebSocket protocol or authentication failure that ends a live session.

    `code` is the close, disconnect or error code (None when there is none); `reason` is server
    text reduced to printable ASCII (SDK_SPEC 3.11), not redacted. The exception text names the
    code only, because a message is often logged: callers branch on `code`, never on `reason`.
    """

    def __init__(self, code: int | None = None, reason: str = "") -> None:
        self.code = code
        self.reason = reason
        super().__init__(
            "live connection failed" if code is None else f"live connection failed: code {code}"
        )
