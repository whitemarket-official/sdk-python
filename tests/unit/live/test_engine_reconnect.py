"""Reconnect, backoff, close codes and the 5-consecutive rule (SDK_SPEC 3.11, 1.4)."""

import pytest

from support.live_fakes import DEFAULT_INFO, Rig, Wait, make_rig
from whitemarket.errors.base import LiveConnectionError, TransportError
from whitemarket.live._connection import ServerClosedError
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.envelope import Publication
from whitemarket.live.events import UnknownEvent
from whitemarket.live.options import LiveOptions

EVENT = Publication("broadcast", {"message": '{"type":"x","content":{}}'})


async def drain(rig: Rig) -> None:
    """Poll until an event comes (the last connection of the script yields one)."""
    event = await rig.session.poll(100_000)
    assert isinstance(event, UnknownEvent)


@pytest.mark.parametrize(
    "code", [3000, 3005, 3499, 4000, 4499, 3012], ids=lambda c: f"reconnect-{c}"
)
async def test_centrifugo_reconnect_codes_reconnect(code: int) -> None:
    rig = make_rig()
    rig.connection.reads = [[ServerClosedError(code, "r")], [EVENT]]
    await drain(rig)
    assert len(rig.connection.open_calls) == 2


@pytest.mark.parametrize("code", [3501, 3999, 4500, 4999, 3503], ids=lambda c: f"terminal-{c}")
async def test_centrifugo_terminal_codes_end_the_session(code: int) -> None:
    rig = make_rig()
    rig.connection.reads = [[ServerClosedError(code, "bye")]]
    with pytest.raises(LiveConnectionError) as caught:
        await rig.session.poll(100)
    assert (caught.value.code, caught.value.reason) == (code, "bye")
    assert len(rig.connection.open_calls) == 1
    assert rig.calls[-1][1].will_reconnect is False


async def test_backoff_is_full_jitter_with_cap_and_the_attempt_counts_up() -> None:
    rig = make_rig(random_value=1.0)
    rig.connection.reads = [[ServerClosedError(3000, "")] for _ in range(9)] + [[EVENT]]
    await drain(rig)
    assert rig.clock.sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 20.0, 20.0, 20.0]


async def test_backoff_jitter_scales_the_delay() -> None:
    rig = make_rig(random_value=0.5)
    rig.connection.reads = [[ServerClosedError(3000, "")], [ServerClosedError(3000, "")], [EVENT]]
    await drain(rig)
    assert rig.clock.sleeps == [0.25, 0.5]


async def test_the_attempt_counter_resets_after_60_seconds_connected() -> None:
    rig = make_rig()
    rig.connection.reads = [
        [ServerClosedError(3000, "")],
        [ServerClosedError(3000, "")],
        [Wait(60.0), ServerClosedError(3000, "")],
        [ServerClosedError(3000, "")],
        [EVENT],
    ]
    await drain(rig)
    assert rig.clock.sleeps == [0.5, 1.0, 0.5, 1.0]


async def test_the_attempt_counter_does_not_reset_after_59_seconds() -> None:
    rig = make_rig()
    rig.connection.reads = [
        [ServerClosedError(3000, "")],
        [Wait(59.0), ServerClosedError(3000, "")],
        [EVENT],
    ]
    await drain(rig)
    assert rig.clock.sleeps == [0.5, 1.0]


@pytest.mark.parametrize("code", [1000, 1001, 1006, 2999, 5000, 1], ids=lambda c: f"other-{c}")
async def test_other_codes_reconnect_five_times_and_the_sixth_in_a_row_is_terminal(
    code: int,
) -> None:
    rig = make_rig()
    rig.connection.reads = [[ServerClosedError(code, "gone")] for _ in range(10)]
    with pytest.raises(LiveConnectionError) as caught:
        await rig.session.poll(100_000)
    assert caught.value.code == code
    assert len(rig.connection.open_calls) == 6  # 1 + 5 reconnects, the 6th close ends it


async def test_the_other_close_count_resets_only_after_a_connection_stayed_up_60_seconds() -> None:
    rig = make_rig()
    rig.connection.reads = [
        *[[ServerClosedError(1006, "")] for _ in range(5)],
        [
            Wait(60.0),
            ServerClosedError(1006, ""),
        ],  # resets the count, this close is the first again
        *[[ServerClosedError(1006, "")] for _ in range(4)],
        [EVENT],
    ]
    await drain(rig)
    assert len(rig.connection.open_calls) == 11


async def test_closes_of_the_centrifugo_ranges_neither_count_nor_reset_the_other_count() -> None:
    rig = make_rig()
    rig.connection.reads = [
        *[[ServerClosedError(1006, "")] for _ in range(5)],
        [ServerClosedError(3000, "")],  # a Centrifugo-range close in between
        [ServerClosedError(1006, "")],  # still the 6th other close: terminal
    ]
    with pytest.raises(LiveConnectionError) as caught:
        await rig.session.poll(100_000)
    assert caught.value.code == 1006


async def test_failed_connect_attempts_do_not_count_as_other_closes() -> None:
    rig = make_rig()
    rig.connection.opens = [TransportError("refused")] * 8
    rig.connection.reads = [[EVENT]]
    await drain(rig)
    assert len(rig.connection.open_calls) == 9
    assert [kind for kind, _ in rig.calls].count("error") == 8


async def test_max_reconnect_attempts_applies_to_every_reconnect() -> None:
    rig = make_rig(options=LiveOptions(max_reconnect_attempts=2))
    rig.connection.reads = [[ServerClosedError(3000, "")] for _ in range(5)]
    with pytest.raises(LiveConnectionError) as caught:
        await rig.session.poll(100_000)
    assert caught.value.code == 3000
    assert len(rig.connection.open_calls) == 3


async def test_reconnected_flag_and_lifecycle_order() -> None:
    rig = make_rig()
    rig.connection.reads = [[ServerClosedError(3000, "x")], [EVENT]]
    await drain(rig)
    kinds = [kind for kind, _ in rig.calls]
    assert kinds == ["connecting", "connected", "disconnected", "connecting", "connected"]
    assert [v for k, v in rig.calls if k == "connected"] == [False, True]
    disconnected = rig.calls[2][1]
    assert (disconnected.code, disconnected.reason, disconnected.will_reconnect) == (
        3000,
        "x",
        True,
    )


async def test_idle_deadline_is_ping_plus_10_seconds_and_a_message_resets_it() -> None:
    rig = make_rig()
    rig.connection.opens = [ConnectInfo(ping=25, pong=True, ttl=None)] * 3
    rig.connection.reads = [[Wait(30.0), EVENT]]
    event = await rig.session.poll(1000.0)  # 30 s of silence is within 35 s
    assert isinstance(event, UnknownEvent)
    assert len(rig.connection.open_calls) == 1
    # now nothing more arrives: 35 s after the last message the connection is dropped
    assert await rig.session.poll(100.0) is None
    assert len(rig.connection.open_calls) >= 2
    assert rig.connection.open_times[1] - (1000.0 + 30.0) == pytest.approx(35.0 + 0.5, abs=1e-6)


async def test_the_server_ping_interval_is_clamped_to_300_seconds() -> None:
    assert ConnectInfo.from_reply(10_000, True, None, False).idle_seconds == 310.0
    assert ConnectInfo.from_reply(None, True, None, False).idle_seconds == 35.0
    assert ConnectInfo.from_reply(0, True, None, False).idle_seconds == 35.0


async def test_a_connection_that_enforces_its_own_idle_deadline_has_none() -> None:
    rig = make_rig()
    rig.connection.opens = [ConnectInfo(ping=None, pong=True, ttl=None)]
    rig.connection.reads = [[Wait(10_000.0), EVENT]]
    await drain(rig)
    assert len(rig.connection.open_calls) == 1


async def test_a_transport_error_while_reading_reconnects_with_backoff_uncounted() -> None:
    rig = make_rig()
    rig.connection.reads = [*[[TransportError("x")] for _ in range(7)], [EVENT]]
    await drain(rig)
    assert len(rig.connection.open_calls) == 8


async def test_default_connect_info_matches_the_documented_defaults() -> None:
    assert DEFAULT_INFO.idle_seconds == 35.0
