"""Endpoint settings and their validation (SDK_SPEC 0, 2, 8): TLS only, no credentials in a URL."""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import httpx

DEFAULT_BASE_URL: Final = "https://api.white.market"
DEFAULT_GRAPHQL_PATH: Final = "/graphql/partner"
DEFAULT_EXPORT_BASE_URL: Final = "https://export.white.market"
_SSE_PATH: Final = "/sse_endpoint"
_WS_PATH: Final = "/ws_endpoint"

# Module-level so a test can allow a plain-HTTP loopback server; there is no switch in the API.
_ORIGIN_SCHEMES: tuple[str, ...] = ("https",)


def allowed_origin_schemes() -> tuple[str, ...]:
    """The URL schemes an origin may have (read at call time: tests widen it for loopback)."""
    return _ORIGIN_SCHEMES


_ORIGIN: Final = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://[^/?#\s@]+", re.ASCII)
_PATH: Final = re.compile(r"/[^?#\s]*", re.ASCII)
_USER_AGENT_SUFFIX: Final = re.compile(r"[\x20-\x7E]+", re.ASCII)
_NOT_PRINTABLE_ASCII: Final = re.compile(r"[^\x20-\x7E]")
# Per option. The SDK appends to them (base + path, the SSE connect query with the live token,
# export file paths); httpx refuses a URL over 65536 characters only when it builds the request.
MAX_ENDPOINT_LENGTH: Final = 2048


def _refuse_unusable_text(name: str, value: str) -> None:
    """An endpoint is printable ASCII of at most `MAX_ENDPOINT_LENGTH` characters (SDK_SPEC 2):
    `urlsplit` accepts or silently drops control characters, httpx refuses many non-ASCII hosts,
    lone surrogates and over-long URLs only when it builds a request (for SSE, one that holds the
    live token in its URL), and a live session would retry such a URL for ever. An
    internationalised host is given in its `xn--` form."""
    if len(value) > MAX_ENDPOINT_LENGTH:
        raise ValueError(f"{name} must be at most {MAX_ENDPOINT_LENGTH} characters")
    if _NOT_PRINTABLE_ASCII.search(value) is not None:
        raise ValueError(
            f"{name} must be printable ASCII (an internationalised host in its xn-- form)"
        )


def _refuse_unusable_url(name: str, url: str) -> None:
    """httpx checks the port, an IPv4 address and an `xn--` label only when it builds a request,
    so one is built here, at construction, instead of failing on the first call.

    The port must also read alike in every layer: httpx builds a port over 65535 or a signed one
    and fails only at connect, while `urlsplit` and websockets (the WS URL derived from a base URL
    keeps its port) refuse them; port 0 is read as 443 by websockets and as 0 by httpx. An empty
    or zero-padded port reads as the default in all three and stays accepted."""
    try:
        httpx.Request("GET", url)
        port = urlsplit(url).port  # ValueError: out of 0..65535, a sign, not digits
    except Exception:  # httpx.InvalidURL, idna.IDNAError (a UnicodeError), or a future class
        raise ValueError(f"{name} is not a valid URL") from None
    if port == 0:
        raise ValueError(f"{name} is not a valid URL")


def require_origin(name: str, value: str) -> str:
    """`value` as an `https://host[:port]` origin without a path, query or fragment.

    A trailing slash is dropped. User information (`user:password@host`) is refused: a credential
    in a URL ends up in logs and traces.
    """
    _refuse_unusable_text(name, value)
    if "@" in value:
        raise ValueError(f"{name} must not contain credentials")
    origin = value.rstrip("/")
    match = _ORIGIN.fullmatch(origin)
    if match is None or match["scheme"].lower() not in _ORIGIN_SCHEMES:
        raise ValueError(f"{name} must be an https:// origin without a path, query or fragment")
    _refuse_unusable_url(name, origin)
    return origin


def require_path(name: str, value: str) -> str:
    _refuse_unusable_text(name, value)
    if _PATH.fullmatch(value) is None:
        raise ValueError(f'{name} must start with "/" and hold no query or fragment')
    return value


def require_user_agent_suffix(value: str | None) -> str | None:
    if value is not None and _USER_AGENT_SUFFIX.fullmatch(value) is None:
        raise ValueError("user_agent_suffix must be non-empty printable ASCII")
    return value


def _require_url(name: str, value: str, schemes: tuple[str, ...]) -> str:
    """A TLS-only URL (`https` or `wss`) with a host, no user information, no fragment."""
    _refuse_unusable_text(name, value)
    if "@" in value:
        raise ValueError(f"{name} must not contain credentials")
    try:
        parts = urlsplit(value)  # a bad port is refused by _refuse_unusable_url below
    except ValueError:
        raise ValueError(f"{name} is not a valid URL") from None
    # `"#" in value`, not `parts.fragment`: a bare trailing "#" is an empty, falsy fragment, and the
    # SSE connect query appended after it would become part of the fragment.
    if parts.scheme.lower() not in schemes or not parts.hostname or "#" in value:
        raise ValueError(f"{name} must be a {' or '.join(schemes)}:// URL without a fragment")
    _refuse_unusable_url(name, value)
    return value


@dataclass(frozen=True, slots=True)
class Endpoints:
    """The resolved, validated addresses of one client."""

    base_url: str
    graphql_path: str
    export_base_url: str
    sse_url: str
    ws_url: str

    @property
    def graphql_url(self) -> str:
        return self.base_url + self.graphql_path

    @classmethod
    def resolve(
        cls,
        *,
        base_url: str | None = None,
        graphql_path: str | None = None,
        export_base_url: str | None = None,
        sse_url: str | None = None,
        ws_url: str | None = None,
    ) -> "Endpoints":
        base = require_origin("base_url", base_url if base_url is not None else DEFAULT_BASE_URL)
        host = base.partition("://")[2]
        return cls(
            base_url=base,
            graphql_path=require_path(
                "graphql_path", graphql_path if graphql_path is not None else DEFAULT_GRAPHQL_PATH
            ),
            export_base_url=require_origin(
                "export_base_url",
                export_base_url if export_base_url is not None else DEFAULT_EXPORT_BASE_URL,
            ),
            # Derived from the (validated) base URL; a given one must be TLS-only.
            sse_url=_require_url("sse_url", sse_url, ("https",))
            if sse_url is not None
            else base + _SSE_PATH,
            ws_url=_require_url("ws_url", ws_url, ("wss",))
            if ws_url is not None
            else f"wss://{host}{_WS_PATH}",
        )
