"""The result of one item of a `*_many` call (SDK_SPEC 3.5 rule 3)."""

from dataclasses import dataclass
from enum import Enum

from whitemarket.models.products import Product, ProductHistory


class BatchOutcome(Enum):
    """What is known about one item of a batch."""

    SUCCEEDED = "succeeded"
    """The server reported the item done."""
    FAILED = "failed"
    """The server reported the item failed: see `BatchItemResult.error_category`."""
    UNKNOWN = "unknown"
    """The request that carried the item failed ambiguously, or the server did not report the
    item: it may have been done."""
    NOT_SENT = "not_sent"
    """The item was not sent, or the server rejected the request before running it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchItemResult:
    """The result for one item of a `*_many` call of `client.selling`.

    `index` is the 0-based position of the item in the caller's list. `product` is the live
    listing, or the archived one for a removal; None when the server sent none or it could not be
    mapped (the outcome still stands). `error_category` is the category the server reported for a
    failed item (any text, unknown ones included); `error_message` is display text, never branch
    on it.
    """

    index: int
    outcome: BatchOutcome
    product: Product | ProductHistory | None = None
    error_category: str | None = None
    error_message: str | None = None
