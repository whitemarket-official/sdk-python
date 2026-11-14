"""`deals.wait_for()`: polling, deadline arithmetic, seller deals, live wake-up (SDK_SPEC 3.4).

Time is a `Timeline` that only moves when the API sleeps (async and sync flavor alike); no test
waits for real.
"""

import math
import time
from typing import Any

import pytest

from support.clients import ClientRig
from support.deal_apis import (
    DEAL_ID as ID,
)
from support.deal_apis import (
    OTHER_ID,
    Timeline,
    deals_api,
    live_deal,
    names,
    not_found,
    operations,
    states,
)
from support.flavors import Flavor
from support.http import reply
from whitemarket import RetryPolicy
from whitemarket.deals import Until
from whitemarket.errors import DealWaitTimeoutError, ServerError
from whitemarket.models import DealState, DealStatus

NO_RETRY = RetryPolicy(max_attempts=1)


def row(status: str, custom_id: str | None = "order-1") -> dict[str, Any]:
    return {"id": ID, "customId": custom_id, "status": status}


def setup(flavor: Flavor, *outcomes: Any) -> tuple[ClientRig, Timeline, Any]:
    rig = ClientRig(flavor, *outcomes, retry=NO_RETRY)
    timeline = Timeline()
    return rig, timeline, deals_api(rig, timeline)


def test_returns_the_state_of_the_first_poll_that_matches_without_sleeping(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("OFFERED")))
    with rig:
        state = rig.call(api.wait_for("order-1", Until.offered()))

        assert (state.id, state.status) == (ID, DealStatus.OFFERED)
        assert operations(rig) == [("DealBuyerStatuses", {"ids": ["order-1"]})]
        assert timeline.sleeps == []


def test_polls_every_five_seconds_by_default_until_the_state_matches(flavor: Flavor) -> None:
    rig, timeline, api = setup(
        flavor,
        states(row("INITIATED")),
        states(row("SELLER_SENDING_STEAM_OFFER")),
        states(row("EXCHANGED")),
    )
    with rig:
        state = rig.call(api.wait_for("order-1", Until.exchanged_or_completed()))

        assert state.status is DealStatus.EXCHANGED
        assert rig.script.count == 3
        assert timeline.sleeps == [5.0, 5.0]


def test_uses_the_given_poll_interval(flavor: Flavor) -> None:
    rig, timeline, api = setup(
        flavor, states(row("INITIATED", None)), states(row("COMPLETED", None))
    )
    with rig:
        rig.call(api.wait_for(ID, Until.final(), poll_interval=0.25))

        assert timeline.sleeps == [0.25]


def test_passes_each_state_to_the_callers_condition(flavor: Flavor) -> None:
    seen: list[DealStatus] = []

    def until(state: DealState) -> bool:
        seen.append(state.status)
        return state.status is DealStatus.HOLD

    rig, _, api = setup(flavor, states(row("INITIATED", None)), states(row("HOLD", None)))
    with rig:
        state = rig.call(api.wait_for(ID, until))

        assert seen == [DealStatus.INITIATED, DealStatus.HOLD]
        assert state.status is DealStatus.HOLD


def test_gives_up_when_the_timeout_has_elapsed_and_carries_the_last_state(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("INITIATED")))
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(api.wait_for("order-1", Until.offered(), timeout=12.0))

        error = caught.value
        assert (error.id_or_custom_id, error.timeout) == ("order-1", 12.0)
        assert error.last_state is not None
        assert (error.last_state.id, error.last_state.status) == (ID, DealStatus.INITIATED)
        # Polls at 0 s, 5 s, 10 s and 12 s (the last sleep is capped at the 2 s that remain).
        assert rig.script.count == 4
        assert timeline.sleeps == [5.0, 5.0, 2.0]


def test_never_sleeps_past_the_timeout_and_checks_once_more_at_the_deadline(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("INITIATED", None)))
    with rig:
        with pytest.raises(DealWaitTimeoutError):
            rig.call(api.wait_for(ID, Until.offered(), timeout=1.0, poll_interval=3600.0))

        assert timeline.sleeps == [1.0]
        assert rig.script.count == 2


def test_returns_a_match_found_by_the_poll_at_the_deadline(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("INITIATED", None)), states(row("OFFERED", None)))
    with rig:
        state = rig.call(api.wait_for(ID, Until.offered(), timeout=1.0, poll_interval=3600.0))

        assert state.status is DealStatus.OFFERED
        assert timeline.sleeps == [1.0]
        assert rig.script.count == 2


def test_sleeps_the_full_interval_without_a_timeout(flavor: Flavor) -> None:
    rig, timeline, api = setup(
        flavor, states(row("INITIATED", None)), states(row("COMPLETED", None))
    )
    with rig:
        rig.call(api.wait_for(ID, Until.final(), poll_interval=3600.0))

        assert timeline.sleeps == [3600.0]


def test_stops_exactly_when_the_elapsed_time_equals_the_timeout(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("INITIATED", None)))
    with rig:
        with pytest.raises(DealWaitTimeoutError):
            rig.call(api.wait_for(ID, Until.offered(), timeout=10.0))

        assert rig.script.count == 3, "polls at 0 s, 5 s and 10 s; at 10 s the timeout has elapsed"
        assert timeline.sleeps == [5.0, 5.0]


def test_a_timeout_of_zero_polls_exactly_once(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(row("INITIATED", None)))
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(api.wait_for(ID, Until.offered(), timeout=0.0))

        assert caught.value.last_state is not None
        assert caught.value.last_state.status is DealStatus.INITIATED
        assert rig.script.count == 1
        assert timeline.sleeps == []


def test_a_timeout_of_zero_still_returns_a_match_of_the_first_poll(flavor: Flavor) -> None:
    rig, _, api = setup(flavor, states(row("COMPLETED", None)))
    with rig:
        assert rig.call(api.wait_for(ID, Until.final(), timeout=0.0)).status is DealStatus.COMPLETED


def test_keeps_polling_while_the_deal_is_not_visible_yet(flavor: Flavor) -> None:
    rig, timeline, api = setup(
        flavor,
        states(),
        not_found("item"),
        not_found("history"),
        live_deal("order-1", status="OFFERED"),
    )
    with rig:
        state = rig.call(api.wait_for("order-1", Until.offered()))

        assert state.status is DealStatus.OFFERED
        assert rig.script.count == 4
        assert timeline.sleeps == [5.0]


def test_keeps_polling_on_a_status_it_does_not_know(flavor: Flavor) -> None:
    rig, _, api = setup(flavor, states(row("SOMETHING_NEW", None)), states(row("COMPLETED", None)))
    with rig:
        state = rig.call(api.wait_for(ID, Until.final()))

        assert state.status is DealStatus.COMPLETED
        assert rig.script.count == 2


def test_lets_a_failed_poll_through(flavor: Flavor) -> None:
    rig, _, api = setup(flavor, reply(500))
    with rig:
        with pytest.raises(ServerError):
            rig.call(api.wait_for(ID, Until.final()))

        assert rig.script.count == 1


# ---- a seller's deal is not in deal_buyer_statuses --------------------------------------------


def test_reads_a_seller_deal_with_get_when_the_statuses_do_not_know_it(flavor: Flavor) -> None:
    rig, timeline, api = setup(flavor, states(), live_deal("order-1", status="OFFERED"))
    with rig:
        state = rig.call(api.wait_for("order-1", Until.offered()))

        assert (state.id, state.custom_id, state.status) == (ID, "order-1", DealStatus.OFFERED)
        assert operations(rig) == [
            ("DealBuyerStatuses", {"ids": ["order-1"]}),
            ("DealItem", {"customId": "order-1"}),
        ]
        assert timeline.sleeps == []


def test_polls_only_deal_item_after_the_first_fallback(flavor: Flavor) -> None:
    rig, timeline, api = setup(
        flavor,
        states(),
        live_deal("order-1", status="INITIATED"),
        live_deal("order-1", status="SELLER_NEED_CONFIRMATION"),
        live_deal("order-1", status="OFFERED"),
    )
    with rig:
        state = rig.call(api.wait_for("order-1", Until.offered()))

        assert state.status is DealStatus.OFFERED
        assert names(rig) == ["DealBuyerStatuses", "DealItem", "DealItem", "DealItem"]
        assert timeline.sleeps == [5.0, 5.0]


def test_keeps_using_only_the_statuses_for_a_buyer_deal(flavor: Flavor) -> None:
    rig, _, api = setup(flavor, states(row("INITIATED")), states(row("OFFERED")))
    with rig:
        rig.call(api.wait_for("order-1", Until.offered()))

        assert names(rig) == ["DealBuyerStatuses", "DealBuyerStatuses"]


def test_times_out_when_neither_the_statuses_nor_the_deal_lookup_know_the_deal(
    flavor: Flavor,
) -> None:
    rig, _, api = setup(flavor, states(), *[not_found(str(i)) for i in range(4)])
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(api.wait_for("order-1", Until.offered(), timeout=5.0))

        assert caught.value.last_state is None
        assert operations(rig) == [
            ("DealBuyerStatuses", {"ids": ["order-1"]}),
            ("DealItem", {"customId": "order-1"}),
            ("DealHistoryItem", {"customId": "order-1"}),
            ("DealItem", {"customId": "order-1"}),
            ("DealHistoryItem", {"customId": "order-1"}),
        ]


# ---- argument validation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "timeout", "poll_interval"),
    [
        pytest.param("", None, 5.0, id="empty reference"),
        pytest.param("order-1", None, 0.0, id="poll interval 0"),
        pytest.param("order-1", None, -1.0, id="negative poll interval"),
        pytest.param("order-1", None, math.inf, id="infinite poll interval"),
        pytest.param("order-1", None, math.nan, id="NaN poll interval"),
        pytest.param("order-1", -1.0, 5.0, id="negative timeout"),
        pytest.param("order-1", math.inf, 5.0, id="infinite timeout"),
        pytest.param("order-1", math.nan, 5.0, id="NaN timeout"),
    ],
)
def test_rejects_invalid_arguments_before_any_request(
    flavor: Flavor, reference: str, timeout: float | None, poll_interval: float
) -> None:
    rig, timeline, api = setup(flavor)
    with rig:
        with pytest.raises(ValueError, match=r"empty|poll_interval|timeout"):
            rig.call(
                api.wait_for(reference, Until.final(), timeout=timeout, poll_interval=poll_interval)
            )

        assert rig.script.count == 0
        assert timeline.sleeps == []


def test_the_timeout_error_names_the_reference_the_status_and_no_secret(flavor: Flavor) -> None:
    rig, _, api = setup(flavor, states(row("INITIATED")))
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(api.wait_for("order-1", Until.offered(), timeout=0))

        assert str(caught.value) == (
            "deal 'order-1' did not reach the awaited state within 0 s (last status INITIATED)"
        )


def test_the_timeout_error_keeps_the_last_state_seen_when_the_deal_goes_unreported(
    flavor: Flavor,
) -> None:
    # Poll 1 sees the state; poll 2 gets no row from the statuses and a not-found from `get()`.
    rig, _, api = setup(flavor, states(row("INITIATED")), states(), not_found("a"), not_found("b"))
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(api.wait_for("order-1", Until.offered(), timeout=5.0))

        assert caught.value.last_state is not None
        assert caught.value.last_state.status is DealStatus.INITIATED


def test_the_default_clock_is_monotonic_so_a_step_of_the_system_clock_cannot_move_the_deadline(
    flavor: Flavor,
) -> None:
    api = flavor.cls("deals", "DealsApi")(object())

    assert api._clock is time.monotonic


# ---- live wake-up -------------------------------------------------------------------------------


class ScriptedLive:
    """A live session's `wait_for_deal_event` over the timeline: `script` has one step per call,
    `(seconds, deal_id)` (an event for `deal_id` after `seconds`) or `None` (a quiet or closed
    session: returns at once without time passing). A step that is further away than the wait
    ends it with `None` after the full wait."""

    def __init__(self, timeline: Timeline, flavor: Flavor, script: list[tuple[float, str] | None]):
        self._timeline = timeline
        self._script = script
        self.calls: list[tuple[str, float]] = []
        if flavor.is_async:
            self.wait_for_deal_event = self._wait_async

    def _wait(self, deal_id: str, timeout: float) -> object | None:
        self.calls.append((deal_id, timeout))
        step = self._script.pop(0) if self._script else None
        if step is None:
            return None
        seconds, event_deal = step
        if seconds > timeout:
            self._timeline.advance(timeout)
            return None
        self._timeline.advance(seconds)
        return object() if event_deal == deal_id else None

    wait_for_deal_event = _wait

    async def _wait_async(self, deal_id: str, seconds: float) -> object | None:
        return self._wait(deal_id, seconds)


def live_setup(
    flavor: Flavor, script: list[tuple[float, str] | None], *outcomes: Any
) -> tuple[ClientRig, Timeline, Any, ScriptedLive]:
    rig, timeline, api = setup(flavor, *outcomes)
    return rig, timeline, api, ScriptedLive(timeline, flavor, script)


def test_with_live_it_wakes_up_on_an_event_of_the_waited_deal_instead_of_sleeping(
    flavor: Flavor,
) -> None:
    rig, timeline, api, live = live_setup(
        flavor, [(2.0, ID)], states(row("INITIATED")), states(row("OFFERED"))
    )
    start = timeline.now
    with rig:
        state = rig.call(api.wait_for("order-1", Until.offered(), poll_interval=20.0, live=live))

        assert state.status is DealStatus.OFFERED
        assert rig.script.count == 2
        assert timeline.sleeps == [], "the wait ran in the live session"
        assert live.calls == [(ID, 20.0)], (
            "waits for the deal id the statuses reported, 20 s at most"
        )
        assert timeline.now - start == 2.0


def test_with_live_a_burst_of_events_polls_at_most_once_per_second(flavor: Flavor) -> None:
    rig, timeline, api, live = live_setup(
        flavor,
        [(0.2, ID), (0.1, ID), (0.1, ID)],
        states(row("INITIATED")),
        states(row("INITIATED")),
        states(row("INITIATED")),
        states(row("OFFERED")),
    )
    start = timeline.now
    with rig:
        rig.call(api.wait_for("order-1", Until.offered(), poll_interval=20.0, live=live))

        assert rig.script.count == 4
        # Four polls began at 0, 1, 2 and 3 s: each early wake is held until a second has passed.
        assert timeline.sleeps == pytest.approx([0.8, 0.9, 0.9])
        assert timeline.now - start == pytest.approx(3.0)


def test_with_live_an_event_after_the_gap_polls_at_once(flavor: Flavor) -> None:
    rig, timeline, api, live = live_setup(
        flavor, [(1.5, ID)], states(row("INITIATED")), states(row("OFFERED"))
    )
    start = timeline.now
    with rig:
        rig.call(api.wait_for("order-1", Until.offered(), poll_interval=20.0, live=live))

        assert timeline.sleeps == []
        assert timeline.now - start == 1.5


def test_with_live_the_hold_after_an_early_event_never_passes_the_deadline(flavor: Flavor) -> None:
    rig, timeline, api, live = live_setup(flavor, [(0.2, ID)], states(row("INITIATED")))
    start = timeline.now
    with rig:
        with pytest.raises(DealWaitTimeoutError):
            rig.call(
                api.wait_for("order-1", Until.offered(), timeout=0.5, poll_interval=20.0, live=live)
            )

        assert timeline.now - start == pytest.approx(0.5)


def test_with_live_before_any_state_is_known_it_waits_for_the_lowercased_reference(
    flavor: Flavor,
) -> None:
    rig, _, api, live = live_setup(
        flavor,
        [None],
        states(),
        *[not_found(str(i)) for i in range(4)],
        live_deal("order-1", status="OFFERED"),
    )
    with rig:
        rig.call(api.wait_for(ID.upper(), Until.offered(), live=live))

        assert live.calls == [(ID, 5.0)]


def test_with_live_events_of_other_deals_do_not_trigger_a_poll(flavor: Flavor) -> None:
    rig, _, api, live = live_setup(flavor, [(1.0, OTHER_ID), None], states(row("INITIATED")))
    with rig:
        with pytest.raises(DealWaitTimeoutError):
            rig.call(
                api.wait_for("order-1", Until.offered(), timeout=5.0, poll_interval=5.0, live=live)
            )

        assert rig.script.count == 2, "the first poll and the one at the deadline"


def test_with_live_the_next_poll_comes_after_the_full_interval_when_no_event_matches(
    flavor: Flavor,
) -> None:
    rig, timeline, api, live = live_setup(
        flavor, [(30.0, ID)], states(row("INITIATED")), states(row("OFFERED"))
    )
    start = timeline.now
    with rig:
        rig.call(api.wait_for("order-1", Until.offered(), poll_interval=10.0, live=live))

        assert timeline.now - start == 10.0
        assert rig.script.count == 2


def test_with_live_never_waits_longer_than_the_remaining_interval_or_deadline(
    flavor: Flavor,
) -> None:
    rig, _, api, live = live_setup(flavor, [None, None], states(row("INITIATED")))
    with rig:
        with pytest.raises(DealWaitTimeoutError):
            rig.call(
                api.wait_for("order-1", Until.offered(), timeout=8.0, poll_interval=5.0, live=live)
            )

        assert [seconds for _, seconds in live.calls] == [5.0, 3.0]


def test_with_live_it_times_out_at_the_deadline_like_without_live(flavor: Flavor) -> None:
    rig, _, api, live = live_setup(flavor, [None, None], states(row("INITIATED")))
    with rig:
        with pytest.raises(DealWaitTimeoutError) as caught:
            rig.call(
                api.wait_for(
                    "order-1", Until.offered(), timeout=1.0, poll_interval=3600.0, live=live
                )
            )

        assert caught.value.timeout == 1.0
        assert caught.value.last_state is not None
        assert caught.value.last_state.status is DealStatus.INITIATED
        assert rig.script.count == 2


def test_with_a_closed_live_it_still_sleeps_the_interval(flavor: Flavor) -> None:
    rig, timeline, api, live = live_setup(
        flavor, [None], states(row("INITIATED")), states(row("OFFERED"))
    )
    with rig:
        rig.call(api.wait_for("order-1", Until.offered(), poll_interval=4.0, live=live))

        assert timeline.sleeps == [4.0], "a closed session returns at once: the rest is slept"
