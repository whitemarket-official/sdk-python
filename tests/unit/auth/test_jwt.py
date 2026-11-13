"""JWT expiry: payload read without verification, local clock, 24 h fallback (WHITEMARKET_API 3)."""

from datetime import UTC, datetime, timedelta

import pytest

from support.flavors import jwt
from whitemarket._runtime.jwt import token_expiry

NOW = datetime(2026, 11, 6, 7, 28, 0, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())
DAY = 24 * 3600


def lifetime(token: str) -> float:
    return (token_expiry(token, NOW) - NOW).total_seconds()


@pytest.mark.parametrize(
    ("token", "seconds"),
    [
        pytest.param(jwt(exp=NOW_TS + 3600), 3600, id="exp only: exp - now"),
        pytest.param(jwt(exp=NOW_TS + 3600, iat=NOW_TS), 3600, id="exp and iat"),
        pytest.param(
            jwt(exp=NOW_TS + 1000, iat=NOW_TS - 5000), 6000, id="exp - iat from the local clock"
        ),
        pytest.param(jwt(exp=NOW_TS + 10 * DAY), DAY, id="never longer than 24 h"),
        pytest.param(jwt(exp=NOW_TS + 10 * DAY, iat=NOW_TS), DAY, id="exp - iat capped at 24 h"),
        pytest.param(jwt(exp=NOW_TS - 10), DAY, id="already expired: documented lifetime"),
        pytest.param(
            jwt(exp=NOW_TS + 100, iat=NOW_TS + 200), 100, id="iat after exp: exp - now is used"
        ),
        pytest.param(jwt(exp=NOW_TS + 5, iat=-5), 5, id="negative iat ignored"),
        pytest.param(jwt(), DAY, id="no exp"),
        pytest.param(jwt(exp="soon"), DAY, id="exp is a string"),
        pytest.param(jwt(exp=1.5e9), DAY, id="exp is a float"),
        pytest.param(jwt(exp=True), DAY, id="exp is a bool"),
        pytest.param(jwt(exp=None, raw_payload='{"exp": null}'), DAY, id="exp is null"),
        pytest.param(jwt(raw_payload="[1, 2]"), DAY, id="payload is a list"),
        pytest.param(jwt(raw_payload="not json"), DAY, id="payload is not JSON"),
        pytest.param(jwt(raw_payload='{"exp": 1e999}'), DAY, id="non-finite number"),
        pytest.param(jwt(raw_payload="[" * 100_000), DAY, id="payload too deep for the parser"),
        pytest.param("a.b", DAY, id="two parts"),
        pytest.param("a.b.c.d", DAY, id="four parts"),
        pytest.param("a.!!!.c", DAY, id="payload is not base64"),
        pytest.param("a..c", DAY, id="empty payload"),
        pytest.param("", DAY, id="empty token"),
    ],
)
def test_the_lifetime_of_a_token(token: str, seconds: int) -> None:
    assert lifetime(token) == seconds


def test_the_expiry_is_counted_from_the_given_clock_not_from_iat() -> None:
    token = jwt(exp=NOW_TS + 600, iat=NOW_TS - 100)

    later = NOW + timedelta(days=3)
    assert token_expiry(token, later) - later == timedelta(seconds=700)
