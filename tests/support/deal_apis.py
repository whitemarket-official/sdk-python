"""The buying and deals APIs on a scripted HTTP client with deterministic time (no real sleeping).

The APIs are built over the real generated client of a `ClientRig`, with a recording sleeper and a
clock that the sleeper advances, in the async and the sync flavor alike.
"""

from collections.abc import Callable
from typing import Any

from support import market_payloads as mp
from support.clients import ClientRig
from support.http import Reply, data, json_response
from whitemarket import BuyReconciliation
from whitemarket._generated.deal_cancel_sending_offer import (
    DealCancelSendingOfferDealCancelSendingOffer,
)
from whitemarket._generated.deal_history import DealHistoryDealHistoryEdgesNode
from whitemarket._generated.market_buy import MarketBuyMarketBuy

DELAY = 12.0
INTERVAL = 2.0
CUSTOM_ID = "order-42"
PRODUCT_ID = "7d1c0e52-3b8a-4f6d-9a21-5e4c8b7f0a13"
DEAL_ID = "0b6c1c0a-5a44-4e49-8f27-1f2d3c4b5a69"
OTHER_ID = "c9b1a2d3-0e4f-4a5b-8c6d-7e8f9a0b1c2d"
MAX_SLEEPS = 500
NOT_FOUND_CATEGORY = "market.deal.not_found"


class Timeline:
    """A clock that only moves when the sleeper is called; `sleeps` is every wait asked for."""

    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def record(self, seconds: float) -> None:
        if len(self.sleeps) >= MAX_SLEEPS:  # a loop that never ends must fail, not hang
            raise AssertionError(f"more than {MAX_SLEEPS} waits: the loop does not end")
        self.sleeps.append(seconds)
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.record(seconds)


def sleeper_of(rig: ClientRig, timeline: Timeline) -> Callable[[float], Any]:
    return timeline.sleep if rig.flavor.is_async else timeline.record


def buying_api(
    rig: ClientRig,
    timeline: Timeline,
    reconciliation: BuyReconciliation | None = None,
    **options: Any,
) -> Any:
    """`BuyingApi` over the rig's generated client."""
    return rig.flavor.cls("buying", "BuyingApi")(
        rig.client.generated,
        reconciliation or BuyReconciliation(delay=DELAY, attempts=3, interval=INTERVAL),
        sleeper=sleeper_of(rig, timeline),
        **options,
    )


def deals_api(rig: ClientRig, timeline: Timeline) -> Any:
    """`DealsApi` over the rig's generated client; its clock is the timeline."""
    return rig.flavor.cls("deals", "DealsApi")(
        rig.client.generated, sleeper=sleeper_of(rig, timeline), clock=timeline
    )


def operations(rig: ClientRig) -> list[tuple[str, dict[str, Any]]]:
    """`(operationName, variables)` of every request sent so far."""
    return [(b["operationName"], b.get("variables", {})) for b in rig.bodies()]


def names(rig: ClientRig) -> list[str]:
    return [name for name, _ in operations(rig)]


def not_found(marker: str = "") -> Reply:
    return json_response(
        {
            "data": None,
            "errors": [
                {
                    "message": f"Deal not found {marker}",
                    "extensions": {"category": NOT_FOUND_CATEGORY},
                }
            ],
        }
    )


def graphql_error(category: str | None = None) -> Reply:
    extensions = {} if category is None else {"extensions": {"category": category}}
    return json_response({"data": None, "errors": [{"message": "Rejected", **extensions}]})


def bought(custom_id: str = CUSTOM_ID, **overrides: Any) -> Reply:
    deal = mp.deal_as(MarketBuyMarketBuy, id=DEAL_ID, customId=custom_id, **overrides)
    return data(market_buy=deal)


def live_deal(custom_id: str | None = CUSTOM_ID, **overrides: Any) -> Reply:
    """A `deal_item` answer."""
    return data(deal_item=mp.deal(id=DEAL_ID, customId=custom_id, **overrides))


def archived_deal(custom_id: str | None = CUSTOM_ID, **overrides: Any) -> Reply:
    """A `deal_history_item` answer."""
    return data(
        deal_history_item=mp.archived_deal(
            id=DEAL_ID, customId=custom_id, status="STEAM_ROLLBACK", **overrides
        )
    )


def history_node(custom_id: str, **overrides: Any) -> dict[str, Any]:
    return mp.archived_as(DealHistoryDealHistoryEdgesNode, customId=custom_id, **overrides)


def cancelled_offer(custom_id: str = CUSTOM_ID) -> Reply:
    node = mp.archived_as(
        DealCancelSendingOfferDealCancelSendingOffer,
        id=DEAL_ID,
        customId=custom_id,
        status="SELLER_CANCELLED",
    )
    return data(deal_cancel_sending_offer=node)


def states(*rows: dict[str, Any]) -> Reply:
    """A `deal_buyer_statuses` answer, one entry per row (`status` defaults to OFFERED)."""
    return data(deal_buyer_statuses=[mp.deal_state(**{"status": "OFFERED", **row}) for row in rows])
