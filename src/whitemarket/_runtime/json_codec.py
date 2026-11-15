"""JSON codec of the transport: no binary float on the way in or out (CLAUDE.md rule 3)."""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel

from whitemarket._runtime.unset import UnsetType


class RequestNotSentError(ValueError, TypeError):
    """A request value cannot be encoded, so nothing was sent and no mutation can have run. Both a
    `ValueError` and a `TypeError`: it replaces either, whichever the encoder raised."""


def _refuse_constant(name: str) -> object:
    raise ValueError(f"non-finite number {name} in JSON")


def _decimal(text: str) -> Decimal:
    """A JSON fraction or exponent as `Decimal`. One the decimal module cannot hold (an exponent
    such as `1e99999999999999999999`) is a `ValueError` like any other unreadable number, not a
    `decimal.InvalidOperation` that callers catching `ValueError` would let escape. A caller's
    context with that trap off yields NaN instead, which is refused the same way."""
    try:
        value = Decimal(text)
    except ArithmeticError:
        pass
    else:
        if value.is_finite():
            return value
    raise ValueError("a number in the JSON text is out of the decimal range")


def _key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("JSON object keys must be strings")
    return key


# A request number is written out in full, so `Decimal("1E+999999999")` would be a gigabyte literal.
# No money, wear or fade value comes near this.
_MAX_EXPONENT = 1000


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("non-finite Decimal in a request")
    if abs(value.adjusted()) > _MAX_EXPONENT:
        raise ValueError(f"Decimal exponent beyond {_MAX_EXPONENT} in a request")
    return value


def decode(
    body: str | bytes | bytearray, *, parse_int: Callable[[str], object] | None = None
) -> Any:
    """Parse JSON text: fractions and exponents become `Decimal`, integers stay exact ints.

    `parse_int` replaces the integer conversion (the JWT reader clamps instead of failing on an
    integer longer than Python's digit limit).
    """
    return json.loads(
        body, parse_float=_decimal, parse_int=parse_int, parse_constant=_refuse_constant
    )


def to_plain(value: object) -> object:
    """Turn request variables into plain JSON data: dict, list, str, int, bool, None, `Decimal`.

    Pydantic models dump by alias without unset fields, enums become their value, datetimes become
    ISO 8601 text and `UNSET` values are dropped from mappings. A `float` and a non-finite
    `Decimal` are refused: money, wear and fade values never pass through binary floating point.
    """
    result: object
    if value is None or isinstance(value, bool | int | str):
        result = value
    elif isinstance(value, Decimal):
        result = _finite(value)
    elif isinstance(value, float):
        raise TypeError("float in a request: pass a Decimal")
    elif isinstance(value, Enum):
        result = to_plain(value.value)
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("a datetime in a request must be timezone-aware")
        result = value.isoformat()
    elif isinstance(value, BaseModel):
        result = to_plain(value.model_dump(by_alias=True, exclude_unset=True))
    elif isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        result = {_key(k): to_plain(v) for k, v in items if not isinstance(v, UnsetType)}
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        result = [to_plain(v) for v in cast("Sequence[object]", value)]
    else:
        raise TypeError(f"cannot encode {type(value).__name__} in a request")
    return result


def to_request_plain(value: object) -> object:
    """`to_plain` for request variables: a refusal is a `RequestNotSentError`. Raised outside the
    handler, so no `__context__` keeps a value that may be a secret."""
    failure = ""
    try:
        return to_plain(value)
    except (TypeError, ValueError) as error:
        failure = str(error)
    raise RequestNotSentError(failure)


def encode(value: object) -> str:
    """Serialise request data compactly: `to_plain` first, then a `Decimal` is a number literal."""
    return _dump(to_plain(value))


def _dump(value: object) -> str:
    """The text of plain data (what `to_plain` returns)."""
    if value is None or isinstance(value, bool | int | str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        items = cast("Mapping[str, object]", value).items()
        return (
            "{"
            + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{_dump(v)}" for k, v in items)
            + "}"
        )
    return "[" + ",".join(_dump(v) for v in cast("Sequence[object]", value)) + "]"
