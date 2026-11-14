"""`search_argument`: the one rule for the `search` variable of every list operation."""

from whitemarket._generated.input_types import (
    MarketProductSearchInput,
    PersonInventorySearchInput,
    WalletTransactionSearchInput,
)
from whitemarket._mappers.search import (
    inventory_search_input,
    product_search_input,
    search_argument,
    wallet_transaction_search_input,
)
from whitemarket._runtime.unset import UNSET
from whitemarket.inventory import InventoryFilter
from whitemarket.market.filter import ProductFilter


def test_no_filter_sends_no_search_variable_at_all() -> None:
    assert search_argument(None, MarketProductSearchInput, product_search_input) is UNSET


def test_a_raw_input_is_sent_as_the_very_same_object() -> None:
    raw = PersonInventorySearchInput(name="x")

    assert search_argument(raw, PersonInventorySearchInput, inventory_search_input) is raw


def test_an_empty_raw_input_is_still_sent_not_dropped_as_falsy() -> None:
    raw = WalletTransactionSearchInput()

    assert (
        search_argument(raw, WalletTransactionSearchInput, wallet_transaction_search_input) is raw
    )


def test_a_filter_is_encoded_with_the_given_encoder() -> None:
    wire = search_argument(ProductFilter(name="AK"), MarketProductSearchInput, product_search_input)

    assert isinstance(wire, MarketProductSearchInput)
    assert wire.name == "AK"
    flt = InventoryFilter(name_strict=True)
    encoded = search_argument(flt, PersonInventorySearchInput, inventory_search_input)
    assert isinstance(encoded, PersonInventorySearchInput)
    assert encoded.name_strict is True
