"""`client.wallet`: balances, deposits, withdrawals, transactions, transfers and the credit line
(SDK_SPEC 3.8).

Everything that reads is a query, which the transport retries on transient failures (SDK_SPEC
1.4). `take_credit()` and `transfer()` move money and are mutations: each is sent exactly once and
never retried (CLAUDE.md rule 2), and neither has an idempotency key. A failure that proves the
server did not run it (a malformed request, a rejected credential, a rate limit, a GraphQL error
of the root field) propagates as its own error. Any other failure (a timeout, a 5xx, an unreadable
answer) is a `MutationOutcomeUnknownError`: the money may have moved, so check before sending
again.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Final

from whitemarket._async.pagination import forward_pagination, iterate_pages
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._generated.input_types import WalletTransactionSearchInput
from whitemarket._mappers.common import map_list, map_page, money
from whitemarket._mappers.search import search_argument, wallet_transaction_search_input
from whitemarket._mappers.wallet import (
    map_credit,
    map_debt,
    map_deposit,
    map_wallet_transaction,
    map_wallet_transfer,
    map_withdrawal,
)
from whitemarket._mappers.wire import wire_enum, wire_money
from whitemarket._runtime.rejection import is_mutation_rejection
from whitemarket._runtime.text_args import require_text
from whitemarket.errors import MutationOutcomeUnknownError
from whitemarket.models.enums import Currency
from whitemarket.models.money import Money
from whitemarket.models.page import Page, PageRequest
from whitemarket.models.wallet import (
    Credit,
    Debt,
    Deposit,
    WalletTransaction,
    WalletTransfer,
    Withdrawal,
)
from whitemarket.wallet.filter import WalletTransactionFilter

# One document with the three root fields (SDK_SPEC 3.8 rule 1): typed per-operation overrides
# hold one root field. The selection is that of the `MoneyFields` fragment.
_CREDIT_QUERY: Final = (
    "query WalletCredit { "
    "wallet_credit_max { value currency } "
    "wallet_credit_used { value currency } "
    "wallet_credit_available { value currency } }"
)
_TRANSACTIONS = ("wallet_transactions",)
_TRANSFERS = ("wallet_transfers",)


class AsyncWalletApi:
    """`client.wallet`."""

    def __init__(self, generated: AsyncGeneratedClient) -> None:
        self._generated = generated

    async def balance(self, currency: Currency) -> Money:
        """The balance in one currency (`wallet_balance`). Raises `ValueError` for a currency this
        SDK does not know, before anything is sent."""
        answer = await self._generated.wallet_balance(wire_enum(Currency, currency))
        return money(answer.wallet_balance, ("wallet_balance",))

    async def balances(self) -> list[Money]:
        """The balances in every currency (`wallet_balances`)."""
        answer = await self._generated.wallet_balances()
        return map_list(answer.wallet_balances, money, ("wallet_balances",))

    async def deposits(self) -> list[Deposit]:
        """The deposits (`wallet_deposits`). `Deposit.airwallex_secret` is a `Secret`."""
        answer = await self._generated.wallet_deposits()
        return map_list(answer.wallet_deposits, map_deposit, ("wallet_deposits",))

    async def withdrawals(self) -> list[Withdrawal]:
        """The withdrawals (`wallet_withdrawals`)."""
        answer = await self._generated.wallet_withdrawals()
        return map_list(answer.wallet_withdrawals, map_withdrawal, ("wallet_withdrawals",))

    async def transactions(
        self,
        filter: WalletTransactionFilter | WalletTransactionSearchInput | None = None,
        page: PageRequest | None = None,
    ) -> Page[WalletTransaction]:
        """One page of wallet transactions (`wallet_transactions`).

        Pass `PageRequest(after=previous.end_cursor)` for the next page while
        `previous.has_next_page` is true, or use `iterate_transactions()`. A raw
        `WalletTransactionSearchInput` is sent as is. The server's defaults apply to what `page`
        leaves out.
        """
        answer = await self._generated.wallet_transactions(
            forward_pagination=forward_pagination(page),
            search=search_argument(
                filter, WalletTransactionSearchInput, wallet_transaction_search_input
            ),
        )
        return map_page(answer.wallet_transactions, map_wallet_transaction, _TRANSACTIONS)

    def iterate_transactions(
        self,
        filter: WalletTransactionFilter | WalletTransactionSearchInput | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[WalletTransaction]:
        """Every wallet transaction that matches, page after page; a page is requested only when
        the previous one is consumed. `page_size` is the items per request (the server's default
        when None). Raises what `transactions()` raises, at the point of the iteration that reads
        the failing page, and `DecodeError` when the server reports a next page without a new
        cursor.
        """
        return iterate_pages(partial(self.transactions, filter), page_size, _TRANSACTIONS)

    async def transfers(self, page: PageRequest | None = None) -> Page[WalletTransfer]:
        """One page of transfers between partners (`wallet_transfers`)."""
        answer = await self._generated.wallet_transfers(forward_pagination(page))
        return map_page(answer.wallet_transfers, map_wallet_transfer, _TRANSFERS)

    def iterate_transfers(self, page_size: int | None = None) -> AsyncIterator[WalletTransfer]:
        """Every transfer, page after page, lazily (see `iterate_transactions()`)."""
        return iterate_pages(self.transfers, page_size, _TRANSFERS)

    async def credit(self) -> Credit:
        """The credit line: the most that may be owed, what is owed and what is still available.

        One query document with the three root fields, so the figures are consistent, retried like
        any query. Raises `DecodeError` naming the field when one is missing or malformed.
        """
        data = await self._generated.execute(
            _CREDIT_QUERY, None, "WalletCredit", operation_type="query"
        )
        return map_credit(data)

    async def take_credit(self, amount: Money) -> Debt:
        """Take credit (`wallet_credit_get`). Sent once, never retried.

        Raises `ValueError`, before anything is sent, for a currency this SDK does not know. A
        rejection (the server did not run it) propagates as its own error. Any other failure is a
        `MutationOutcomeUnknownError`: the money may have moved, so check `credit()` before
        sending again.
        """
        wire = wire_money(amount)
        try:
            answer = await self._generated.wallet_credit_get(wire)
            return map_debt(answer.wallet_credit_get, ("wallet_credit_get",))
        except Exception as error:
            if is_mutation_rejection(error, "wallet_credit_get"):
                raise
            raise MutationOutcomeUnknownError("wallet.take_credit") from error

    async def transfer(self, to: str, amount: Money) -> WalletTransfer:
        """Send money to another partner (`wallet_transfer_send`). Sent once, never retried.

        `to` is a person id or a Steam id, sent unchanged (the API does not document the format).
        Raises `ValueError`, before anything is sent, when `to` is empty, is not valid UTF-8 or
        holds a control character, or the currency of `amount` is unknown to this SDK. A
        rejection (the server did not run it) propagates as its own error. Any other failure is a
        `MutationOutcomeUnknownError`: the money may have moved, so check `transfers()` before
        sending again.
        """
        require_text(to, "the recipient", non_empty=True, no_control=True)
        wire = wire_money(amount)
        try:
            answer = await self._generated.wallet_transfer_send(wire, to)
            return map_wallet_transfer(answer.wallet_transfer_send, ("wallet_transfer_send",))
        except Exception as error:
            if is_mutation_rejection(error, "wallet_transfer_send"):
                raise
            raise MutationOutcomeUnknownError("wallet.transfer") from error
