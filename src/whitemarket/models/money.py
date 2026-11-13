"""`Money`: an exact decimal amount in one currency (SDK_SPEC 4)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self

from whitemarket.models.enums import Currency


def _is_decimal(value: object) -> bool:
    """The annotation of `Money.amount` is not enforced at run time; this is."""
    return isinstance(value, Decimal)


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    """An amount of money. Equal when the amount and the currency are equal (`1.0 USD == 1.00 USD`).

    Ordering (`<`, `<=`, `>`, `>=`) exists only between two amounts of the same currency; across
    currencies it raises `TypeError`. The amount is a finite `Decimal`, never a `float`.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not _is_decimal(self.amount):
            raise TypeError(f"Money.amount must be a Decimal, not {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError("Money.amount must be finite")

    @classmethod
    def usd(cls, amount: str | int | Decimal) -> Self:
        """USD from a decimal string, an int or a `Decimal`; a `float` is refused."""
        if isinstance(amount, float):
            raise TypeError("a float is not an exact amount; pass a str, an int or a Decimal")
        return cls(amount=Decimal(amount), currency=Currency.USD)

    def __str__(self) -> str:
        return f"{self.amount:f} {self.currency.value}"

    def __lt__(self, other: Any) -> bool:
        return self._compare(other) < 0

    def __le__(self, other: Any) -> bool:
        return self._compare(other) <= 0

    def __gt__(self, other: Any) -> bool:
        return self._compare(other) > 0

    def __ge__(self, other: Any) -> bool:
        return self._compare(other) >= 0

    def _compare(self, other: object) -> int:
        if not isinstance(other, Money):
            raise TypeError(f"cannot order Money against {type(other).__name__}")
        if self.currency.value != other.currency.value:
            raise TypeError(
                f"cannot order {self.currency.value} against {other.currency.value}: "
                "different currencies"
            )
        return (self.amount > other.amount) - (self.amount < other.amount)
