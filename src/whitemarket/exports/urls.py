"""URLs of export files and the freshness limit of a call (SDK_SPEC 3.10): pure rules, no IO."""

import math
from datetime import timedelta
from typing import Final

from whitemarket.exports.kinds import ExportFormat, ExportKind
from whitemarket.exports.window import ExportWindow

DEFAULT_APP: Final = 730
MAX_APP_ID: Final = 2**31 - 1
META_SUFFIX: Final = ".meta.json"


def export_file_url(
    base_url: str,
    kind: ExportKind,
    app: int,
    window: ExportWindow | None,
    format: ExportFormat,
) -> str:
    """`{base}/v1/{kind}/{app}{window}.{format}`; `app` is a Steam app id from 1 to 2^31-1."""
    if isinstance(app, bool):
        raise TypeError("app must be an int")
    if not 1 <= app <= MAX_APP_ID:
        raise ValueError(f"app must be a Steam app id: an integer from 1 to {MAX_APP_ID}")
    suffix = (window or ExportWindow.ALL).suffix
    return f"{base_url.rstrip('/')}/v1/{kind.value}/{app}{suffix}.{format.value}"


def max_age_seconds(max_age: timedelta | float | None) -> float | None:
    """`max_age` (a `timedelta` or a number of seconds) as seconds; `ValueError` if negative."""
    if max_age is None:
        return None
    if isinstance(max_age, bool):
        raise TypeError("max_age must be a timedelta or a number of seconds")
    seconds = max_age.total_seconds() if isinstance(max_age, timedelta) else float(max_age)
    if math.isnan(seconds) or seconds < 0:
        raise ValueError("max_age must not be negative")
    return seconds
