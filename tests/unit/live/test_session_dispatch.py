"""Dispatch, handler errors, subscriptions, replies, close (SDK_SPEC 3.11)."""

import asyncio
import json
from typing import Any

import pytest

from support.live_fakes import Wait, make_rig
from support.live_servers import PRODUCT_CONTENT
from whitemarket.errors.base import DecodeError, LiveConnectionError
from whitemarket.live._connection import ServerClosedError
from whitemarket.live.envelope import Publication, Reply, ReplyError, Unsubscribe
from whitemarket.live.events import (
    DealExchanged,
    DealOffered,
    ProductAdded,
    UnknownEvent,
)


def pub(channel: str, message_type: str, content: dict[str, Any]) -> Publication:
    return Publication(channel, {"message": json.dumps({"type": message_type, "content": content})})


DEAL = {
    "deal_id": "d1",
    "deal_action_type": "buy",
    "market_product_name": "AK",
    "deal_steam_id": "1",
}
PRODUCT = pub("market_products_updates", "market_product_added", PRODUCT_CONTENT)


async def test_poll_returns_the_event_after_its_handlers_ran_in_order() -> None:
    rig = make_rig()
    seen: list[str] = []
    rig.session.on(ProductAdded, lambda e: seen.append("on"))
    rig.session.subscribe_products(lambda e: seen.append("products"))
    rig.connection.reads = [[PRODUCT]]
    event = await rig.session.poll(5)
    assert isinstance(event, ProductAdded)
    assert seen == ["on", "products"]


async def test_channel_filters_products_by_name_and_personal_by_hash_prefix() -> None:
    rig = make_rig()
    products: list[Any] = []
    personal: list[Any] = []
    rig.session.subscribe_products(products.append)
    rig.session.subscribe_personal(personal.append)
    rig.connection.reads = [
        [PRODUCT, pub("#42", "market_deal_offered", DEAL), pub("broadcast", "other", {})]
    ]
    for _ in range(3):
        await rig.session.poll(5)
    assert [type(e) for e in products] == [ProductAdded]
    assert [type(e) for e in personal] == [DealOffered]


async def test_personal_subscription_sends_no_subscribe_and_products_does() -> None:
    rig = make_rig()
    rig.session.subscribe_personal()
    rig.session.subscribe_products()
    await rig.session.connect()
    assert rig.connection.open_calls[0][1] == ["market_products_updates"]
    rig.session.subscribe_personal()
    assert rig.connection.subscribed == []


async def test_unknown_type_is_unknown_event_and_malformed_known_type_also_reports_error() -> None:
    rig = make_rig()
    broken = dict(PRODUCT_CONTENT)
    del broken["price"]
    rig.connection.reads = [
        [
            pub("broadcast", "wallet_balance_updated", {"a": 1}),
            pub("market_products_updates", "market_product_added", broken),
        ]
    ]
    first = await rig.session.poll(5)
    second = await rig.session.poll(5)
    assert isinstance(first, UnknownEvent)
    assert first.type == "wallet_balance_updated"
    assert isinstance(second, UnknownEvent)
    errors = [e for k, e in rig.calls if k == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], DecodeError)
    assert "0.020" not in str(errors[0])
    assert await rig.session.poll(0) is None  # the stream continues, nothing else pending


async def test_a_decode_error_from_the_connection_goes_to_on_error_and_the_stream_continues() -> (
    None
):
    rig = make_rig()
    rig.connection.reads = [[DecodeError("not valid JSON", ("live",)), PRODUCT]]
    assert isinstance(await rig.session.poll(5), ProductAdded)
    assert [type(e) for k, e in rig.calls if k == "error"] == [DecodeError]


async def test_a_handler_exception_propagates_and_the_connection_stays_open() -> None:
    rig = make_rig()

    def boom(event: Any) -> None:
        raise RuntimeError("handler failed")

    rig.session.on(ProductAdded, boom)
    rig.connection.reads = [[PRODUCT, PRODUCT]]
    with pytest.raises(RuntimeError, match="handler failed"):
        await rig.session.poll(5)
    assert rig.connection.closes == 0
    assert len(rig.connection.open_calls) == 1
    with pytest.raises(RuntimeError, match="handler failed"):  # the next event is still delivered
        await rig.session.poll(5)
    assert [k for k, _ in rig.calls].count("error") == 0  # not routed to on_error


async def test_a_lifecycle_callback_exception_propagates_too() -> None:
    rig = make_rig()

    def boom(reconnected: bool) -> None:
        raise RuntimeError("callback failed")

    rig.session.on_connected(boom)
    with pytest.raises(RuntimeError, match="callback failed"):
        await rig.session.connect()


async def test_async_handlers_are_awaited() -> None:
    rig = make_rig()
    seen: list[Any] = []

    async def handler(event: Any) -> None:
        await asyncio.sleep(0)
        seen.append(event)

    rig.session.on(ProductAdded, handler)
    rig.connection.reads = [[PRODUCT]]
    await rig.session.poll(5)
    assert len(seen) == 1


async def test_poll_returns_none_after_the_timeout_and_the_clock_passed() -> None:
    rig = make_rig()
    assert await rig.session.poll(7.0) is None
    assert rig.clock.now == pytest.approx(1007.0)


@pytest.mark.parametrize("bad", [-1.0, float("nan")], ids=["negative", "nan"])
async def test_poll_refuses_a_bad_timeout(bad: float) -> None:
    rig = make_rig()
    with pytest.raises(ValueError, match="timeout"):
        await rig.session.poll(bad)


async def test_subscribe_while_connected_on_ws_subscribes_on_the_open_connection() -> None:
    rig = make_rig()
    await rig.session.connect()
    rig.session.subscribe_products()
    await rig.session.poll(1)
    assert rig.connection.subscribed == ["market_products_updates"]
    assert len(rig.connection.open_calls) == 1


async def test_subscribe_while_connected_on_sse_reconnects_at_once_with_the_new_list() -> None:
    rig = make_rig(can_subscribe=False)
    await rig.session.connect()
    rig.session.subscribe_products()
    await rig.session.poll(1)
    assert [c for _, c in rig.connection.open_calls] == [[], ["market_products_updates"]]
    assert rig.clock.sleeps == []


async def test_105_already_subscribed_counts_as_success_and_other_errors_reach_on_error() -> None:
    rig = make_rig()
    rig.connection.reads = [
        [
            Reply(2, ReplyError(105, "already subscribed", False)),
            Reply(3, ReplyError(103, "denied", False)),
        ]
    ]
    await rig.session.poll(1)
    errors = [e for k, e in rig.calls if k == "error"]
    assert [e.code for e in errors] == [103]
    assert len(rig.connection.open_calls) == 1


async def test_unsubscribe_push_from_2500_resubscribes_below_that_drops_the_channel() -> None:
    rig = make_rig()
    rig.session.subscribe_products()
    await rig.session.connect()
    rig.connection.reads = [[Unsubscribe("market_products_updates", 2500)]]
    await rig.session.poll(1)
    assert rig.connection.subscribed == ["market_products_updates"]
    rig.connection.reads[0] = [Unsubscribe("market_products_updates", 2400)]
    await rig.session.poll(1)
    errors = [e for k, e in rig.calls if k == "error"]
    assert [e.code for e in errors] == [2400]


async def test_a_server_asked_resubscribe_on_sse_is_a_counted_backoff_unless_up_60_seconds() -> (
    None
):
    rig = make_rig(can_subscribe=False)
    rig.session.subscribe_products()
    rig.connection.reads = [
        [Unsubscribe("market_products_updates", 2600)],
        [Wait(60.0), Unsubscribe("market_products_updates", 2600)],
        [],
    ]
    await rig.session.poll(5)
    assert rig.clock.sleeps[:1] == [0.5]  # connected < 60 s: backoff, not immediate
    await rig.session.poll(100)
    # the second connection stayed up 60 s: the reconnect is immediate (no new sleep before it)
    assert len(rig.connection.open_calls) >= 3


async def test_close_closes_the_connection_once_and_is_idempotent() -> None:
    rig = make_rig()
    await rig.session.connect()
    await rig.session.close()
    await rig.session.close()
    assert rig.connection.closes == 1
    disconnects = [i for k, i in rig.calls if k == "disconnected"]
    assert len(disconnects) == 1
    assert (disconnects[0].code, disconnects[0].will_reconnect) == (None, False)
    assert await rig.session.poll(1) is None


async def test_close_from_a_handler_ends_poll_and_the_iterator() -> None:
    rig = make_rig()

    async def closer(event: Any) -> None:
        await rig.session.close()

    rig.session.on(ProductAdded, closer)
    rig.connection.reads = [[PRODUCT, PRODUCT]]
    seen = [event async for event in rig.session]
    assert len(seen) == 1


async def test_close_from_another_task_wakes_a_blocked_poll() -> None:
    rig = make_rig()
    gate = asyncio.Event()
    rig.connection.block = gate
    await rig.session.connect()
    task = asyncio.create_task(rig.session.poll(None))
    await asyncio.sleep(0)
    await rig.session.close()
    gate.set()
    assert await asyncio.wait_for(task, 2) is None


async def test_a_second_consumer_is_refused() -> None:
    rig = make_rig()
    gate = asyncio.Event()
    rig.connection.block = gate
    await rig.session.connect()
    first = asyncio.create_task(rig.session.poll(None))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="one consumer"):
        await rig.session.poll(1)
    await rig.session.close()
    gate.set()
    await first


async def test_run_dispatches_for_the_duration_then_returns() -> None:
    rig = make_rig()
    seen: list[Any] = []
    rig.session.on(ProductAdded, seen.append)
    rig.connection.reads = [[PRODUCT, PRODUCT]]
    await rig.session.run(5.0)
    assert len(seen) == 2


async def test_wait_for_deal_event_returns_the_event_of_that_deal_and_dispatches_others() -> None:
    rig = make_rig()
    seen: list[Any] = []
    rig.session.on(DealOffered, seen.append)
    other = dict(DEAL, deal_id="d2")
    rig.connection.reads = [
        [
            pub("#42", "market_deal_offered", other),
            PRODUCT,
            pub("#42", "market_deal_exchanged", DEAL),
        ]
    ]
    event = await rig.session.wait_for_deal_event("d1", 30.0)
    assert isinstance(event, DealExchanged)
    assert event.deal_id == "d1"
    assert len(seen) == 1  # the other deal's event still went to its handler


async def test_wait_for_deal_event_times_out_with_none() -> None:
    rig = make_rig()
    assert await rig.session.wait_for_deal_event("d1", 3.0) is None
    assert rig.clock.now == pytest.approx(1003.0)


async def test_the_token_never_reaches_the_lifecycle_callbacks_or_errors() -> None:
    rig = make_rig()
    rig.connection.reads = [[ServerClosedError(3000, "x")], []]
    await rig.session.poll(5)
    assert "jwt-" not in repr(rig.calls)


def test_live_connection_error_names_the_code_not_the_reason() -> None:
    error = LiveConnectionError(3500, "secret-looking reason")
    assert "secret-looking" not in str(error)
    assert (error.code, error.reason) == (3500, "secret-looking reason")
