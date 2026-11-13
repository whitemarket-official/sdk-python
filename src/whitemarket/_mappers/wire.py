"""High-level values to generated input types (CLAUDE.md rule 12: API names only at the boundary).

High-level enums are matched to the wire enum by value. A value the wire enum does not know (or an
unknown value of the high-level enum) cannot be sent: it is a `ValueError` here, not a server
error later.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypeVar, overload

from whitemarket._generated.input_types import DateTimeRangeInput, MoneyInput, MoneyRangeInput
from whitemarket._runtime.enums import UnknownTolerantEnum
from whitemarket.models.money import Money

_W = TypeVar("_W", bound=UnknownTolerantEnum)


@overload
def wire_enum(wire: type[_W], value: UnknownTolerantEnum) -> _W: ...
@overload
def wire_enum(wire: type[_W], value: None) -> None: ...
@overload
def wire_enum(wire: type[_W], value: UnknownTolerantEnum | None) -> _W | None: ...
def wire_enum(wire: type[_W], value: UnknownTolerantEnum | None) -> _W | None:
    """The wire enum member with the value of `value`; None stays None."""
    if value is None:
        return None
    converted = wire(value.value)
    if value.is_unknown or converted.is_unknown:
        raise ValueError(
            f"{type(value).__name__} value {value.value} cannot be sent: "
            "the API schema does not accept it"
        )
    return converted


def wire_enums(wire: type[_W], values: Sequence[UnknownTolerantEnum] | None) -> list[_W] | None:
    if values is None:
        return None
    return [wire_enum(wire, value) for value in values]


def assert_sendable(money: Money) -> None:
    """A price with a currency this SDK does not know cannot be sent."""
    if money.currency.is_unknown:
        raise ValueError(f"unknown currency {money.currency.value} cannot be sent")


def wire_money(money: Money) -> MoneyInput:
    assert_sendable(money)
    return MoneyInput(currency=money.currency, value=format(money.amount, "f"))


def present(**fields: Any) -> dict[str, Any]:
    """The fields that are not None: an unset input field is left out of the request, a None one
    would be sent as `null`."""
    return {name: value for name, value in fields.items() if value is not None}


def wire_money_range(start: Money | None, end: Money | None) -> MoneyRangeInput | None:
    """None when both bounds are None."""
    if start is None and end is None:
        return None
    return MoneyRangeInput(
        **present(
            from_=None if start is None else wire_money(start),
            to=None if end is None else wire_money(end),
        )
    )


def wire_date_range(start: datetime | None, end: datetime | None) -> DateTimeRangeInput | None:
    """None when both bounds are None."""
    if start is None and end is None:
        return None
    return DateTimeRangeInput(**present(from_=start, to=end))
