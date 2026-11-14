"""`WalletTransactionFilter` and `WalletTransactionSort`: conditions of `wallet.transactions()`
(SDK_SPEC 3.8)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from whitemarket._generated.enums import (
    SortType,
    WalletTransactionFeeType,
    WalletTransactionReason,
    WalletTransactionSortField,
    WalletTransactionStatus,
)
from whitemarket._generated.input_types import (
    WalletTransactionSearchInput,
    WalletTransactionSortInput,
)
from whitemarket._mappers.wire import present, wire_date_range, wire_enum, wire_enums, wire_list
from whitemarket._runtime.filter_checks import normalize_filter
from whitemarket.models.account_enums import (
    TransactionFeeType,
    TransactionSortField,
    TransactionStatus,
)
from whitemarket.models.enums import Currency, SortDirection, TransactionReason

_TUPLE_FIELDS = (
    "initial_deposit_currencies",
    "initial_withdrawal_currencies",
    "reasons",
    "deposit_methods",
    "withdrawal_methods",
)
_DATE_FIELDS = ("created_from", "created_to")


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletTransactionSort:
    """How the wallet transactions are ordered (`WalletTransactionFilter(sort=...)`)."""

    field: TransactionSortField
    direction: SortDirection = SortDirection.ASC

    def to_input(self) -> WalletTransactionSortInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return WalletTransactionSortInput(
            field=wire_enum(WalletTransactionSortField, self.field),
            type_=wire_enum(SortType, self.direction),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletTransactionFilter:
    """Conditions of a wallet transaction list (`wallet.transactions()`): every field is optional
    and the ones given are combined with AND. Pass a raw `WalletTransactionSearchInput` to
    `wallet.transactions()` for anything this class does not cover.

    Immutable: change a copy with `dataclasses.replace(filter, buyer=True)`. Lists given are kept
    as tuples. `created_from` / `created_to` are aware datetimes. `initial_deposit_currencies` and
    `initial_withdrawal_currencies` are the currencies a deposit or a withdrawal was made in;
    `buyer` / `seller` keep only the transactions of deals where the partner bought / sold;
    `deposit_methods` and `withdrawal_methods` are wallet methods as the API names them.

    Raises `ValueError` for a naive datetime.
    """

    created_from: datetime | None = None
    created_to: datetime | None = None
    currency: Currency | None = None
    fee_type: TransactionFeeType | None = None
    initial_deposit_currencies: Sequence[Currency] | None = None
    initial_withdrawal_currencies: Sequence[Currency] | None = None
    buyer: bool | None = None
    seller: bool | None = None
    reason: TransactionReason | None = None
    reasons: Sequence[TransactionReason] | None = None
    sort: WalletTransactionSort | None = None
    status: TransactionStatus | None = None
    deposit_methods: Sequence[str] | None = None
    withdrawal_methods: Sequence[str] | None = None

    def __post_init__(self) -> None:
        normalize_filter(self, tuples=_TUPLE_FIELDS, dates=_DATE_FIELDS)

    def to_input(self) -> WalletTransactionSearchInput:
        """The generated input; used by the high-level API, not part of the public API."""
        return WalletTransactionSearchInput(
            **present(
                created_at=wire_date_range(self.created_from, self.created_to),
                currency=wire_enum(Currency, self.currency),
                fee_type=wire_enum(WalletTransactionFeeType, self.fee_type),
                initial_currency_deposit=wire_enums(Currency, self.initial_deposit_currencies),
                initial_currency_withdrawal=wire_enums(
                    Currency, self.initial_withdrawal_currencies
                ),
                is_buyer=self.buyer,
                is_seller=self.seller,
                reason=wire_enum(WalletTransactionReason, self.reason),
                reasons=wire_enums(WalletTransactionReason, self.reasons),
                sort=None if self.sort is None else self.sort.to_input(),
                status=wire_enum(WalletTransactionStatus, self.status),
                wallet_methods_deposit=wire_list(self.deposit_methods),
                wallet_methods_withdrawal=wire_list(self.withdrawal_methods),
            )
        )
