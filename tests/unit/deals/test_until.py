"""`Until`: the ready-made `wait_for` conditions (SDK_SPEC 3.4 rule 5)."""

import pytest

from whitemarket.deals import Until
from whitemarket.models import DealStatus
from whitemarket.models.deals import DealState
from whitemarket.models.money import Money

OFFERED = {"OFFERED", "BUYER_OFFERED", "SELLER_OFFERED", "NEED_CONFIRMATION"}
FINAL = {
    "COMPLETED", "CANCELLED", "BUYER_CANCELLED", "SELLER_CANCELLED", "EXPIRED", "BUYER_EXPIRED",
    "SELLER_EXPIRED", "EXPIRING", "STEAM_ROLLBACK", "BUYER_STEAM_ROLLBACK", "SELLER_STEAM_ROLLBACK",
}  # fmt: skip
EARLY = {
    "HOLD", "INITIATED", "QUEUED", "SELLER_SENDING_STEAM_OFFER", "WAITING_STEAM_QUEUE",
    "BUYER_CANCEL_REQUESTED",
}  # fmt: skip


def state(status: str) -> DealState:
    return DealState(
        id="d",
        custom_id=None,
        status=DealStatus(status),
        cancel_reason=None,
        price=Money.usd("1"),
        steam_id=None,
        trade_id=None,
        is_trade_protected=None,
        settlement_time_at=None,
        reverse_penalty=None,
        reverse_refund=None,
    )


def matches(status: str) -> dict[str, bool]:
    s = state(status)
    return {
        "offered": Until.offered()(s),
        "exchanged_or_completed": Until.exchanged_or_completed()(s),
        "completed": Until.completed()(s),
        "final": Until.final()(s),
    }


@pytest.mark.parametrize("status", sorted(EARLY))
def test_nothing_matches_before_the_offer(status: str) -> None:
    assert matches(status) == {
        "offered": False,
        "exchanged_or_completed": False,
        "completed": False,
        "final": False,
    }


@pytest.mark.parametrize("status", sorted(OFFERED))
def test_offered_matches_the_offer_statuses_only(status: str) -> None:
    assert matches(status) == {
        "offered": True,
        "exchanged_or_completed": False,
        "completed": False,
        "final": False,
    }


def test_exchanged_matches_offered_and_exchanged_but_not_final() -> None:
    assert matches("EXCHANGED") == {
        "offered": True,
        "exchanged_or_completed": True,
        "completed": False,
        "final": False,
    }


@pytest.mark.parametrize("status", sorted(FINAL))
def test_every_predicate_also_matches_a_final_status(status: str) -> None:
    # SDK_SPEC 3.4 rule 5: a wait never outlives a failed or reversed deal.
    assert matches(status) == {
        "offered": True,
        "exchanged_or_completed": True,
        "completed": True,
        "final": True,
    }


def test_an_unknown_status_matches_no_predicate() -> None:
    assert not any(matches("TELEPORTED").values())


def test_the_table_covers_every_status() -> None:
    assert OFFERED | FINAL | EARLY | {"EXCHANGED"} == {s.value for s in DealStatus}


def test_until_is_not_instantiable() -> None:
    with pytest.raises(TypeError):
        Until()
