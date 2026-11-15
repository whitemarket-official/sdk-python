"""When an access token expires, read from the JWT payload (WHITEMARKET_API 3)."""

import base64
import binascii
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, cast

from whitemarket._runtime import json_codec

DOCUMENTED_LIFETIME: Final = timedelta(hours=24)
_PARTS: Final = 3
# A NumericDate outside this range is clamped to its ends (SDK_SPEC 3.1), so `1E+999999999` is never
# expanded into an integer of a billion digits.
_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1
_INT64_DIGITS: Final = 19  # digits of 2**63 - 1; a longer JSON integer is beyond the range


def token_expiry(jwt: str, now: datetime) -> datetime:
    """The moment `jwt` expires, by the local clock.

    The payload is decoded WITHOUT verifying the signature (the SDK has no key). The lifetime is
    `exp - now` by the local clock, never more than `exp - iat` when `iat >= 0` and `exp > iat`, so
    the token never outlives its `exp` and a host clock behind the issuer does not lengthen it. An
    `exp` in the past gives 0 (SDK_SPEC 3.1: with the provider's 5 min margin, an `exp` within the
    margin counts as expired too). A missing or non-numeric `exp` gives the documented 24 h, and no
    lifetime is taken as longer.
    """
    # In UTC, so adding the lifetime counts elapsed time, not wall time of a zone with DST. Whole
    # seconds rounded up, so a clock with a fraction of a second never moves the expiry past `exp`:
    # the token expires at most 1 s early, never late.
    now = now.astimezone(UTC)
    return now + timedelta(seconds=_lifetime_seconds(jwt, math.ceil(now.timestamp())))


def seconds_left(jwt: str, now: datetime) -> float | None:
    """Seconds until the `exp` claim of `jwt` (negative once past), `None` without a numeric `exp`.

    Read without verifying the signature. The live connection uses it where Centrifugo's connect
    reply `ttl` (the same `exp`, counted by the server) is not exposed by the WebSocket library.
    """
    exp = _numeric_date(_claims(jwt), "exp")
    return None if exp is None else exp - now.timestamp()


def _lifetime_seconds(jwt: str, now: int) -> int:
    claims = _claims(jwt)
    maximum = int(DOCUMENTED_LIFETIME.total_seconds())
    exp = _numeric_date(claims, "exp")
    if exp is None:
        return maximum
    lifetime = max(exp - now, 0)  # an `exp` in the past is expired
    iat = _numeric_date(claims, "iat")
    if iat is not None and iat >= 0 and exp > iat:
        lifetime = min(lifetime, exp - iat)
    return min(lifetime, maximum)


def _numeric_date(claims: dict[str, object], name: str) -> int | None:
    """A NumericDate claim (RFC 7519 2) in whole seconds, rounded down; `None` when not a number.

    The JSON codec reads a fraction or an exponent as a finite `Decimal` (it refuses `NaN` and
    `Infinity`). A value outside the 64-bit range is clamped to its end, as in the sister SDKs, so
    a date far in the past still reads as expired.
    """
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        return None
    if value < _INT64_MIN:
        return _INT64_MIN
    if value > _INT64_MAX:
        return _INT64_MAX
    return math.floor(value)


def _bounded_int(text: str) -> int:
    """A JSON integer, clamped to the 64-bit range by its digit count before it is converted.

    Python refuses to convert an integer longer than `sys.get_int_max_str_digits()` digits, which
    would make the whole payload unreadable (24 h) even for an `exp` far in the past.
    """
    if len(text.lstrip("-")) > _INT64_DIGITS:
        return _INT64_MIN if text.startswith("-") else _INT64_MAX
    return int(text)


def _claims(jwt: str) -> dict[str, object]:
    parts = jwt.split(".")
    if len(parts) != _PARTS:
        return {}
    segment = parts[1]
    try:
        raw = base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)
        claims = json_codec.decode(raw, parse_int=_bounded_int)
    except (binascii.Error, ValueError, RecursionError):
        return {}
    return cast("dict[str, object]", claims) if isinstance(claims, dict) else {}
