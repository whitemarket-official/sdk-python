"""`deals.wait_for(..., live=session)` with a real `AsyncLiveSession` on a scripted connection.

The unit tests of `test_wait_for.py` drive a stand-in for the session; this module shows the real
session wakes the wait up (async flavor: the sync `LiveSession` runs the same engine on a thread and
has its own tests). The HTTP side is the usual scripted client; the clock is the live fakes' clock,
shared by the session and the API, so no real time passes.
"""

import json
from typing import Any

import pytest

from support.clients import ClientRig
from support.deal_apis import DEAL_ID as ID
from support.deal_apis import OTHER_ID, states
from support.flavors import ASYNC
from support.live_fakes import Wait, make_live_rig
from support.live_servers import PRODUCT_CONTENT
from whitemarket import RetryPolicy
from whitemarket._async.deals import AsyncDealsApi
from whitemarket.deals import Until
from whitemarket.errors import DealWaitTimeoutError
from whitemarket.live._envelope import Publication
from whitemarket.live.events import DealOffered
from whitemarket.models import DealStatus


def pub(message_type: str, content: dict[str, Any], channel: str = "#42") -> Publication:
    return Publication(channel, {"message": json.dumps({"type": message_type, "content": content})})


def deal_event(deal_id: str) -> Publication:
    content = {
        "deal_id": deal_id,
        "deal_action_type": "buy",
        "market_product_name": "AK",
        "deal_steam_id": "1",
    }
    return pub("market_deal_offered", content)


PRODUCT = pub("market_product_added", PRODUCT_CONTENT, "market_products_updates")


def row(status: str) -> dict[str, Any]:
    return {"id": ID, "customId": "order-1", "status": status}


def test_a_deal_event_of_the_waited_deal_wakes_the_wait_before_the_interval() -> None:
    live = make_live_rig()
    live.connection.reads = [[Wait(2.0), deal_event(ID)]]
    http = ClientRig(
        ASYNC, states(row("INITIATED")), states(row("OFFERED")), retry=RetryPolicy.none()
    )
    api = AsyncDealsApi(http.client.generated, sleeper=live.clock.sleep, clock=live.clock)
    started = live.clock.now
    with http:
        state = http.call(
            api.wait_for("order-1", Until.offered(), poll_interval=20.0, live=live.session)
        )

        assert state.status is DealStatus.OFFERED
        assert http.script.count == 2
        assert live.clock.now - started == 2.0, "woken by the event, not after the 20 s interval"
        assert live.clock.sleeps == []


def test_events_of_other_deals_and_products_do_not_wake_the_wait() -> None:
    live = make_live_rig()
    live.connection.reads = [[Wait(1.0), PRODUCT, deal_event(OTHER_ID), PRODUCT]]
    http = ClientRig(
        ASYNC, states(row("INITIATED")), states(row("OFFERED")), retry=RetryPolicy.none()
    )
    api = AsyncDealsApi(http.client.generated, sleeper=live.clock.sleep, clock=live.clock)
    started = live.clock.now
    with http:
        http.call(api.wait_for("order-1", Until.offered(), poll_interval=10.0, live=live.session))

        assert live.clock.now - started == 10.0, "the full interval passed before the next poll"
        assert http.script.count == 2


def test_the_timeout_applies_with_live_too() -> None:
    live = make_live_rig()
    http = ClientRig(ASYNC, states(row("INITIATED")), retry=RetryPolicy.none())
    api = AsyncDealsApi(http.client.generated, sleeper=live.clock.sleep, clock=live.clock)
    with http, pytest.raises(DealWaitTimeoutError) as caught:
        http.call(
            api.wait_for(
                "order-1", Until.offered(), timeout=1.0, poll_interval=3600.0, live=live.session
            )
        )

    assert caught.value.last_state is not None
    assert caught.value.last_state.status is DealStatus.INITIATED
    assert http.script.count == 2


def test_an_exception_of_a_live_handler_propagates_out_of_the_wait() -> None:
    live = make_live_rig()
    live.connection.reads = [[Wait(1.0), deal_event(OTHER_ID)]]

    def boom(event: DealOffered) -> None:
        raise RuntimeError("handler failed")

    live.session.on(DealOffered, boom)
    http = ClientRig(ASYNC, states(row("INITIATED")), retry=RetryPolicy.none())
    api = AsyncDealsApi(http.client.generated, sleeper=live.clock.sleep, clock=live.clock)
    with http, pytest.raises(RuntimeError, match="handler failed"):
        http.call(api.wait_for("order-1", Until.offered(), live=live.session))


def test_a_closed_session_does_not_spin_the_rest_of_the_interval_is_slept() -> None:
    live = make_live_rig()
    http = ClientRig(
        ASYNC, states(row("INITIATED")), states(row("OFFERED")), retry=RetryPolicy.none()
    )
    api = AsyncDealsApi(http.client.generated, sleeper=live.clock.sleep, clock=live.clock)
    with http:
        http.call(live.session.close())
        http.call(api.wait_for("order-1", Until.offered(), poll_interval=4.0, live=live.session))

        assert live.clock.sleeps == [4.0]
