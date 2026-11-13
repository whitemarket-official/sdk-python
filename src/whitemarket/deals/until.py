"""Ready-made conditions for `deals.wait_for()` (SDK_SPEC 3.4)."""

from collections.abc import Callable

from whitemarket.models.deal_status import DealStatus
from whitemarket.models.deals import DealState

DealPredicate = Callable[[DealState], bool]

_OFFERED = frozenset(
    {
        DealStatus.OFFERED,
        DealStatus.BUYER_OFFERED,
        DealStatus.SELLER_OFFERED,
        DealStatus.NEED_CONFIRMATION,
    }
)


class Until:
    """Predicates over a `DealState`: pass one to `deals.wait_for(..., until=Until.offered())`.

    Every predicate also matches a FINAL status (`DealStatus.is_final()`: completed, failed or
    reversed), so a wait never outlives a cancelled, expired or reversed deal; the caller checks
    the status of the returned state to see how the deal ended. A status this SDK does not know
    matches none of them. `COMPLETED` is final, so `completed()` and `final()` match the same
    states.
    """

    def __new__(cls) -> "Until":
        raise TypeError("Until is a namespace of predicates; call its static methods")

    @staticmethod
    def offered() -> DealPredicate:
        """The offer was made (`OFFERED`, `BUYER_OFFERED`, `SELLER_OFFERED`, `NEED_CONFIRMATION`),
        or the deal is already past that: exchanged or final."""
        past_offer = Until.exchanged_or_completed()
        return lambda state: past_offer(state) or state.status in _OFFERED

    @staticmethod
    def exchanged_or_completed() -> DealPredicate:
        """Items moved in Steam (`EXCHANGED`) or the deal is final."""
        return lambda state: state.status.is_exchanged() or state.status.is_final()

    @staticmethod
    def completed() -> DealPredicate:
        """The deal reached `COMPLETED`, or any other final status (see the class documentation)."""
        return Until.final()

    @staticmethod
    def final() -> DealPredicate:
        """The deal will not change any more: completed, failed or reversed."""
        return lambda state: state.status.is_final()
