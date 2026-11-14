"""Token handling: fresh token per connect, 109/3500/401 refresh rules, ttl, Retry-After."""

import pytest

from support.live_fakes import EVENT, Wait, drain, make_live_rig
from whitemarket.errors.base import LiveConnectionError, TransportError
from whitemarket.errors.http import AuthenticationError, HttpError, RateLimitError, ServerError
from whitemarket.live._connection import (
    ConnectRejectedError,
    ServerClosedError,
    StatusFailureError,
)
from whitemarket.live._envelope import Reply, ReplyError
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.events import UnknownEvent


async def test_a_fresh_token_is_asked_for_before_every_connect() -> None:
    rig = make_live_rig()
    rig.connection.reads = [[ServerClosedError(3000, "")], [ServerClosedError(3000, "")], [EVENT]]
    await drain(rig)
    assert [t for t, _ in rig.connection.open_calls] == [
        "jwt-access-1",
        "jwt-access-2",
        "jwt-access-3",
    ]
    assert rig.tokens.refresh_calls == 0


@pytest.mark.parametrize(
    "rejection",
    [
        ServerClosedError(3500, "invalid token"),
        Reply(0, ReplyError(109, "token expired", False)),
    ],
    ids=["close-3500", "reply-109"],
)
async def test_token_rejection_refreshes_once_and_reconnects_at_once(rejection: object) -> None:
    rig = make_live_rig()
    rig.connection.reads = [[rejection], [EVENT]]
    await drain(rig)
    assert rig.tokens.refresh_calls == 1
    assert rig.clock.sleeps == []  # at once, no backoff
    assert [t for t, _ in rig.connection.open_calls] == ["jwt-access-1", "jwt-refresh-1"]


async def test_a_second_token_rejection_in_a_row_is_an_authentication_error() -> None:
    rig = make_live_rig()
    rig.connection.reads = [[ServerClosedError(3500, "")], [ServerClosedError(3500, "")]]
    with pytest.raises(AuthenticationError):
        await rig.session.poll(100_000)
    assert rig.tokens.refresh_calls == 1
    assert len(rig.connection.open_calls) == 2


async def test_connect_rejected_109_follows_the_same_rule() -> None:
    rig = make_live_rig()
    rig.connection.opens = [ConnectRejectedError(109, True), ConnectRejectedError(109, True)]
    with pytest.raises(AuthenticationError):
        await rig.session.poll(100_000)
    assert rig.tokens.refresh_calls == 1


async def test_sse_401_refreshes_once_and_a_second_is_terminal() -> None:
    rig = make_live_rig()
    rig.connection.opens = [StatusFailureError(401)]
    rig.connection.reads = [[EVENT]]
    await drain(rig)
    assert rig.tokens.refresh_calls == 1
    rig = make_live_rig()
    rig.connection.opens = [StatusFailureError(401), StatusFailureError(401)]
    with pytest.raises(AuthenticationError):
        await rig.session.poll(100_000)


async def test_a_connection_that_stayed_up_60_seconds_resets_the_auth_retry() -> None:
    rig = make_live_rig()
    rig.connection.reads = [
        [ServerClosedError(3500, "")],
        [Wait(60.0), ServerClosedError(3500, "")],
        [EVENT],
    ]
    await drain(rig)
    assert rig.tokens.refresh_calls == 2


async def test_a_provider_authentication_error_is_terminal_without_a_retry() -> None:
    rig = make_live_rig()
    rig.tokens.access_error = AuthenticationError()
    with pytest.raises(AuthenticationError):
        await rig.session.poll(100)
    assert rig.connection.open_calls == []


async def test_a_provider_failure_backs_off_and_goes_to_on_error() -> None:
    rig = make_live_rig()
    rig.tokens.access_error = TransportError("down")
    await rig.session.poll(2.0)
    assert rig.clock.sleeps[:2] == [0.5, 1.0]
    assert [k for k, _ in rig.calls].count("error") >= 2


async def test_a_short_lived_token_is_refreshed_once_per_streak_then_kept() -> None:
    rig = make_live_rig()
    rig.connection.opens = [ConnectInfo(ping=25, pong=True, ttl=600.0)] * 3
    rig.connection.reads = [[], [EVENT]]  # the first connection is dropped before it is announced
    await drain(rig)
    # the first connect reply says 600 s left: refresh + reconnect at once; the second says it
    # again but the streak already used its refresh, so the connection is kept
    assert rig.tokens.refresh_calls == 1
    assert len(rig.connection.open_calls) == 2


async def test_a_token_with_601_seconds_left_is_not_refreshed_at_connect() -> None:
    rig = make_live_rig()
    rig.connection.opens = [ConnectInfo(ping=25, pong=True, ttl=601.0)]
    rig.connection.reads = [[EVENT]]
    await drain(rig)
    assert rig.tokens.refresh_calls == 0
    assert len(rig.connection.open_calls) == 1


async def test_the_scheduled_refresh_reconnects_when_ten_minutes_are_left() -> None:
    rig = make_live_rig()
    rig.connection.opens = [ConnectInfo(ping=None, pong=True, ttl=1000.0)] * 2
    rig.connection.reads = [[Wait(399.0), EVENT], [EVENT]]
    assert isinstance(await rig.session.poll(100_000), UnknownEvent)
    assert rig.tokens.refresh_calls == 0
    await rig.session.poll(100.0)  # 1000 - 600 = 400 s after connect the refresh is due
    assert rig.tokens.refresh_calls == 1
    assert len(rig.connection.open_calls) == 2


async def test_close_3005_and_the_ttl_rule_share_one_refresh_per_streak() -> None:
    rig = make_live_rig()
    rig.connection.reads = [
        [ServerClosedError(3005, "expired")],
        [ServerClosedError(3005, "expired")],
        [EVENT],
    ]
    await drain(rig)
    # first 3005: refresh once; second 3005 in the same streak: reconnects with backoff, no refresh
    assert rig.tokens.refresh_calls == 1
    assert len(rig.connection.open_calls) == 3


async def test_3005_then_a_token_rejection_makes_at_most_two_refreshes() -> None:
    rig = make_live_rig()
    rig.connection.reads = [[ServerClosedError(3005, "")], [ServerClosedError(3500, "")], [EVENT]]
    await drain(rig)
    assert rig.tokens.refresh_calls == 2


@pytest.mark.parametrize(
    ("retry_after", "expected_wait"),
    [(100.0, 100.0), (0.1, 0.5), (1000.0, 300.0)],
    ids=["lengthens", "never-shortens", "capped-at-300"],
)
async def test_retry_after_only_lengthens_the_backoff(
    retry_after: float, expected_wait: float
) -> None:
    rig = make_live_rig()
    rig.connection.opens = [StatusFailureError(503, retry_after)]
    rig.connection.reads = [[EVENT]]
    await drain(rig)
    assert rig.clock.sleeps == [expected_wait]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 599], ids=str)
async def test_retryable_statuses_reconnect(status: int) -> None:
    rig = make_live_rig()
    rig.connection.opens = [StatusFailureError(status)]
    rig.connection.reads = [[EVENT]]
    await drain(rig)
    errors = [e for k, e in rig.calls if k == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], RateLimitError | ServerError)


@pytest.mark.parametrize("status", [302, 400, 403, 404], ids=str)
async def test_other_statuses_end_the_session_and_a_redirect_is_not_followed(status: int) -> None:
    rig = make_live_rig()
    rig.connection.opens = [StatusFailureError(status)]
    with pytest.raises(HttpError) as caught:
        await rig.session.poll(100)
    assert caught.value.status == status
    assert len(rig.connection.open_calls) == 1


async def test_a_permanent_connect_rejection_ends_the_session() -> None:
    rig = make_live_rig()
    rig.connection.opens = [ConnectRejectedError(101, False)]
    with pytest.raises(LiveConnectionError) as caught:
        await rig.session.poll(100)
    assert caught.value.code == 101
