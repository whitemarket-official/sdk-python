"""`Money`: exact decimals, equality, ordering within one currency (SDK_SPEC 4)."""

import operator
from decimal import Decimal

import pytest

from whitemarket.models import Currency, Money


def test_amount_is_exact() -> None:
    assert Money.usd("0.07").amount == Decimal("0.07")
    assert Money.usd("0.1").amount + Money.usd("0.2").amount == Decimal("0.3")


@pytest.mark.parametrize("amount", [0.07, 1.0], ids=["float", "whole float"])
def test_a_float_is_refused(amount: float) -> None:
    with pytest.raises(TypeError):
        Money.usd(amount)
    with pytest.raises(TypeError):
        Money(amount=amount, currency=Currency.USD)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_amount_is_refused(amount: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        Money.usd(amount)


def test_equality_ignores_trailing_zeros_but_not_currency() -> None:
    assert Money.usd("1.0") == Money.usd("1.00")
    assert hash(Money.usd("1.0")) == hash(Money.usd("1.00"))
    assert Money.usd("1") != Money(amount=Decimal("1"), currency=Currency("EUR"))


def test_ordering_within_one_currency() -> None:
    small, large = Money.usd("0.99"), Money.usd("1.00")

    assert small < large
    assert small <= large
    assert large > small
    assert large >= small
    assert small <= Money.usd("0.990")
    assert small >= Money.usd("0.990")
    assert not small < Money.usd("0.990")
    assert not small > Money.usd("0.990")


def test_ordering_across_currencies_is_an_error() -> None:
    euros = Money(amount=Decimal("1"), currency=Currency("EUR"))

    for compare in (
        lambda: Money.usd("1") < euros,
        lambda: Money.usd("1") <= euros,
        lambda: Money.usd("1") > euros,
        lambda: Money.usd("1") >= euros,
    ):
        with pytest.raises(TypeError, match="different currencies"):
            compare()


def test_ordering_against_a_non_money_is_an_error() -> None:
    with pytest.raises(TypeError):
        operator.lt(Money.usd("1"), Decimal("2"))


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        pytest.param("7.060", "7.060 USD", id="trailing zeros kept"),
        pytest.param("0.0000001", "0.0000001 USD", id="no exponent notation"),
        pytest.param("1E+3", "1000 USD", id="exponent expanded"),
    ],
)
def test_str_is_plain_decimal_and_currency(amount: str, text: str) -> None:
    assert str(Money.usd(amount)) == text


def test_money_is_immutable() -> None:
    with pytest.raises(AttributeError):
        Money.usd("1").amount = Decimal("2")


def test_an_unknown_currency_is_the_unknown_variant() -> None:
    money = Money(amount=Decimal("1"), currency=Currency("XTS"))

    assert money.currency.is_unknown
    assert str(money) == "1 XTS"
