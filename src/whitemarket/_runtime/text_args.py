"""The checks of a string argument that is sent to the API, run before any request is built."""

import unicodedata
from typing import cast


def require_text(
    value: str, name: str, *, non_empty: bool = False, no_control: bool = False
) -> str:
    """`value` when it can be sent: a `str` of valid Unicode, not empty when `non_empty`, without a
    control character (Unicode category Cc) when `no_control`.

    Raises `TypeError` for a non-`str` and `ValueError` otherwise. The message names the argument
    and never holds the text: it may be a secret, and a lone surrogate could not be shown anyway.
    """
    if not isinstance(cast("object", value), str):
        raise TypeError(f"{name} must be a str")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        failure = f"{name} must be valid Unicode text"
    else:
        if non_empty and not value:
            failure = f"{name} must not be empty"
        elif no_control and any(unicodedata.category(c) == "Cc" for c in value):
            failure = f"{name} must not contain control characters"
        else:
            return value
    # Raised outside the handler: no __context__ keeps the text.
    raise ValueError(failure)
