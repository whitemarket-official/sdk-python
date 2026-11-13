"""The freshness sidecar of an export file, `<file>.meta.json` (SDK_SPEC 3.10)."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from whitemarket.errors import DecodeError

_ROOT = "meta"
_DATE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportMeta:
    """What the server says about a file: its name, the age of the data, the build time and the row
    count."""

    file: str
    data_as_of: datetime
    generated_at: datetime
    items: int


def parse_meta(body: bytes | str) -> ExportMeta:
    """Parse the body of a `.meta.json` file.

    `data_as_of` and `generated_at` must be ISO 8601 date-times with an offset; the result is
    timezone-aware. A body that is not the expected JSON is a `DecodeError` at `meta` or
    `meta.<key>`, never quoting the body.
    """
    try:
        data: Any = json.loads(body)
        valid = True
    except (
        ValueError,
        RecursionError,
    ):  # bad JSON or bytes, nesting too deep; not chained: the message could quote the body
        data = None
        valid = False
    if not valid:
        raise DecodeError("not valid JSON", (_ROOT,))
    if not isinstance(data, dict):
        raise DecodeError("not an object", (_ROOT,))
    data = cast("dict[str, Any]", data)
    return ExportMeta(
        file=_string(data, "file"),
        data_as_of=_date(data, "data_as_of"),
        generated_at=_date(data, "generated_at"),
        items=_count(data, "items"),
    )


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise DecodeError("missing or not a string", (_ROOT, key))
    return value


def _count(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DecodeError("missing or not a non-negative integer", (_ROOT, key))
    return value


def _date(data: dict[str, Any], key: str) -> datetime:
    text = _string(data, key)
    parsed: datetime | None = None
    if _DATE.fullmatch(text):
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
    if parsed is None:
        raise DecodeError("not an ISO 8601 date-time with an offset", (_ROOT, key))
    return parsed
