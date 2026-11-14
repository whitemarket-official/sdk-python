"""RetryPolicy and Retry-After parsing (SDK_SPEC 1.4); port of the PHP RetryPolicyTest cases."""

from datetime import UTC, datetime

import pytest

from whitemarket import RetryPolicy
from whitemarket._runtime.operation import OperationType
from whitemarket._runtime.retry_after import parse_retry_after

NOW = datetime(2026, 11, 6, 7, 28, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("operation_type", "attempt", "status", "retry_after", "expected"),
    [
        pytest.param("query", 1, None, None, True, id="query network error"),
        pytest.param("query", 1, 429, None, True, id="query 429"),
        pytest.param("query", 1, 500, None, True, id="query 500"),
        pytest.param("query", 1, 502, None, True, id="query 502"),
        pytest.param("query", 1, 503, None, True, id="query 503"),
        pytest.param("query", 1, 504, None, True, id="query 504"),
        pytest.param("query", 1, 501, None, False, id="query 501 is not retried"),
        pytest.param("query", 1, 505, None, False, id="query 505 is not retried"),
        pytest.param("query", 1, 400, None, False, id="query 400"),
        pytest.param("query", 1, 401, None, False, id="query 401"),
        pytest.param("query", 1, 404, None, False, id="query 404"),
        pytest.param("query", 1, 302, None, False, id="query 3xx"),
        pytest.param("query", 1, 429, 5, False, id="429 with Retry-After is not retried"),
        pytest.param("query", 1, 503, 0, False, id="503 with Retry-After 0 is not retried"),
        pytest.param("query", 1, 500, 5, True, id="500 ignores Retry-After"),
        pytest.param("query", 1, 502, 5, True, id="502 ignores Retry-After"),
        pytest.param("query", 1, 504, 5, True, id="504 ignores Retry-After"),
        pytest.param("query", 2, 503, None, True, id="second attempt may retry"),
        pytest.param("query", 3, 503, None, False, id="the third attempt is the last"),
        pytest.param("query", 4, None, None, False, id="beyond the last attempt"),
        pytest.param("mutation", 1, None, None, False, id="mutation network error"),
        pytest.param("mutation", 1, 503, None, False, id="mutation 503"),
        pytest.param("mutation", 1, 429, None, False, id="mutation 429"),
        pytest.param("mutation", 1, 500, None, False, id="mutation 500"),
    ],
)
def test_retries_only_queries_on_transient_failures(
    operation_type: OperationType,
    attempt: int,
    status: int | None,
    retry_after: float | None,
    expected: bool,
) -> None:
    assert RetryPolicy().should_retry(operation_type, attempt, status, retry_after) is expected


def test_a_mutation_is_never_retried_whatever_the_configuration() -> None:
    policy = RetryPolicy(max_attempts=100)

    assert not any(
        policy.should_retry("mutation", n, s) for n in range(1, 100) for s in (None, 503)
    )


def test_none_makes_one_attempt_and_max_attempts_is_configurable() -> None:
    assert not RetryPolicy.none().should_retry("query", 1, 503)
    assert RetryPolicy(max_attempts=5).should_retry("query", 4, 503)
    assert not RetryPolicy(max_attempts=5).should_retry("query", 5, 503)


@pytest.mark.parametrize(
    ("attempt", "jitter", "expected"),
    [
        pytest.param(1, 1.0, 0.5, id="first ceiling is the base"),
        pytest.param(2, 1.0, 1.0, id="doubles"),
        pytest.param(3, 1.0, 2.0, id="doubles again"),
        pytest.param(7, 1.0, 30.0, id="capped at 30 s (32 s uncapped)"),
        pytest.param(6, 1.0, 16.0, id="just below the cap"),
        pytest.param(5000, 1.0, 30.0, id="overflowing power stays capped"),
        pytest.param(3, 0.5, 1.0, id="full jitter scales the ceiling"),
        pytest.param(3, 0.0, 0.0, id="full jitter reaches zero"),
    ],
)
def test_backs_off_exponentially_with_full_jitter_and_a_cap(
    attempt: int, jitter: float, expected: float
) -> None:
    assert RetryPolicy().delay(attempt, jitter) == pytest.approx(expected)


def test_a_zero_base_delay_never_waits() -> None:
    assert RetryPolicy(base_delay=0).delay(3, 0.9) == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": -1},
        {"base_delay": -0.1},
        {"max_delay": -1.0},
        {"factor": 0.5},
    ],
)
def test_rejects_invalid_options(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match=r"attempts|delays"):
        RetryPolicy(**kwargs)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        pytest.param("0", 0, id="zero seconds"),
        pytest.param("120", 120, id="seconds"),
        pytest.param(" 7 ", 7, id="padded seconds"),
        pytest.param("99999999999999999999", 999_999_999, id="saturated"),
        pytest.param("Fri, 06 Nov 2026 07:28:30 GMT", 30, id="IMF-fixdate"),
        pytest.param("Friday, 06-Nov-26 07:29:00 GMT", 60, id="RFC 850"),
        pytest.param("Fri Nov  6 07:30:00 2026", 120, id="asctime"),
        pytest.param("Fri, 06 Nov 2026 07:00:00 GMT", 0, id="a date in the past is zero"),
        pytest.param("Sat, 06 Nov 2026 07:28:30 GMT", None, id="wrong weekday"),
        pytest.param("Fri, 06 Nov 2026 07:28:30 +0100", None, id="not GMT"),
        pytest.param("Fri, 31 Feb 2026 07:28:30 GMT", None, id="impossible date"),
        pytest.param("-5", None, id="negative"),
        pytest.param("1.5", None, id="fraction"),
        pytest.param("soon", None, id="garbage"),
        pytest.param("", None, id="empty"),
        pytest.param(None, None, id="missing"),
    ],
)
def test_parses_seconds_and_http_dates(header: str | None, expected: int | None) -> None:
    assert parse_retry_after(header, NOW) == expected
