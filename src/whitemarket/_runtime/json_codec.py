"""JSON codec of the transport: no binary float on the way in or out (CLAUDE.md rule 3)."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel

from whitemarket._runtime.unset import UnsetType


def _refuse_constant(name: str) -> object:
    raise ValueError(f"non-finite number {name} in JSON")


def _key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("JSON object keys must be strings")
    return key


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("non-finite Decimal in a request")
    return value


def decode(body: str | bytes) -> Any:
    """Parse JSON text: fractions and exponents become `Decimal`, integers stay exact ints."""
    return json.loads(body, parse_float=Decimal, parse_constant=_refuse_constant)


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


def encode(value: object) -> str:
    """Serialise plain JSON data (see `to_plain`) compactly; a `Decimal` is a number literal."""
    if value is None or isinstance(value, bool | int | str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Decimal):
        return format(_finite(value), "f")
    if isinstance(value, float):
        raise TypeError("float in a request: pass a Decimal")
    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        pairs = (f"{json.dumps(_key(k), ensure_ascii=False)}:{encode(v)}" for k, v in items)
        return "{" + ",".join(pairs) + "}"
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return "[" + ",".join(encode(v) for v in cast("Sequence[object]", value)) + "]"
    raise TypeError(f"cannot encode {type(value).__name__}")
