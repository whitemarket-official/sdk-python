"""Errors that are not tied to HTTP status codes or GraphQL answers (SDK_SPEC 1.5).

No error here carries a token, a request body or response data: messages are built from names,
ids the caller chose and JSON paths only.
"""

from collections.abc import Sequence


class WhiteMarketError(Exception):
    """Base of every error the SDK raises on purpose; never raised directly."""


class TransportError(WhiteMarketError):
    """DNS, TLS, connect, timeout or body read failure."""


class DecodeError(WhiteMarketError):
    """The response has an unexpected JSON shape.

    Holds the path of the first offending value and the reason, never the response itself (SDK_SPEC
    8).
    """

    def __init__(self, reason: str, path: Sequence[str | int] = ()) -> None:
        self.reason = reason
        self.path: tuple[str | int, ...] = tuple(path)
        location = ".".join(str(part) for part in self.path)
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
    """The export file is older than the caller allows."""


class LiveConnectionError(WhiteMarketError):
    """SSE or WebSocket protocol or authentication failure."""
