"""Refresh-once streak ordering, `close()` while the session waits, and the slow consumer."""

import asyncio

from support.live_fakes import DEFAULT_INFO, EVENT, Wait, make_live_rig
from whitemarket.errors.base import LiveConnectionError
from whitemarket.live._connection import ServerClosedError, SlowConsumerError
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.events import UnknownEvent

SHORT = ConnectInfo(ping=25, pong=True, ttl=300)


async def test_a_token_expiry_after_a_long_connection_refreshes_once_in_the_new_streak() -> None:
    rig = make_live_rig()
    rig.connection.opens = [DEFAULT_INFO, SHORT, DEFAULT_INFO]
    rig.connection.reads = [
        [Wait(3600), ServerClosedError(3005, "")],  # long connection, then the token expired
        [],  # short-lived token: the one refresh of this streak was spent on the 3005
        [Wait(1)],
    ]
    for _ in range(6):
        await rig.session.poll(1)
        if len(rig.connection.open_calls) >= 3:
            break
    assert rig.tokens.refresh_calls == 1
    assert [token for token, _ in rig.connection.open_calls[:2]] == [
        "jwt-access-1",
        "jwt-refresh-1",
    ]


async def test_a_due_refresh_is_not_skipped_after_a_long_connection_ended_the_streak() -> None:
    rig = make_live_rig()
    rig.connection.opens = [SHORT, DEFAULT_INFO, DEFAULT_INFO]
    rig.connection.reads = [[], [Wait(7200), ServerClosedError(3005, "")], [Wait(1)]]
    for _ in range(10):
        await rig.session.poll(1)
        if len(rig.connection.open_calls) >= 3:
            break
    # access (short ttl) -> refresh once -> long connection -> 3005 in a new streak -> refresh
    assert [token for token, _ in rig.connection.open_calls] == [
        "jwt-access-1",
        "jwt-refresh-1",
        "jwt-refresh-2",
    ]


async def test_close_wakes_a_poll_that_sleeps_in_a_backoff() -> None:
    rig = make_live_rig()
    release = asyncio.Event()

    async def long_sleep(seconds: float) -> None:
        del seconds
        await release.wait()  # a real 300 s sleep, never finished by the test

    rig.session._engine._sleeper = long_sleep
    rig.connection.reads = [[ServerClosedError(3000, "")]]
    polling = asyncio.create_task(rig.session.poll(None))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not polling.done()  # in the backoff sleep
    await rig.session.close()
    done, _ = await asyncio.wait({polling}, timeout=2)
    assert done
    assert polling.result() is None


async def test_a_slow_consumer_is_reported_and_the_connection_is_reopened() -> None:
    rig = make_live_rig()
    rig.connection.reads = [[SlowConsumerError("too slow")], [EVENT]]
    event = await rig.session.poll(100_000)
    assert isinstance(event, UnknownEvent)
    errors = [value for kind, value in rig.calls if kind == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], LiveConnectionError)
    assert [value for kind, value in rig.calls if kind == "connected"] == [False, True]
