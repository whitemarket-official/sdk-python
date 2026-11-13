"""Base of the generated enums: a value the snapshot does not know must not break decoding."""

from enum import StrEnum
from typing import Self

UNKNOWN_NAME = "UNKNOWN"


class UnknownTolerantEnum(StrEnum):
    """A string enum whose unknown values become a pseudo-member named `UNKNOWN` with the raw value.

    `MyEnum("TELEPORT")` returns a member with `.value == "TELEPORT"` and `.is_unknown`. It is not
    listed by iteration and is not identical to any declared member. Non-string values still raise
    `ValueError`. (CLAUDE.md rule 5)
    """

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        member = str.__new__(cls, value)
        member._name_ = UNKNOWN_NAME
        member._value_ = value
        return member

    @property
    def is_unknown(self) -> bool:
        return self._name_ == UNKNOWN_NAME
