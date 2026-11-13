"""Exact decimals from server text (SDK_SPEC 4, CLAUDE.md rule 3)."""

import re
from decimal import Decimal

from whitemarket.errors import DecodeError

_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def parse_decimal(text: str, path: tuple[str | int, ...]) -> Decimal:
    """A plain decimal (`-12.5`; no exponent, no `+`, no spaces) as an exact `Decimal`.

    Anything else is a `DecodeError` at `path` with a fixed reason: the text is never put in the
    message, because it is a server amount.
    """
    if _DECIMAL.fullmatch(text) is None:
        raise DecodeError("not a decimal number", path)
    return Decimal(text)
