"""When an access token expires, read from the JWT payload (WHITEMARKET_API 3)."""

import base64
import binascii
from datetime import datetime, timedelta
from typing import Final, cast

from whitemarket._runtime import json_codec

DOCUMENTED_LIFETIME: Final = timedelta(hours=24)
_PARTS: Final = 3


def token_expiry(jwt: str, now: datetime) -> datetime:
    """The moment `jwt` expires, by the local clock.

    The payload is decoded WITHOUT verifying the signature (the SDK has no key). The lifetime is
    `exp - iat` when both are integers, `iat >= 0` and `exp > iat`, otherwise `exp - now`; it is
    counted from `now`, so a skewed host clock does not shorten the token. A missing, unreadable
    or non-positive lifetime gives the documented 24 h, and no lifetime is taken as longer.
    """
    return now + timedelta(seconds=_lifetime_seconds(jwt, int(now.timestamp())))


def seconds_left(jwt: str, now: datetime) -> float | None:
    """Seconds until the `exp` claim of `jwt` (negative once past), `None` without an integer `exp`.

    Read without verifying the signature. The live connection uses it where Centrifugo's connect
    reply `ttl` (the same `exp`, counted by the server) is not exposed by the WebSocket library.
    """
    exp = _int_claim(_claims(jwt), "exp")
    return None if exp is None else exp - now.timestamp()


def _lifetime_seconds(jwt: str, now: int) -> int:
    claims = _claims(jwt)
    maximum = int(DOCUMENTED_LIFETIME.total_seconds())
    exp = _int_claim(claims, "exp")
    if exp is None:
        return maximum
    iat = _int_claim(claims, "iat")
    lifetime = exp - iat if iat is not None and iat >= 0 and exp > iat else exp - now
    return min(lifetime, maximum) if lifetime > 0 else maximum


def _int_claim(claims: dict[str, object], name: str) -> int | None:
    value = claims.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _claims(jwt: str) -> dict[str, object]:
    parts = jwt.split(".")
    if len(parts) != _PARTS:
        return {}
    segment = parts[1]
    try:
        raw = base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)
        claims = json_codec.decode(raw)
    except (binascii.Error, ValueError, RecursionError):
        return {}
    return cast("dict[str, object]", claims) if isinstance(claims, dict) else {}
