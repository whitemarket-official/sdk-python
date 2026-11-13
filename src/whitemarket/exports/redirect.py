"""Which redirects an export GET follows (SDK_SPEC 3.10 rule 2): pure rules, no IO.

At most `MAX_REDIRECTS`, and only to an https URL on the host and port of the base URL. The
`Location` value is server input and is never echoed into an error.
"""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from whitemarket._runtime.endpoints import allowed_origin_schemes
from whitemarket.errors.base import TransportError

MAX_REDIRECTS: Final = 3
REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})

_VISIBLE_ASCII: Final = re.compile(r"[\x21-\x7E]+", re.ASCII)
_DEFAULT_PORTS: Final = {"https": 443, "http": 80}


@dataclass(frozen=True, slots=True)
class Origin:
    """Scheme, lower-case host and port of a URL."""

    scheme: str
    host: str
    port: int

    @classmethod
    def of(cls, url: str) -> "Origin | None":
        """The origin of an absolute URL with an allowed scheme and no credentials, else `None`."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return None
        if parts.scheme not in allowed_origin_schemes() or not parts.hostname:
            return None
        if "@" in parts.netloc:
            return None
        return cls(
            parts.scheme, parts.hostname.lower(), port or _DEFAULT_PORTS.get(parts.scheme, 0)
        )

    def prefix(self) -> str:
        """`scheme://host[:port]`, the port left out when it is the scheme's default."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        default = _DEFAULT_PORTS.get(self.scheme)
        return f"{self.scheme}://{host}" + ("" if self.port == default else f":{self.port}")


def redirect_target(location: str, origin: Origin) -> str:
    """The URL a `Location` points to: an absolute path on `origin`, or a URL on the same origin.

    Anything else raises `TransportError`: another host or port, a scheme that is not allowed,
    credentials, a relative path without a leading slash, a protocol-relative URL, whitespace.
    """
    if _VISIBLE_ASCII.fullmatch(location) is None:
        raise TransportError("The export redirected to an invalid location.")
    if location.startswith("/") and not location.startswith("//"):
        return origin.prefix() + location
    target = Origin.of(location) if location.startswith(f"{origin.scheme}://") else None
    if target is None:
        raise TransportError("The export redirected to a location that is not an https URL.")
    if target != origin:
        raise TransportError("The export redirected to another host.")
    return location
