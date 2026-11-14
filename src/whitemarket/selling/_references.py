"""Item references of the selling API (SDK_SPEC 3.5 rule 1): a UUID or a 64-bit Steam asset id.

An item or a listing is named by format: a UUID, or an asset id written in digits and kept as a
string so it never loses precision. Anything else is refused before any request.
"""

import re
from dataclasses import dataclass
from typing import Final

from whitemarket._runtime.uuids import is_uuid

_ASSET_ID: Final = re.compile(r"[0-9]{1,20}", re.ASCII)
_SHOWN_LENGTH: Final = 40
_PRINTABLE: Final = bytes(range(0x20, 0x7F))  # the bytes an error message shows as they are


@dataclass(frozen=True, slots=True)
class ItemReference:
    """A parsed reference: exactly one of `uuid` and `asset_id` is set."""

    uuid: str | None
    asset_id: str | None


def _shown(value: str) -> str:
    """The value for an error message: pure ASCII (every UTF-8 byte outside 0x20..0x7E is written
    as `\\xNN`, so a control sequence never reaches a terminal), at most 40 characters, cut between
    whole escapes, with `...` when cut."""
    shown = ""
    for byte in value.encode("utf-8", "surrogatepass"):
        piece = chr(byte) if byte in _PRINTABLE else f"\\x{byte:02x}"
        if len(shown) + len(piece) > _SHOWN_LENGTH:
            return shown + "..."
        shown += piece
    return shown


def uuid_or_asset(value: str, expected: str, name: str) -> ItemReference:
    """`value` as a UUID or an asset id; `expected` names the UUID kind in the message."""
    if is_uuid(value):
        return ItemReference(value, None)
    if _ASSET_ID.fullmatch(value) is not None:
        return ItemReference(None, value)
    raise ValueError(
        f'The {name} must be {expected} or a Steam asset id (digits), got "{_shown(value)}".'
    )


def inventory_or_asset(item: str) -> ItemReference:
    return uuid_or_asset(item, "an inventory id (UUID)", "item")


def product_or_asset(product: str) -> ItemReference:
    return uuid_or_asset(product, "a listing id (UUID)", "product")


def require_product_id(product_id: str) -> None:
    if not is_uuid(product_id):
        raise ValueError(f'The product id must be a UUID, got "{_shown(product_id)}".')
