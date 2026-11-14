"""The omitted-argument sentinel shared by generated code and the transport."""

from typing import Final, TypeVar, final

_T = TypeVar("_T")


@final
class UnsetType:
    """Marks an operation argument the caller did not pass: it is left out of the request
    variables."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = UnsetType()


def unset_if_none(value: _T | None) -> _T | UnsetType:
    """`value`, or `UNSET` (the argument is left out of the request) when it is None. A falsy value
    such as `0` or `""` is a value and is kept."""
    return UNSET if value is None else value
