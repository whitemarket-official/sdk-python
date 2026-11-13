"""Models of deals: `Deal`, `DealState`, `BuyResult` (SDK_SPEC 3.3, 3.4, 4)."""

from dataclasses import dataclass, field
from datetime import datetime

from whitemarket._runtime.secret import Secret
from whitemarket.models.deal_status import DealStatus
from whitemarket.models.enums import DealCancelReason, DeliveryType
from whitemarket.models.money import Money
from whitemarket.models.products import InventoryItem, ProductHistory


@dataclass(frozen=True, slots=True, kw_only=True)
class DealState:
    """The cheap status snapshot of a deal, as returned by `deals.statuses()` (SDK_SPEC 3.4).

    `is_trade_protected` is None when the server does not report it. `reverse_penalty` and
    `reverse_refund` are set after a Steam rollback.
    """

    id: str
    custom_id: str | None
    status: DealStatus
    cancel_reason: DealCancelReason | None
    price: Money
    steam_id: str | None
    trade_id: str | None
    is_trade_protected: bool | None
    settlement_time_at: datetime | None
    reverse_penalty: Money | None
    reverse_refund: Money | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Deal:
    """A deal, in progress or archived (SDK_SPEC 3.4: `deals.get()` returns both as one model).

    The server keeps a deal in progress until it finishes and then moves it to the history; some
    fields exist on one side only and are None (or False) on the other:

    - in progress only: `is_trade_protected`, `settlement_time_at` (when Steam Trade Protection
      ends), `expires_at`, `is_cancel_by_buyer_supported` (always False for an archived deal),
      `cancel_by_buyer_need_wait` (seconds until the buyer may request a cancel), `item`,
      `receiver_trade_url`;
    - archived only: `cancel_reason`, `archived_at`, `reverse_penalty` and `reverse_refund` (after
      a Steam rollback). An archived deal's item is `product.item`.

    `receiver_trade_url` is a `Secret`: where a MANUAL seller sends the item, and the URL carries
    the buyer's trade token (SDK_SPEC 3.4 rule 11). It is None for null, for an empty value and for
    an archived deal, and it is left out of `repr()`.
    """

    id: str
    custom_id: str | None
    status: DealStatus
    price: Money
    created_at: datetime
    delivery_type: DeliveryType
    steam_id: str | None
    trade_id: str | None
    is_trade_protected: bool | None
    settlement_time_at: datetime | None
    expires_at: datetime | None
    is_cancel_by_buyer_supported: bool
    cancel_by_buyer_need_wait: int | None
    cancel_reason: DealCancelReason | None
    archived_at: datetime | None
    reverse_penalty: Money | None
    reverse_refund: Money | None
    product: ProductHistory
    item: InventoryItem | None
    receiver_trade_url: Secret | None = field(default=None, repr=False)

    @property
    def is_archived(self) -> bool:
        """The deal moved to the history (`archived_at` is set)."""
        return self.archived_at is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class BuyResult:
    """The outcome of a buy (SDK_SPEC 3.3): the `deal`, the `custom_id` it was bought under and
    whether it was found by reconciliation (`reconciled`) after the `market_buy` answer was lost."""

    deal: Deal
    custom_id: str
    reconciled: bool
