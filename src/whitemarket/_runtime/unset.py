"""The omitted-argument sentinel shared by generated code and the transport."""

from typing import Final, final


@final
class UnsetType:
    """Marks an operation argument the caller did not pass: it is left out of the request
    variables."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = UnsetType()
