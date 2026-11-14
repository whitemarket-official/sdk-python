"""Listing options, item references and batch inputs: construction-time validation (SDK_SPEC 3.5,
7). No request is involved."""

import re
from decimal import Decimal
from typing import Any

import pytest

from whitemarket.models import Currency, DeliveryPromise, DeliveryType, Money
from whitemarket.selling import DEFAULT_BATCH_SIZE, Listing, ListingOptions, PriceChange
from whitemarket.selling._checks import check_batch_size
from whitemarket.selling._references import require_product_id

UUID = "7d1c0e52-3b8a-4f6d-9a21-5e4c8b7f0a13"
PRICE = Money.usd("5.00")
EUR = Money(amount=Decimal(5), currency=Currency("EUR"))  # a currency this SDK cannot send


def test_options_default_to_semi_delivery_and_the_servers_defaults_for_the_rest() -> None:
    options = ListingOptions()

    assert (options.delivery_type, options.delivery_promise, options.lifetime) == (
        DeliveryType.SEMI,
        None,
        None,
    )


def test_manual_delivery_a_promise_and_a_lifetime_are_kept() -> None:
    options = ListingOptions(
        delivery_type=DeliveryType.MANUAL, delivery_promise=DeliveryPromise.HOUR1, lifetime=3600
    )

    assert (options.delivery_type, options.delivery_promise, options.lifetime) == (
        DeliveryType.MANUAL,
        DeliveryPromise.HOUR1,
        3600,
    )


def test_auto_delivery_is_refused_with_a_clear_message() -> None:
    with pytest.raises(ValueError, match=r"^AUTO delivery is reserved by the server"):
        ListingOptions(delivery_type=DeliveryType.AUTO)


@pytest.mark.parametrize(
    ("lifetime", "accepted"),
    [
        pytest.param(59, False, id="one below the minimum"),
        pytest.param(60, True, id="the minimum"),
        pytest.param(31_536_000, True, id="the maximum"),
        pytest.param(31_536_001, False, id="one above the maximum"),
        pytest.param(0, False, id="zero"),
        pytest.param(-60, False, id="negative"),
    ],
)
def test_the_lifetime_bounds(lifetime: int, accepted: bool) -> None:
    if accepted:
        assert ListingOptions(lifetime=lifetime).lifetime == lifetime
    else:
        message = f"The lifetime must be 60..31536000 seconds, got {lifetime}."
        with pytest.raises(ValueError, match=re.escape(message)):
            ListingOptions(lifetime=lifetime)


REFERENCES = [
    pytest.param(UUID, True, id="a UUID"),
    pytest.param(UUID.upper(), True, id="an upper-case UUID"),
    pytest.param("1", True, id="a short asset id"),
    pytest.param("40000000000000000002", True, id="a 20-digit asset id"),
    pytest.param("400000000000000000021", False, id="a 21-digit asset id"),
    pytest.param("", False, id="empty"),
    pytest.param(" 123", False, id="a leading space"),
    pytest.param("123\n", False, id="a trailing newline on digits"),
    pytest.param(UUID + "\n", False, id="a UUID with a trailing newline"),
    pytest.param(" " + UUID, False, id="a UUID with a leading space"),
    pytest.param(UUID[:-1], False, id="a UUID one character short"),
    pytest.param("-5", False, id="a signed number"),
    pytest.param("1.5", False, id="a decimal"),
    pytest.param("0x1f", False, id="a hex id"),
    pytest.param("AK-47 | Redline", False, id="a name"),
    pytest.param("١٢٣", False, id="non-ASCII digits"),
]


@pytest.mark.parametrize(("item", "accepted"), REFERENCES)
def test_a_listing_takes_an_inventory_id_or_an_asset_id_only(item: str, accepted: bool) -> None:
    if accepted:
        assert Listing(item, PRICE).item == item
    else:
        with pytest.raises(ValueError, match="inventory id"):
            Listing(item, PRICE)


@pytest.mark.parametrize(("product", "accepted"), REFERENCES)
def test_a_price_change_takes_a_listing_id_or_an_asset_id_only(
    product: str, accepted: bool
) -> None:
    if accepted:
        assert PriceChange(product, PRICE).product == product
    else:
        with pytest.raises(ValueError, match="listing id"):
            PriceChange(product, PRICE)


def test_the_message_names_the_kind_of_reference_and_cuts_a_long_value() -> None:
    with pytest.raises(ValueError, match="inventory id") as long_value:
        Listing("x" * 100 + "\n", PRICE)
    with pytest.raises(ValueError, match="listing id") as escaped:
        PriceChange("a\nb", PRICE)

    assert str(long_value.value) == (
        'The item must be an inventory id (UUID) or a Steam asset id (digits), got "'
        + "x" * 40
        + '...".'
    )
    assert str(escaped.value) == (
        'The product must be a listing id (UUID) or a Steam asset id (digits), got "a\\x0ab".'
    )


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        pytest.param("\x1b[31mred", "\\x1b[31mred", id="ANSI escape at the start"),
        pytest.param("\nabc", "\\x0aabc", id="newline at the start"),
        pytest.param("a\x7fb", "a\\x7fb", id="DEL"),
        pytest.param("a\0b", "a\\x00b", id="NUL"),
        pytest.param("a\udc80b", "a\\xed\\xb2\\x80b", id="a lone surrogate"),
        pytest.param("x" * 40, "x" * 40, id="exactly 40 characters are not cut"),
        pytest.param("x" * 41, "x" * 40 + "...", id="41 characters are cut with an ellipsis"),
        pytest.param(
            "x" * 36 + "\nzz",
            "x" * 36 + "\\x0a" + "...",
            id="an escape that ends at 40 stays whole",
        ),
        pytest.param(
            "x" * 37 + "\nzz", "x" * 37 + "...", id="an escape that would cross 40 is dropped whole"
        ),
    ],
)
def test_the_message_shows_escaped_ascii_cut_on_an_escape_boundary(value: str, shown: str) -> None:
    with pytest.raises(ValueError, match="must be a UUID") as error:
        require_product_id(value)

    assert str(error.value) == f'The product id must be a UUID, got "{shown}".'


def test_a_long_multi_byte_value_gives_ascii_and_is_not_cut_inside_an_escape() -> None:
    with pytest.raises(ValueError, match="must be a UUID") as error:
        require_product_id("Ж" * 50)

    message = str(error.value)
    assert message.isascii()
    assert re.fullmatch(
        r'The product id must be a UUID, got "(?:\\x[0-9a-f]{2}){10}\.\.\."\.', message
    )


@pytest.mark.parametrize("constructor", [Listing, PriceChange], ids=["Listing", "PriceChange"])
def test_a_price_in_a_currency_the_sdk_cannot_send_is_refused(constructor: Any) -> None:
    with pytest.raises(ValueError, match="unknown currency EUR cannot be sent"):
        constructor(UUID, EUR)


def test_the_default_batch_size_is_100() -> None:
    assert DEFAULT_BATCH_SIZE == 100


@pytest.mark.parametrize(
    ("size", "accepted"),
    [
        pytest.param(0, False, id="zero"),
        pytest.param(-1, False, id="negative"),
        pytest.param(1, True, id="one"),
        pytest.param(100, True, id="the default"),
        pytest.param(10_000, True, id="no upper bound"),
    ],
)
def test_the_batch_size_must_be_at_least_one(size: int, accepted: bool) -> None:
    if accepted:
        assert check_batch_size(size) == size
    else:
        with pytest.raises(ValueError, match="at least 1"):
            check_batch_size(size)


@pytest.mark.parametrize("size", ["10", 2.0, True, None])
def test_the_batch_size_must_be_an_int(size: Any) -> None:
    with pytest.raises(TypeError, match="must be an int"):
        check_batch_size(size)


@pytest.mark.parametrize(
    "lifetime",
    [
        pytest.param(60.5, id="a fractional float"),
        pytest.param(3600.0, id="a whole float"),
        pytest.param(Decimal(3600), id="a Decimal"),
        pytest.param(True, id="a bool"),
        pytest.param("3600", id="a string"),
    ],
)
def test_a_lifetime_that_is_not_an_int_is_refused_at_construction(lifetime: Any) -> None:
    with pytest.raises(TypeError, match="lifetime must be an int"):
        ListingOptions(lifetime=lifetime)
