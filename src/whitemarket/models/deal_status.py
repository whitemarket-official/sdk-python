"""`DealStatus` and its classification (SDK_SPEC 3.4, WHITEMARKET_API.md 4 "MarketDealStatus")."""

from typing import TYPE_CHECKING, Final

from whitemarket._runtime.enums import UnknownTolerantEnum

if TYPE_CHECKING:
    from whitemarket.models.deals import Deal, DealState


class DealStatus(UnknownTolerantEnum):
    """Status of a deal, grouped as in the table of WHITEMARKET_API.md section 4.

    A status the server adds later decodes to a pseudo-member with the raw value (`is_unknown`),
    which belongs to none of the groups (CLAUDE.md rule 5): every `is_*` helper is False for it.
    """

    HOLD = "HOLD"
    INITIATED = "INITIATED"
    QUEUED = "QUEUED"
    """Waiting to send the trade offer; in progress (WHITEMARKET_API.md 4)."""
    SELLER_SENDING_STEAM_OFFER = "SELLER_SENDING_STEAM_OFFER"
    WAITING_STEAM_QUEUE = "WAITING_STEAM_QUEUE"
    BUYER_CANCEL_REQUESTED = "BUYER_CANCEL_REQUESTED"
    OFFERED = "OFFERED"
    BUYER_OFFERED = "BUYER_OFFERED"
    SELLER_OFFERED = "SELLER_OFFERED"
    NEED_CONFIRMATION = "NEED_CONFIRMATION"
    EXCHANGED = "EXCHANGED"
    """Items moved in Steam; under Trade Protection the deal waits for `settlement_time_at` and can
    still be reversed."""
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BUYER_CANCELLED = "BUYER_CANCELLED"
    SELLER_CANCELLED = "SELLER_CANCELLED"
    EXPIRED = "EXPIRED"
    BUYER_EXPIRED = "BUYER_EXPIRED"
    SELLER_EXPIRED = "SELLER_EXPIRED"
    EXPIRING = "EXPIRING"
    """Transitional, always ends in an expired status; already counted as failed and final."""
    STEAM_ROLLBACK = "STEAM_ROLLBACK"
    BUYER_STEAM_ROLLBACK = "BUYER_STEAM_ROLLBACK"
    SELLER_STEAM_ROLLBACK = "SELLER_STEAM_ROLLBACK"

    def is_in_progress(self) -> bool:
        """Still moving towards an exchange: keep waiting. `EXCHANGED` is its own stage."""
        return self.value in _IN_PROGRESS

    def is_exchanged(self) -> bool:
        """Items moved in Steam (`EXCHANGED`); see `awaiting_trade_protection`."""
        return self is DealStatus.EXCHANGED

    def is_successful(self) -> bool:
        """Funds settled (`COMPLETED`)."""
        return self is DealStatus.COMPLETED

    def is_failed(self) -> bool:
        """No trade happened."""
        return self.value in _FAILED

    def is_reversed(self) -> bool:
        """Steam reverted the trade after the exchange."""
        return self.value in _REVERSED

    def is_final(self) -> bool:
        """The deal will not change any more: successful, failed or reversed."""
        return self.is_successful() or self.is_failed() or self.is_reversed()


_IN_PROGRESS: Final = frozenset(
    {
        "HOLD",
        "INITIATED",
        "QUEUED",
        "SELLER_SENDING_STEAM_OFFER",
        "WAITING_STEAM_QUEUE",
        "BUYER_CANCEL_REQUESTED",
        "OFFERED",
        "BUYER_OFFERED",
        "SELLER_OFFERED",
        "NEED_CONFIRMATION",
    }
)
_FAILED: Final = frozenset(
    {
        "CANCELLED",
        "BUYER_CANCELLED",
        "SELLER_CANCELLED",
        "EXPIRED",
        "BUYER_EXPIRED",
        "SELLER_EXPIRED",
        "EXPIRING",
    }
)
_REVERSED: Final = frozenset({"STEAM_ROLLBACK", "BUYER_STEAM_ROLLBACK", "SELLER_STEAM_ROLLBACK"})


def awaiting_trade_protection(deal: "Deal | DealState") -> bool:
    """Exchanged under Steam Trade Protection: wait until `settlement_time_at` for `COMPLETED`.

    The deal can still be reversed until then (`EXCHANGED` and `is_trade_protected`).
    """
    return deal.status is DealStatus.EXCHANGED and deal.is_trade_protected is True
