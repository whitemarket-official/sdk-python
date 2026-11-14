"""Models of the wallet: deposits, withdrawals, transactions, transfers, credit (SDK_SPEC 3.8)."""

from dataclasses import dataclass, field
from datetime import datetime

from whitemarket._runtime.secret import Secret
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
from whitemarket.models.enums import DealAction, DeliveryPromise, TransactionReason
from whitemarket.models.money import Money


@dataclass(frozen=True, slots=True, kw_only=True)
class PersonSummary:
    """The public profile of a party to a wallet operation.

    `id` is the partner's id on the marketplace; `steam_id` is the 64-bit Steam id kept as a string.
    The Steam fields are personal data: do not log them.
    """

    id: str
    steam_id: str | None
    steam_name: str | None
    steam_avatar: str | None
    steam_level: int | None
    steam_registered_at: datetime | None
    delivery_promise: DeliveryPromise | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Deposit:
    """A deposit into the wallet (`wallet.deposits()`).

    `airwallex_secret` is the client secret of an Airwallex payment, a credential: a `Secret`,
    `None` when the server sends none, and left out of `repr()`.
    """

    id: str
    created_at: datetime
    completed_at: datetime | None
    expired_at: datetime | None
    provider: PaymentProvider
    status: DepositStatus
    amount: Money
    comment: str | None
    provider_corresponding_id: str | None
    provider_payment_page: str | None
    person: PersonSummary
    airwallex_secret: Secret | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Withdrawal:
    """A withdrawal from the wallet (`wallet.withdrawals()`)."""

    id: str
    created_at: datetime
    completed_at: datetime | None
    expired_at: datetime | None
    provider: PaymentProvider
    status: WithdrawalStatus
    amount: Money
    comment: str | None
    provider_corresponding_id: str | None
    person: PersonSummary


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletTransaction:
    """One movement of money on the wallet (`wallet.transactions()`).

    `reason_id` is the id of the object the transaction belongs to (a deal, a deposit, ...), by
    `reason`. `withdrawal_address` is a crypto address: personal data, do not log it.
    `counterparty` is the other party of a transfer or a deal.
    """

    id: str
    created_at: datetime
    reason: TransactionReason
    reason_id: str
    status: TransactionStatus
    amount: Money
    fee: Money | None
    comment: str | None
    initial_currency: CryptoCurrency | None
    deal_action: DealAction | None
    method: WalletMethod | None
    network: CryptoNetwork | None
    withdrawal_address: str | None
    person: PersonSummary
    counterparty: PersonSummary | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletTransfer:
    """A transfer of money between two partners (`wallet.transfers()`, `wallet.transfer()`).

    `from_` is the sender (`from` is a Python keyword) and `to` the recipient."""

    id: str
    created_at: datetime
    completed_at: datetime | None
    status: TransferStatus
    amount: Money
    comment: str | None
    from_: PersonSummary
    to: PersonSummary


@dataclass(frozen=True, slots=True, kw_only=True)
class Debt:
    """Credit taken from the marketplace (`wallet.take_credit()`)."""

    id: str
    created_at: datetime
    amount: Money


@dataclass(frozen=True, slots=True, kw_only=True)
class Credit:
    """The credit line of the wallet (`wallet.credit()`), read in one request so the three figures
    are consistent: the most that may be owed, what is owed, and what can still be taken."""

    max: Money
    used: Money
    available: Money
