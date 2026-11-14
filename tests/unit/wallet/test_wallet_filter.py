"""`WalletTransactionFilter` and `WalletTransactionSort` over `WalletTransactionSearchInput`."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from whitemarket._mappers.search import (
    wallet_transaction_search_input,
    wallet_transaction_sort_input,
)
from whitemarket._runtime.json_codec import to_plain
from whitemarket.models import Currency, SortDirection, TransactionReason
from whitemarket.models.account_enums import (
    TransactionFeeType,
    TransactionSortField,
    TransactionStatus,
)
from whitemarket.wallet import WalletTransactionFilter, WalletTransactionSort

NAIVE = datetime(2026, 10, 1, tzinfo=UTC).replace(tzinfo=None)


def wire(flt: WalletTransactionFilter) -> Any:
    return to_plain(wallet_transaction_search_input(flt))


def test_an_empty_filter_sends_nothing() -> None:
    assert wire(WalletTransactionFilter()) == {}


def test_every_condition_is_encoded_under_its_wire_name() -> None:
    flt = WalletTransactionFilter(
        created_from=datetime(2026, 10, 1, tzinfo=UTC),
        created_to=datetime(2026, 10, 31, tzinfo=UTC),
        currency=Currency.USD,
        fee_type=TransactionFeeType.MARKET_PRODUCT,
        initial_deposit_currencies=[Currency.USD],
        initial_withdrawal_currencies=[Currency.USD],
        buyer=False,
        seller=True,
        reason=TransactionReason.TRANSFER,
        reasons=[TransactionReason.BONUS],
        sort=WalletTransactionSort(field=TransactionSortField.AMOUNT, direction=SortDirection.DESC),
        status=TransactionStatus.SUCCESS,
        deposit_methods=["SEPA"],
        withdrawal_methods=["PAYPAL"],
    )

    assert wire(flt) == {
        "createdAt": {"from": "2026-10-01T00:00:00+00:00", "to": "2026-10-31T00:00:00+00:00"},
        "currency": "USD",
        "feeType": "MARKET_PRODUCT",
        "initialCurrencyDeposit": ["USD"],
        "initialCurrencyWithdrawal": ["USD"],
        "isBuyer": False,
        "isSeller": True,
        "reason": "TRANSFER",
        "reasons": ["BONUS"],
        "sort": {"field": "AMOUNT", "type": "DESC"},
        "status": "SUCCESS",
        "walletMethodsDeposit": ["SEPA"],
        "walletMethodsWithdrawal": ["PAYPAL"],
    }


def test_the_sort_direction_defaults_to_ascending() -> None:
    sort = WalletTransactionSort(field=TransactionSortField.CREATED_AT)

    assert to_plain(wallet_transaction_sort_input(sort)) == {"field": "CREATED_AT", "type": "ASC"}


def test_a_false_boolean_is_sent_not_dropped() -> None:
    assert wire(WalletTransactionFilter(buyer=False)) == {"isBuyer": False}


def test_lists_given_are_kept_as_tuples_and_the_filter_is_immutable() -> None:
    methods = ["SEPA"]
    flt = WalletTransactionFilter(deposit_methods=methods)
    methods.append("PAYPAL")

    assert flt.deposit_methods == ("SEPA",)
    with pytest.raises(FrozenInstanceError):
        flt.buyer = True


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="created_from"):
        WalletTransactionFilter(created_from=NAIVE)


def test_a_reason_the_schema_does_not_accept_is_refused_when_encoded() -> None:
    flt = WalletTransactionFilter(reason=TransactionReason("TELEPORT"))

    with pytest.raises(ValueError, match="TELEPORT"):
        wallet_transaction_search_input(flt)
