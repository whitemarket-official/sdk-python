"""`Page`, `PageRequest` and `parse_decimal`."""

import dataclasses
from decimal import Decimal

import pytest

from whitemarket._runtime.decimals import parse_decimal
from whitemarket.errors import DecodeError
from whitemarket.models import Money, Page, PageRequest


def test_a_page_iterates_its_items_and_has_a_length() -> None:
    page = Page(items=("a", "b"), end_cursor="c", has_next_page=True, total_count=7)

    assert list(page) == ["a", "b"]
    assert len(page) == 2
    assert (page.end_cursor, page.has_next_page, page.total_count) == ("c", True, 7)


def test_a_page_and_a_page_request_are_frozen() -> None:
    page = Page(items=(), end_cursor=None, has_next_page=False, total_count=None)

    with pytest.raises(dataclasses.FrozenInstanceError):
        page.has_next_page = True
    with pytest.raises(dataclasses.FrozenInstanceError):
        PageRequest().first = 1


def test_a_page_request_defaults_to_the_servers_defaults() -> None:
    assert (PageRequest().first, PageRequest().after) == (None, None)


@pytest.mark.parametrize("text", ["0", "-0", "12.50", "0.1000000000000000000001", "-3.5", "007"])
def test_parse_decimal_keeps_the_exact_value(text: str) -> None:
    assert parse_decimal(text, ()) == Decimal(text)
    assert str(parse_decimal(text, ())) == str(Decimal(text))


@pytest.mark.parametrize(
    "text", ["", " ", "1.", ".5", "1e5", "+1", "--1", "1.2.3", "NaN", "inf", "1 ", "1\n", "1,5"]
)
def test_parse_decimal_refuses_anything_but_a_plain_decimal(text: str) -> None:
    with pytest.raises(DecodeError) as caught:
        parse_decimal(text, ("a", 2, "b"))

    assert caught.value.path == ("a", 2, "b")
    assert caught.value.reason == "not a decimal number"


def test_money_from_a_page_item_is_not_a_float() -> None:
    assert isinstance(Money.usd("0.07").amount, Decimal)
