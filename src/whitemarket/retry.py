"""Retry policy of the transport: pure rules, no IO (SDK_SPEC 1.4)."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from whitemarket._runtime.operation import OperationType

_RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
# The statuses whose error carries `retry_after` (SDK_SPEC 1.5): a header there stops the retries.
RETRY_AFTER_STATUSES: Final = frozenset({429, 503})
# A delay-seconds value too long to matter; the caller decides what to do with it.
_SATURATED_SECONDS: Final = 999_999_999
_DIGITS: Final = re.compile(r"[0-9]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """When and how long to wait before repeating a GraphQL query. Durations are in seconds.

    A mutation is never retried, whatever the configuration (CLAUDE.md rule 2); this class has no
    switch for it. A query is retried on a network error before a response and on 429, 500, 502,
    503 and 504, at most `max_attempts` attempts in total. The delay is exponential with full
    jitter: `random() * min(max_delay, base_delay * factor ** (attempt - 1))`.

    A 429 or 503 that carries `Retry-After` is not retried: the caller gets the error with
    `retry_after` at once and decides when to try again, so the SDK never blocks for a time the
    server chose (owner decision 2026-10-31). On every other status the header is ignored.
    An unparsable value counts as no header (the query is retried), as in the PHP SDK.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    factor: float = 2.0
    max_delay: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0 or self.factor < 1:
            raise ValueError("delays must not be negative and factor must be at least 1")

    @classmethod
    def none(cls) -> "RetryPolicy":
        """One attempt, no retry."""
        return cls(max_attempts=1)

    def should_retry(
        self,
        operation_type: OperationType,
        attempt: int,
        status: int | None,
        retry_after: float | None = None,
    ) -> bool:
        """Whether attempt number `attempt` (1-based) may be repeated.

        `status` is `None` when no response came (a network error before the answer).
        """
        if operation_type != "query" or attempt >= self.max_attempts:
            return False
        if status is None:
            return True
        if retry_after is not None and status in RETRY_AFTER_STATUSES:
            return False
        return status in _RETRYABLE_STATUSES

    def delay(self, attempt: int, random: float) -> float:
        """Seconds to wait after attempt number `attempt` (1-based) failed.

        `random` is a uniform sample of [0, 1): the full-jitter fraction of the ceiling.
        """
        if self.base_delay == 0:
            return 0.0
        try:
            ceiling = min(self.max_delay, self.base_delay * self.factor ** max(0, attempt - 1))
        except OverflowError:
            ceiling = self.max_delay
        return random * ceiling


def parse_retry_after(value: str | None, now: datetime) -> int | None:
    """`Retry-After` (RFC 9110 10.2.3) as whole seconds: delay-seconds or an HTTP-date.

    `0` for a date in the past, `None` for a missing or unparsable value. The three date forms of
    RFC 9110 5.6.7 are read strictly: the weekday must match the date, so a mangled value is
    refused instead of guessed.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if _DIGITS.fullmatch(text):
        return min(int(text), _SATURATED_SECONDS)
    date = _http_date(text, now)
    if date is None:
        return None
    return max(0, int((date - now).total_seconds()))


_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_WEEKDAYS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_FULL_WEEKDAYS: Final = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)  # fmt: skip
_TIME: Final = r"(?P<h>[0-9]{2}):(?P<mi>[0-9]{2}):(?P<s>[0-9]{2})"
_MONTH: Final = "(?P<mon>" + "|".join(_MONTHS) + ")"
# IMF-fixdate, obsolete RFC 850 (two-digit year) and asctime (space-padded day).
_IMF: Final = re.compile(
    rf"(?P<wd>{'|'.join(_WEEKDAYS)}), (?P<d>[0-9]{{2}}) {_MONTH} (?P<y>[0-9]{{4}}) {_TIME} GMT",
    re.ASCII,
)
_RFC850: Final = re.compile(
    rf"(?P<wd>{'|'.join(_FULL_WEEKDAYS)}), (?P<d>[0-9]{{2}})-{_MONTH}-(?P<y>[0-9]{{2}}) "
    rf"{_TIME} GMT",
    re.ASCII,
)
_ASCTIME: Final = re.compile(
    rf"(?P<wd>{'|'.join(_WEEKDAYS)}) {_MONTH} (?P<d>[ 0-9][0-9]) {_TIME} (?P<y>[0-9]{{4}})",
    re.ASCII,
)
_FUTURE_YEARS: Final = (
    50  # RFC 9110 5.6.7: a two-digit year more than 50 years ahead is the past century
)


def _http_date(text: str, now: datetime) -> datetime | None:
    for pattern in (_IMF, _RFC850, _ASCTIME):
        match = pattern.fullmatch(text)
        if match is None:
            continue
        year = int(match["y"])
        if pattern is _RFC850:
            year += 2000
            if year > now.year + _FUTURE_YEARS:
                year -= 100
        weekday = match["wd"]
        try:
            date = datetime(
                year,
                _MONTHS.index(match["mon"]) + 1,
                int(match["d"]),
                int(match["h"]),
                int(match["mi"]),
                int(match["s"]),
                tzinfo=UTC,
            )
        except ValueError:
            return None
        names = _FULL_WEEKDAYS if pattern is _RFC850 else _WEEKDAYS
        return date if names[date.weekday()] == weekday else None
    return None
