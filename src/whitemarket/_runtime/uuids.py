"""The textual form of a UUID, shared by the deals and the selling API."""

import re
from typing import Final

_UUID: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII | re.IGNORECASE
)


def is_uuid(value: str) -> bool:
    """The textual form of a UUID (any version, any case)."""
    return _UUID.fullmatch(value) is not None
