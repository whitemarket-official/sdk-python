"""JWT expiry: payload read without verification, local clock, 24 h fallback (WHITEMARKET_API 3)."""

from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from support.flavors import jwt
from whitemarket._runtime.jwt import seconds_left, token_expiry

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
            jwt(exp=NOW_TS + 1000, iat=NOW_TS - 5000), 1000, id="host clock ahead: exp - now"
        ),
        pytest.param(
            jwt(exp=NOW_TS + 3600, iat=NOW_TS + 1800),
            1800,
            id="host clock behind the issuer: exp - iat caps it",
        ),
        pytest.param(
            jwt(raw_payload=f'{{"exp": {NOW_TS + 3600}, "iat": {NOW_TS + 1800}.5}}'),
            1800,
            id="fractional iat rounds down",
        ),
        pytest.param(jwt(exp=NOW_TS + 10 * DAY), DAY, id="never longer than 24 h"),
        pytest.param(jwt(exp=NOW_TS + 10 * DAY, iat=NOW_TS), DAY, id="exp - iat capped at 24 h"),
        pytest.param(jwt(exp=NOW_TS - 10), 0, id="exp in the past: expired"),
        pytest.param(jwt(exp=NOW_TS), 0, id="exp is now: expired"),
        pytest.param(jwt(exp=NOW_TS + 1), 1, id="exp one second ahead"),
        pytest.param(jwt(exp=NOW_TS - 10, iat=NOW_TS - 3600), 0, id="past exp with iat: expired"),
        pytest.param(
            jwt(exp=NOW_TS + 100, iat=NOW_TS + 200), 100, id="iat after exp: exp - now is used"
        ),
        pytest.param(jwt(exp=NOW_TS + 5, iat=-5), 5, id="negative iat ignored"),
        pytest.param(jwt(exp=NOW_TS + 3600, iat="early"), 3600, id="iat is a string: ignored"),
        pytest.param(jwt(), DAY, id="no exp"),
        pytest.param(jwt(exp="soon"), DAY, id="exp is a string"),
        pytest.param(jwt(exp=True), DAY, id="exp is a bool"),
        pytest.param(jwt(exp=None, raw_payload='{"exp": null}'), DAY, id="exp is null"),
        pytest.param(
            jwt(raw_payload=f'{{"exp": {NOW_TS + 100}.9}}'), 100, id="fractional exp rounds down"
        ),
        pytest.param(
            jwt(raw_payload=f'{{"exp": {NOW_TS}.5}}'), 0, id="fractional exp just past now"
        ),
        pytest.param(jwt(raw_payload='{"exp": 1.5e9}'), 0, id="exponent notation in the past"),
        pytest.param(jwt(raw_payload='{"exp": 1e999}'), DAY, id="exp far beyond int64: 24 h"),
        pytest.param(jwt(raw_payload='{"exp": -1e999}'), 0, id="exp far below int64: expired"),
        pytest.param(
            jwt(raw_payload='{"exp": 1E+999999999}'), DAY, id="huge exponent: clamped, not expanded"
        ),
        pytest.param(
            jwt(raw_payload='{"exp": -1E+999999999}'), 0, id="huge negative exponent: clamped"
        ),
        pytest.param(
            jwt(raw_payload='{"exp": ' + "9" * 4301 + "}"),
            DAY,
            id="integer longer than the parser's digit limit: clamped, 24 h",
        ),
        pytest.param(
            jwt(raw_payload='{"exp": -' + "9" * 4301 + "}"),
            0,
            id="negative integer longer than the parser's digit limit: clamped, expired",
        ),
        pytest.param(
            jwt(raw_payload=f'{{"exp": {NOW_TS - 10}, "pad": ' + "9" * 4301 + "}"),
            0,
            id="a long integer in another claim does not hide a past exp",
        ),
        pytest.param(
            jwt(raw_payload='{"exp": 1e99999999999999999999999}'),
            DAY,
            id="exponent beyond the decimal module: unreadable",
        ),
        pytest.param(jwt(exp=2**70), DAY, id="integer beyond int64: 24 h"),
        pytest.param(jwt(exp=-(2**70)), 0, id="negative integer beyond int64: expired"),
        pytest.param(jwt(raw_payload='{"exp": NaN}'), DAY, id="NaN literal: unreadable"),
        pytest.param(jwt(raw_payload='{"exp": Infinity}'), DAY, id="Infinity literal: unreadable"),
        pytest.param(jwt(raw_payload="[1, 2]"), DAY, id="payload is a list"),
        pytest.param(jwt(raw_payload="not json"), DAY, id="payload is not JSON"),
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


def test_the_expiry_never_passes_exp_by_the_given_clock() -> None:
    token = jwt(exp=NOW_TS + 600, iat=NOW_TS - 100)

    assert token_expiry(token, NOW + timedelta(seconds=100)) == NOW + timedelta(seconds=600)
    later = NOW + timedelta(days=3)
    assert token_expiry(token, later) == later


class _ShiftingZone(tzinfo):
    """A synthetic zone whose offset drops by one hour at 2026-11-01 01:00 local time, like a DST
    end (no tz database needed on the test host)."""

    _SHIFT = (2026, 11, 1, 1, 0)  # local year, month, day, hour, minute

    def utcoffset(self, dt: datetime | None) -> timedelta:
        before = dt is not None and tuple(dt.timetuple())[:5] < self._SHIFT
        return timedelta(hours=-4 if before else -5)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "SHIFT"


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(datetime(2026, 11, 1, 0, 30, tzinfo=_ShiftingZone()), id="offset drops"),
        pytest.param(datetime(2026, 11, 1, 2, 30, tzinfo=_ShiftingZone()), id="after the drop"),
    ],
)
def test_a_clock_in_a_zone_with_daylight_saving_counts_elapsed_time(now: datetime) -> None:
    exp = int(now.timestamp()) + 7200

    expiry = token_expiry(jwt(exp=exp), now)

    assert expiry.timestamp() == exp


@pytest.mark.parametrize("fraction", [0.1, 0.5, 0.9, 0.999999])
def test_a_clock_with_a_fraction_of_a_second_never_moves_the_expiry_past_exp(
    fraction: float,
) -> None:
    exp = NOW_TS + 1000
    now = NOW + timedelta(seconds=fraction)

    expiry = token_expiry(jwt(exp=exp), now)

    assert expiry <= datetime.fromtimestamp(exp, UTC)
    assert expiry > datetime.fromtimestamp(exp - 1, UTC), "at most 1 s early"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        pytest.param(jwt(exp=NOW_TS + 601), 601, id="integer exp"),
        pytest.param(jwt(raw_payload=f'{{"exp": {NOW_TS + 601}.7}}'), 601, id="fractional exp"),
        pytest.param(jwt(exp=NOW_TS - 5), -5, id="past exp: negative"),
        pytest.param(jwt(exp="soon"), None, id="exp is a string"),
        pytest.param(jwt(), None, id="no exp"),
    ],
)
def test_seconds_left_reads_exp_like_the_lifetime(token: str, expected: float | None) -> None:
    assert seconds_left(token, NOW) == expected
