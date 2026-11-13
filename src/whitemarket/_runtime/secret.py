"""`Secret`: a string that never prints its value (SDK_SPEC 8)."""

import hmac
from typing import Any, NoReturn, Self, cast, final

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

_MASK = "***"


@final
class Secret:
    """Wraps a credential (Partner Token, JWT, `airwallexSecret`, ...).

    `str()`, `repr()`, `format()` and f-strings give `***`; the value comes out only through
    `reveal()`. The object is immutable, compares in constant time (`hmac.compare_digest`) and
    hashes by value, so it can be a dict key.

    It is a pydantic field type: a string validates into it and it serialises as `***` (nothing
    re-sends a response model, so a dump must never carry the value). An empty string is allowed:
    the value is opaque, and rejecting "no credential" is the caller's configuration check.

    `copy.copy` and `copy.deepcopy` return the same object. Pickling is refused, so that a
    credential cannot end up in a cache or queue file by accident.
    """

    __slots__ = ("_value",)

    _value: str

    def __init__(self, value: str) -> None:
        if not isinstance(cast("object", value), str):
            raise TypeError("Secret wraps a str")
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        """The wrapped value. The only way out; call it at the point of use and do not store the
        result."""
        return self._value

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("Secret is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("Secret is immutable")

    def __repr__(self) -> str:
        return _MASK

    def __str__(self) -> str:
        return _MASK

    def __format__(self, format_spec: str) -> str:
        return _MASK

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    def __hash__(self) -> int:
        return hash(self._value)

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("Secret cannot be pickled")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_after_validator_function(cls, core_schema.str_schema()),
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    core_schema.no_info_after_validator_function(cls, core_schema.str_schema()),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(lambda _: _MASK),
        )
