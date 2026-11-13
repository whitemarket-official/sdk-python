"""Decode interface and union selections by `__typename`, with a fallback for unknown types."""

from typing import Any, Final, cast

from pydantic import Discriminator

UNKNOWN_TYPENAME_TAG: Final = "__unknown__"


def typename_discriminator(*known: str) -> Discriminator:
    """A pydantic callable discriminator over tagged union members.

    A `__typename` in `known` selects the member tagged with it; anything else (a new server type,
    a missing or non-string `__typename`) selects the member tagged `__unknown__`.
    """
    known_set = frozenset(known)

    def pick(value: Any) -> str:
        if isinstance(value, dict):
            typename = cast("dict[str, object]", value).get("__typename")
        else:
            typename = getattr(value, "typename__", None)
        if isinstance(typename, str) and typename in known_set:
            return typename
        return UNKNOWN_TYPENAME_TAG

    return Discriminator(pick)
