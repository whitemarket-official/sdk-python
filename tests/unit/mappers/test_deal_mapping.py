"""Generated result -> `Deal` (in progress and archived) and `DealState` (SDK_SPEC 3.4)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from support import market_payloads as mp
from whitemarket import Secret
from whitemarket._generated.deal_buyer_statuses import DealBuyerStatusesDealBuyerStatuses
from whitemarket._generated.deal_history_item import DealHistoryItemDealHistoryItem
from whitemarket._generated.deal_item import DealItemDealItem
from whitemarket._mappers.deals import deal_state_of, map_archived_deal, map_deal, map_deal_state
from whitemarket.errors import DecodeError
from whitemarket.models import DealCancelReason, DealStatus, DeliveryType, Money

URL = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=synthetic"


def deal_of(**overrides: Any) -> Any:
    return map_deal(DealItemDealItem.model_validate(mp.deal(**overrides)), ("deal_item",))


def archived_of(**overrides: Any) -> Any:
    raw = DealHistoryItemDealHistoryItem.model_validate(mp.archived_deal(**overrides))
    return map_archived_deal(raw, ("deal_history_item",))


def state_of(**overrides: Any) -> Any:
    raw = DealBuyerStatusesDealBuyerStatuses.model_validate(mp.deal_state(**overrides))
    return map_deal_state(raw, ("deal_buyer_statuses", 0))


def test_a_deal_in_progress_maps_its_own_fields() -> None:
    deal = deal_of(
        steamId="765",
        tradeId="t-1",
        settlementTimeAt="2026-11-09T10:00:00+00:00",
        status="EXCHANGED",
    )

    assert (deal.id, deal.custom_id, deal.status) == ("deal-1", "custom-1", DealStatus.EXCHANGED)
    assert deal.price == Money.usd("12.50")
    assert deal.delivery_type is DeliveryType.SEMI
    assert (deal.steam_id, deal.trade_id) == ("765", "t-1")
    assert deal.is_trade_protected is True
    assert deal.settlement_time_at == datetime(2026, 11, 9, 10, tzinfo=UTC)
    assert deal.expires_at is not None
    assert deal.expires_at.utcoffset() is not None
    assert (deal.is_cancel_by_buyer_supported, deal.cancel_by_buyer_need_wait) == (True, 120)
    assert deal.product.status.value == "DEAL"
    assert not deal.is_archived


def test_a_deal_in_progress_has_none_of_the_archived_only_fields() -> None:
    deal = deal_of()

    assert (deal.cancel_reason, deal.archived_at, deal.reverse_penalty, deal.reverse_refund) == (
        None,
        None,
        None,
        None,
    )


def test_the_receiver_trade_url_is_a_secret_that_repr_does_not_show() -> None:
    deal = deal_of(receiverTradeUrl=URL)

    assert isinstance(deal.receiver_trade_url, Secret)
    assert deal.receiver_trade_url.reveal() == URL
    assert "token=synthetic" not in repr(deal)
    assert "token=synthetic" not in str(deal)


@pytest.mark.parametrize("value", [None, ""], ids=["null", "empty"])
def test_a_null_or_empty_receiver_trade_url_is_no_url(value: str | None) -> None:
    assert deal_of(receiverTradeUrl=value).receiver_trade_url is None


def test_a_deal_maps_its_item_when_it_has_one() -> None:
    item = mp.item()
    del item["product"], item["deal"]

    assert deal_of(item=None).item is None
    assert deal_of(item={"__typename": "TF2InventoryItem"}).item is None


def test_an_archived_deal_maps_its_own_fields() -> None:
    deal = archived_of(
        status="STEAM_ROLLBACK",
        cancelReason="INSTANT_EXCHANGE_FAILED",
        reversePenaltyValue=mp.money("1.250"),
        reverseRefundValue=mp.money("11.25"),
    )

    assert deal.status is DealStatus.STEAM_ROLLBACK
    assert deal.cancel_reason is DealCancelReason.INSTANT_EXCHANGE_FAILED
    assert deal.archived_at == datetime(2026, 11, 2, 10, tzinfo=UTC)
    assert deal.is_archived
    assert (deal.reverse_penalty, deal.reverse_refund) == (Money.usd("1.250"), Money.usd("11.25"))
    assert deal.product.id == "listing-1"


def test_an_archived_deal_has_none_of_the_in_progress_only_fields() -> None:
    deal = archived_of()

    assert deal.trade_id is None
    assert (deal.is_trade_protected, deal.settlement_time_at, deal.expires_at) == (None, None, None)
    assert (deal.is_cancel_by_buyer_supported, deal.cancel_by_buyer_need_wait) == (False, None)
    assert (deal.item, deal.receiver_trade_url) == (None, None)


@pytest.mark.parametrize(
    ("mapper", "field", "path"),
    [
        pytest.param(deal_of, "price", ("deal_item", "price", "value"), id="deal price"),
        pytest.param(
            archived_of, "price", ("deal_history_item", "price", "value"), id="archived price"
        ),
        pytest.param(
            archived_of,
            "reversePenaltyValue",
            ("deal_history_item", "reversePenaltyValue", "value"),
            id="penalty",
        ),
        pytest.param(
            archived_of,
            "reverseRefundValue",
            ("deal_history_item", "reverseRefundValue", "value"),
            id="refund",
        ),
    ],
)
def test_a_malformed_amount_names_its_path(mapper: Any, field: str, path: tuple[str, ...]) -> None:
    with pytest.raises(DecodeError) as caught:
        mapper(**{field: {"currency": "USD", "value": "12.5.0"}})

    assert caught.value.path == path


def test_unknown_status_and_cancel_reason_keep_the_raw_value() -> None:
    deal = archived_of(status="TELEPORTED", cancelReason="ABDUCTED")

    assert deal.status.is_unknown
    assert deal.status.value == "TELEPORTED"
    assert deal.cancel_reason is not None
    assert deal.cancel_reason.is_unknown
    assert deal.cancel_reason.value == "ABDUCTED"
    assert not deal.status.is_final()


def test_a_null_cancel_reason_stays_none() -> None:
    assert archived_of(cancelReason=None).cancel_reason is None


def test_a_deal_state_maps_every_field() -> None:
    state = state_of(
        cancelReason="NO_FUNDS",
        steamId="765",
        tradeId="t",
        reversePenaltyValue=mp.money("0.5"),
        reverseRefundValue=mp.money("9"),
    )

    assert (state.id, state.custom_id, state.status) == ("deal-1", "custom-1", DealStatus.EXCHANGED)
    assert state.cancel_reason is DealCancelReason.NO_FUNDS
    assert state.price == Money.usd("12.50")
    assert (state.steam_id, state.trade_id) == ("765", "t")
    assert state.is_trade_protected is True
    assert state.settlement_time_at == datetime(2026, 11, 9, 10, tzinfo=UTC)
    assert (state.reverse_penalty, state.reverse_refund) == (Money.usd("0.5"), Money.usd("9"))


def test_a_deal_state_keeps_a_not_reported_protection_flag_as_none() -> None:
    assert state_of(isTradeProtected=None).is_trade_protected is None


def test_a_deal_state_malformed_amount_names_its_path() -> None:
    with pytest.raises(DecodeError) as caught:
        state_of(price={"currency": "USD", "value": "nope"})

    assert caught.value.path == ("deal_buyer_statuses", 0, "price", "value")


@pytest.mark.parametrize(
    "deal",
    [
        pytest.param(
            lambda: deal_of(status="EXCHANGED", steamId="s", tradeId="t"), id="in progress"
        ),
        pytest.param(
            lambda: archived_of(
                reversePenaltyValue=mp.money("1"), reverseRefundValue=mp.money("2")
            ),
            id="archived",
        ),
    ],
)
def test_the_state_of_a_deal_repeats_its_status_fields(deal: Any) -> None:
    source = deal()

    state = deal_state_of(source)

    assert (state.id, state.custom_id, state.status, state.cancel_reason, state.price) == (
        source.id,
        source.custom_id,
        source.status,
        source.cancel_reason,
        source.price,
    )
    assert (state.steam_id, state.trade_id, state.is_trade_protected, state.settlement_time_at) == (
        source.steam_id,
        source.trade_id,
        source.is_trade_protected,
        source.settlement_time_at,
    )
    assert (state.reverse_penalty, state.reverse_refund) == (
        source.reverse_penalty,
        source.reverse_refund,
    )
