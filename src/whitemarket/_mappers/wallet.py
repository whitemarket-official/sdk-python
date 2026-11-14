"""Mappers of the wallet models: money movements, transfers, the credit line (SDK_SPEC 3.8)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from whitemarket._generated.fragments import MoneyFields, PersonPublicFields
from whitemarket._generated.wallet_credit_get import WalletCreditGetWalletCreditGet
from whitemarket._generated.wallet_deposits import WalletDepositsWalletDeposits
from whitemarket._generated.wallet_transactions import (
    WalletTransactionsWalletTransactions,
    WalletTransactionsWalletTransactionsEdgesNode,
)
from whitemarket._generated.wallet_withdrawals import WalletWithdrawalsWalletWithdrawals
from whitemarket._mappers.common import (
    MoneySource,
    Path,
    convert_enum,
    map_page,
    money,
    optional_enum,
    optional_money,
)
from whitemarket._runtime.decode import decode_error_from
from whitemarket.errors import DecodeError
from whitemarket.models.account_enums import (
    CryptoCurrency,
    CryptoNetwork,
    DepositStatus,
    PaymentProvider,
    TransactionStatus,
    TransferStatus,
    WalletMethod,
    WithdrawalStatus,
)
from whitemarket.models.enums import DealAction, TransactionReason
from whitemarket.models.money import Money
from whitemarket.models.page import Page
from whitemarket.models.wallet import (
    Credit,
    Debt,
    Deposit,
    PersonSummary,
    WalletTransaction,
    WalletTransfer,
    Withdrawal,
)


class TransferSource(Protocol):
    """The fields of every selection of `WalletTransfer` (`wallet_transfers` and the send)."""

    @property
    def id(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def completed_at(self) -> datetime | None: ...
    @property
    def status(self) -> str: ...
    @property
    def amount(self) -> MoneySource: ...
    @property
    def comment(self) -> str | None: ...
    @property
    def from_(self) -> PersonPublicFields: ...
    @property
    def to(self) -> PersonPublicFields: ...


def map_person_summary(source: PersonPublicFields) -> PersonSummary:
    return PersonSummary(
        id=source.id,
        steam_id=source.steam_id,
        steam_name=source.steam_name,
        steam_avatar=source.steam_avatar,
        steam_level=source.steam_level,
        steam_registered_at=source.steam_registered_at,
        delivery_promise=source.delivery_promise,
    )


def map_deposit(source: WalletDepositsWalletDeposits, path: Path) -> Deposit:
    return Deposit(
        id=source.id,
        created_at=source.created_at,
        completed_at=source.completed_at,
        expired_at=source.expired_at,
        provider=convert_enum(PaymentProvider, source.provider),
        status=convert_enum(DepositStatus, source.status),
        amount=money(source.amount, (*path, "amount")),
        comment=source.comment,
        provider_corresponding_id=source.provider_corresponding_id,
        provider_payment_page=source.provider_payment_page,
        person=map_person_summary(source.person),
        airwallex_secret=source.airwallex_secret,
    )


def map_withdrawal(source: WalletWithdrawalsWalletWithdrawals, path: Path) -> Withdrawal:
    return Withdrawal(
        id=source.id,
        created_at=source.created_at,
        completed_at=source.completed_at,
        expired_at=source.expired_at,
        provider=convert_enum(PaymentProvider, source.provider),
        status=convert_enum(WithdrawalStatus, source.status),
        amount=money(source.amount, (*path, "amount")),
        comment=source.comment,
        provider_corresponding_id=source.provider_corresponding_id,
        person=map_person_summary(source.person),
    )


def map_wallet_transaction(
    source: WalletTransactionsWalletTransactionsEdgesNode, path: Path
) -> WalletTransaction:
    return WalletTransaction(
        id=source.id,
        created_at=source.created_at,
        reason=convert_enum(TransactionReason, source.reason),
        reason_id=source.reason_id,
        status=convert_enum(TransactionStatus, source.status),
        amount=money(source.amount, (*path, "amount")),
        fee=optional_money(source.fee, (*path, "fee")),
        comment=source.comment,
        initial_currency=optional_enum(CryptoCurrency, source.initial_currency),
        deal_action=optional_enum(DealAction, source.market_deal_action_type),
        method=optional_enum(WalletMethod, source.method),
        network=optional_enum(CryptoNetwork, source.network),
        withdrawal_address=source.withdrawal_address,
        person=map_person_summary(source.person),
        counterparty=None
        if source.counterparty is None
        else map_person_summary(source.counterparty),
    )


def map_wallet_transaction_page(
    connection: WalletTransactionsWalletTransactions, path: Path
) -> Page[WalletTransaction]:
    return map_page(connection, map_wallet_transaction, path)


def map_wallet_transfer(source: TransferSource, path: Path) -> WalletTransfer:
    return WalletTransfer(
        id=source.id,
        created_at=source.created_at,
        completed_at=source.completed_at,
        status=convert_enum(TransferStatus, source.status),
        amount=money(source.amount, (*path, "amount")),
        comment=source.comment,
        from_=map_person_summary(source.from_),
        to=map_person_summary(source.to),
    )


def map_debt(source: WalletCreditGetWalletCreditGet, path: Path) -> Debt:
    return Debt(
        id=source.id, created_at=source.created_at, amount=money(source.amount, (*path, "amount"))
    )


def map_credit(data: Mapping[str, object]) -> Credit:
    """The credit line from the data of the one `WalletCredit` document (three root fields).

    A missing or malformed field is a `DecodeError` naming the field and the failing part, never
    the value.
    """
    return Credit(
        max=_credit_figure(data, "wallet_credit_max"),
        used=_credit_figure(data, "wallet_credit_used"),
        available=_credit_figure(data, "wallet_credit_available"),
    )


def _credit_figure(data: Mapping[str, object], field: str) -> Money:
    try:
        fragment = MoneyFields.model_validate(data.get(field))
    except ValidationError as exc:
        error = decode_error_from(exc)
    else:
        return money(fragment, (field,))
    # Raised outside the except block: no __context__ keeps the ValidationError and its input.
    raise DecodeError(error.reason, (field, *error.path))
