"""Argument checks of the selling API that more than one module needs."""

from typing import cast


def check_batch_size(size: int) -> int:
    """`size` when it is a usable chunk size (at least 1); no upper bound is enforced because the
    backend's maximum is unconfirmed (SDK_SPEC 3.5 rule 4)."""
    if isinstance(size, bool) or not isinstance(cast("object", size), int):
        raise TypeError("selling_batch_size must be an int")
    if size < 1:
        raise ValueError("selling_batch_size must be at least 1")
    return size


def require_whole_seconds(seconds: object, name: str) -> None:
    """A duration in whole seconds: an `int`, never a `bool`, a float or a `Decimal` (the API takes
    an integer, and a fractional value would only fail later while encoding)."""
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise TypeError(f"The {name} must be an int number of seconds")
