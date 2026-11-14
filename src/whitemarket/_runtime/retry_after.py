"""`Retry-After` (RFC 9110 10.2.3): which statuses carry it and how the value is read."""

import re
from datetime import UTC, datetime
from typing import Final

# The statuses whose error carries `retry_after` (SDK_SPEC 1.5): a header there stops the retries.
RETRY_AFTER_STATUSES: Final = frozenset({429, 503})
# A delay-seconds value too long to matter; the caller decides what to do with it.
_SATURATED_SECONDS: Final = 999_999_999
_DIGITS: Final = re.compile(r"[0-9]+", re.ASCII)


def retry_after_for(status: int, header: str | None, now: datetime) -> int | None:
    """The `Retry-After` seconds that count for `status`: only a 429 or 503 carries them.

    On every other status the header is ignored (SDK_SPEC 1.4).
    """
    if status not in RETRY_AFTER_STATUSES:
        return None
    return parse_retry_after(header, now)


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
