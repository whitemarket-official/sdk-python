"""Shape checks of credentials: a bad value is refused before it reaches a header."""

import re
from typing import Final

_HEADER_VALUE: Final = re.compile(r"[\x21-\x7E](?:[\x20-\x7E]*[\x21-\x7E])?", re.ASCII)
_BEARER_TOKEN: Final = re.compile(r"[A-Za-z0-9\-._~+/]+=*", re.ASCII)


def is_valid_header_value(value: str) -> bool:
    """Visible ASCII, inner spaces allowed, no leading or trailing whitespace, not empty."""
    return _HEADER_VALUE.fullmatch(value) is not None


def is_valid_bearer_token(value: str) -> bool:
    """RFC 6750 `b64token`: what every JWT is."""
    return _BEARER_TOKEN.fullmatch(value) is not None
