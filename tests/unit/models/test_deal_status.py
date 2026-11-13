"""`DealStatus`: the classification table of WHITEMARKET_API.md 4, row by row (SDK_SPEC 3.4)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from support import market_payloads as mp
from whitemarket._generated.deal_buyer_statuses import DealBuyerStatusesDealBuyerStatuses
from whitemarket._generated.deal_item import DealItemDealItem
from whitemarket._mappers.deals import map_deal, map_deal_state
from whitemarket.models import DealStatus, awaiting_trade_protection
from whitemarket.models.deals import DealState
from whitemarket.models.money import Money

TABLE = {
    "in progress": [
        "HOLD", "INITIATED", "QUEUED", "SELLER_SENDING_STEAM_OFFER", "WAITING_STEAM_QUEUE",
        "BUYER_CANCEL_REQUESTED", "OFFERED", "BUYER_OFFERED", "SELLER_OFFERED", "NEED_CONFIRMATION",
    ],
    "exchanged": ["EXCHANGED"],
    "successful": ["COMPLETED"],
    "failed": [
        "CANCELLED", "BUYER_CANCELLED", "SELLER_CANCELLED", "EXPIRED", "BUYER_EXPIRED",
        "SELLER_EXPIRED", "EXPIRING",
    ],
    "reversed": ["STEAM_ROLLBACK", "BUYER_STEAM_ROLLBACK", "SELLER_STEAM_ROLLBACK"],
}  # fmt: skip
ROWS = [pytest.param(v, g, id=f"{v} -> {g}") for g, vs in TABLE.items() for v in vs]


def groups_of(status: DealStatus) -> list[str]:
    flags = {
        "in progress": status.is_in_progress(),
        "exchanged": status.is_exchanged(),
        "successful": status.is_successful(),
        "failed": status.is_failed(),
        "reversed": status.is_reversed(),
    }
    return [group for group, flag in flags.items() if flag]


@pytest.mark.parametrize(("value", "group"), ROWS)
def test_a_status_belongs_to_exactly_the_group_of_the_table(value: str, group: str) -> None:
    status = DealStatus(value)

    assert groups_of(status) == [group]
    assert status.is_final() is (group in {"successful", "failed", "reversed"})


def test_the_table_covers_every_status() -> None:
    classified = {value for values in TABLE.values() for value in values}

    assert classified == {status.value for status in DealStatus}


def test_an_unknown_status_belongs_to_no_group_and_is_not_final() -> None:
    status = DealStatus("TELEPORTED")

    assert status.is_unknown
    assert groups_of(status) == []
    assert not status.is_final()


def state(status: str, protected: bool | None = True) -> DealState:
    return DealState(
        id="d",
        custom_id=None,
        status=DealStatus(status),
        cancel_reason=None,
        price=Money.usd("1"),
        steam_id=None,
        trade_id=None,
        is_trade_protected=protected,
        settlement_time_at=datetime(2026, 11, 9, tzinfo=UTC),
        reverse_penalty=None,
        reverse_refund=None,
    )


@pytest.mark.parametrize(
    ("status", "protected", "expected"),
    [
        pytest.param("EXCHANGED", True, True, id="exchanged and protected"),
        pytest.param("EXCHANGED", False, False, id="exchanged, not protected"),
        pytest.param("EXCHANGED", None, False, id="exchanged, protection not reported"),
        pytest.param("COMPLETED", True, False, id="completed"),
        pytest.param("OFFERED", True, False, id="not exchanged yet"),
        pytest.param("TELEPORTED", True, False, id="unknown status"),
    ],
)
def test_awaiting_trade_protection(status: str, protected: bool | None, expected: bool) -> None:
    assert awaiting_trade_protection(state(status, protected)) is expected


def test_awaiting_trade_protection_reads_a_deal_too() -> None:
    def deal(status: str, protected: bool) -> Any:
        raw = DealItemDealItem.model_validate(mp.deal(status=status, isTradeProtected=protected))
        return map_deal(raw, ("deal_item",))

    assert awaiting_trade_protection(deal("EXCHANGED", True))
    assert not awaiting_trade_protection(deal("EXCHANGED", False))


def test_a_status_snapshot_maps_with_the_status_enum() -> None:
    raw = DealBuyerStatusesDealBuyerStatuses.model_validate(mp.deal_state(status="QUEUED"))

    mapped = map_deal_state(raw, ("deal_buyer_statuses", 0))

    assert mapped.status is DealStatus.QUEUED
    assert mapped.status.is_in_progress()
