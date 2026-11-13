"""Live event models: construction, immutability, no personal data in `repr`."""

import dataclasses
from decimal import Decimal
from typing import Any

import pytest

from whitemarket._generated.enums import MarketDealActionType
from whitemarket.live.events import (
    DealCancelled,
    DealCompleted,
    DealEvent,
    DealExchanged,
    DealExpired,
    DealHold,
    DealInitiated,
    DealNeedConfirmation,
    DealOffered,
    LiveEvent,
    ProductAdded,
    ProductEdited,
    ProductRemoved,
    UnknownEvent,
)
from whitemarket.models.enums import DeliveryPromise, DeliveryType
from whitemarket.models.money import Money

STEAM_MARK = "SYNTHETIC-STEAM-MARK"


def _added() -> ProductAdded:
    return ProductAdded(
        channel="market_products_updates",
        id="p-1",
        app_id="730",
        asset_id="7000000001",
        class_id="7000000002",
        instance_id="0",
        price=Money.usd("2.100"),
        market_hash_name="AK-47 | Test (Field-Tested)",
    )


def test_product_added_optional_fields_default_to_none_and_empty() -> None:
    event = _added()

    assert (event.inspect_link, event.delivery_type, event.delivery_promise) == (None, None, None)
    assert (event.float, event.paint_index, event.paint_seed) == (None, None, None)
    assert event.stickers == []
    assert event.keychains == []
    assert dict(event.extra) == {}


def test_product_added_keeps_exact_decimal_values() -> None:
    event = dataclasses.replace(
        _added(),
        float=Decimal("0.152345"),
        delivery_type=DeliveryType.SEMI,
        delivery_promise=DeliveryPromise.MINUTES10,
    )

    assert event.price.amount == Decimal("2.100")
    assert str(event.price.amount) == "2.100"
    assert event.float == Decimal("0.152345")
    assert isinstance(event, LiveEvent)


def test_product_edited_is_partial_by_default() -> None:
    event = ProductEdited(channel="c", id="p-1", price=Money.usd("2.10"))

    assert event.price is not None
    assert (event.app_id, event.market_hash_name, event.float) == (None, None, None)
    assert (event.stickers, event.keychains) == (None, None)


def test_product_removed_requires_the_identifying_fields() -> None:
    incomplete: Any = (
        ProductRemoved  # the signature is checked at run time, not by the type checker
    )
    with pytest.raises(TypeError):
        incomplete(channel="c", id="p-1")


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(_added(), id="added"),
        pytest.param(ProductEdited(channel="c", id="p-1"), id="edited"),
        pytest.param(
            DealCompleted(channel="#1", deal_id="d-1", action=MarketDealActionType.BUY),
            id="deal",
        ),
        pytest.param(UnknownEvent(channel="c", type=None, raw_content="x"), id="unknown"),
    ],
)
def test_events_are_frozen(event: LiveEvent) -> None:
    attribute = "channel"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(event, attribute, "other")


@pytest.mark.parametrize(
    "cls",
    [
        DealInitiated,
        DealOffered,
        DealNeedConfirmation,
        DealExchanged,
        DealCompleted,
        DealExpired,
        DealCancelled,
        DealHold,
    ],
)
def test_deal_events_hide_the_steam_id_from_repr(cls: type[DealEvent]) -> None:
    event = cls(
        channel="#1",
        deal_id="d-1",
        action=MarketDealActionType.SELL,
        product_name="AK-47 | Test",
        steam_id=STEAM_MARK,
    )

    assert event.steam_id == STEAM_MARK
    assert STEAM_MARK not in repr(event)
    assert STEAM_MARK not in str(event)
    assert "d-1" in repr(event)


def test_deal_leaves_are_distinct_types() -> None:
    hold = DealHold(channel="#1", deal_id="d-1", action=MarketDealActionType.BUY)
    expired = DealExpired(channel="#1", deal_id="d-1", action=MarketDealActionType.BUY)

    assert hold != expired
    assert hold == DealHold(channel="#1", deal_id="d-1", action=MarketDealActionType.BUY)


def test_unknown_event_holds_type_and_raw_content() -> None:
    event = UnknownEvent(channel="broadcast", type="x_new", raw_content={"a": 1})

    assert (event.channel, event.type, event.raw_content) == ("broadcast", "x_new", {"a": 1})
    assert UnknownEvent(channel="c", type=None, raw_content=[1]).type is None
