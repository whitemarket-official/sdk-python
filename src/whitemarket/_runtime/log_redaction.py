"""What the debug log may print about a request (SDK_SPEC 1.3).

`Authorization`, `X-partner-token` and every query value (`cf_connect` carries the JWT of the live
connection) are redacted. Headers are redacted by allow-list: only the few known harmless names
keep their value, so a credential header the SDK does not know of is still hidden.
"""

from collections.abc import Mapping
from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

from whitemarket._runtime.secret import MASK

_SAFE_HEADERS: Final = frozenset(
    {
        "accept",
        "accept-encoding",
        "connection",
        "content-encoding",
        "content-length",
        "content-type",
        "retry-after",
        "user-agent",
    }
)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Headers with the value of every name outside the allow-list replaced by `***`."""
    return {
        name: value if name.lower() in _SAFE_HEADERS else MASK for name, value in headers.items()
    }


def redact_url(url: str) -> str:
    """The URL without user information and with every query value replaced by `***`."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return MASK
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    query = "&".join(
        f"{pair.partition('=')[0]}={MASK}" if "=" in pair else pair
        for pair in parts.query.split("&")
        if pair
    )
    return urlunsplit(SplitResult(parts.scheme, netloc, parts.path, query, ""))
