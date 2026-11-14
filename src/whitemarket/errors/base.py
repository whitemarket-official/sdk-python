"""Errors that are not tied to HTTP status codes or GraphQL answers (SDK_SPEC 1.5).

No error here carries a token, a request body or response data: messages are built from names,
ids the caller chose and JSON paths only.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from whitemarket.models.deals import DealState
    from whitemarket.selling.results import BatchItemResult


class WhiteMarketError(Exception):
    """Base of every error the SDK raises on purpose; never raised directly."""


class TransportError(WhiteMarketError):
    """DNS, TLS, connect, timeout or body read failure."""


def _render_path(path: Sequence[str | int]) -> str:
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
        location = _render_path(self.path)
        super().__init__(f"{location}: {reason}" if location else reason)


class PurchaseOutcomeUnknownError(WhiteMarketError):
    """Buy reconciliation found no deal for the `custom_id`; the purchase may have happened.

    `__cause__` is the failure of `market_buy` that started the reconciliation. `last_lookup_error`
    is the most telling failure of the lookups (a failed lookup rather than a plain "not found"),
    or the last "not found" when every lookup answered that. Persist the `custom_id` and check the
    deal again later before buying again: a second purchase may be a double purchase.
    """

    def __init__(self, custom_id: str, last_lookup_error: BaseException | None = None) -> None:
        self.custom_id = custom_id
        self.last_lookup_error = last_lookup_error
        super().__init__(f"purchase outcome unknown for custom_id {custom_id!r}")


class MutationOutcomeUnknownError(WhiteMarketError):
    """A money-moving mutation failed ambiguously: it may have been applied (SDK_SPEC 3.8).

    `operation` is the SDK method (`wallet.transfer`); the error derives where to check from it
    (`wallet.transfers()`). The mutation was sent once and is never resent: do not send it again
    before checking. `__cause__` is the original failure. The message names the method and where
    to check, never an amount or an id.
    """

    _CHECK_HINTS: ClassVar[Mapping[str, str]] = MappingProxyType(
        {"wallet.transfer": "wallet.transfers()", "wallet.take_credit": "wallet.credit()"}
    )

    def __init__(self, operation: str) -> None:
        self.operation = operation
        hint = self._CHECK_HINTS.get(operation)
        where = (
            f"check {hint} before trying again" if hint else "check the result before trying again"
        )
        super().__init__(f"{operation} may or may not have been executed; {where}")


class BatchIncompleteError(WhiteMarketError):
    """A `*_many` call of `client.selling` could not give every item a server-reported outcome
    (SDK_SPEC 3.5 rule 3).

    `results` has one entry per item the caller passed, in the caller's order: items of earlier
    requests keep their outcome, the items of the failed request are `UNKNOWN` (it may have run) or
    `NOT_SENT` (the server rejected it before running it), later items are `NOT_SENT`.
    `__cause__` is the failure of the request, or None when the server only left items out of its
    answer. Never resend the whole list: send only the `NOT_SENT` items, and check the `UNKNOWN`
    ones with `selling.my_products()`.
    """

    def __init__(self, results: "Sequence[BatchItemResult]") -> None:
        self.results: tuple[BatchItemResult, ...] = tuple(results)
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.outcome.value] = counts.get(result.outcome.value, 0) + 1
        super().__init__(
            f"batch incomplete: {counts.get('succeeded', 0)} succeeded, "
            f"{counts.get('failed', 0)} failed, {counts.get('unknown', 0)} unknown, "
            f"{counts.get('not_sent', 0)} not sent"
        )


class DealWaitTimeoutError(WhiteMarketError):
    """`deals.wait_for()` ran out of time before the deal reached the awaited state (SDK_SPEC 3.4).

    `last_state` is the last state seen, `None` when the deal was never visible. `timeout` is the
    limit in seconds that was given.
    """

    def __init__(
        self, id_or_custom_id: str, last_state: "DealState | None", timeout: float
    ) -> None:
        self.id_or_custom_id = id_or_custom_id
        self.last_state = last_state
        self.timeout = timeout
        seen = (
            "the deal was never visible"
            if last_state is None
            else f"last status {last_state.status.value}"
        )
        super().__init__(
            f"deal {id_or_custom_id!r} did not reach the awaited state "
            f"within {timeout:g} s ({seen})"
        )


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
