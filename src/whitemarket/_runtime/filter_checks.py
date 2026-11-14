"""The checks every search filter dataclass runs once built (`ProductFilter`, `DealHistoryFilter`,
`InventoryFilter`, `WalletTransactionFilter`)."""

from collections.abc import Iterable
from decimal import Decimal


def normalize_filter(
    target: object,
    *,
    tuples: Iterable[str] = (),
    decimals: Iterable[str] = (),
    dates: Iterable[str] = (),
) -> None:
    """Keep the listed sequence fields of the frozen dataclass `target` as tuples, and check the
    others.

    Raises `TypeError` for a `float` (or anything but a `Decimal`) in a decimal field and
    `ValueError` for a naive datetime in a date field.
    """
    for name in tuples:
        value = getattr(target, name)
        if value is not None:
            object.__setattr__(target, name, tuple(value))
    for name in decimals:
        value = getattr(target, name)
        if value is not None and not isinstance(value, Decimal):
            raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    for name in dates:
        value = getattr(target, name)
        if value is not None and value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
