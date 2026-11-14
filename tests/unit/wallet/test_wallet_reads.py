"""`client.wallet` reads through the HTTP boundary: request shape, mapping, pagination (3.8).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from support import account_payloads as ap
from support.clients import Rig
from support.flavors import Flavor
from support.http import data, json_response, reply
from whitemarket import RetryPolicy
from whitemarket._generated.input_types import WalletTransactionSearchInput
from whitemarket._runtime.secret import Secret
from whitemarket.errors import DecodeError, GraphQLError
from whitemarket.models import Currency, DealAction, DeliveryPromise, Money, PageRequest
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
from whitemarket.models.enums import TransactionReason
from whitemarket.wallet import WalletTransactionFilter

NO_WAIT = {"retry": RetryPolicy(base_delay=0)}


# ---- balances ----


def test_balance_sends_the_currency_and_keeps_the_amount_exact(flavor: Flavor) -> None:
    answer = data(wallet_balance=ap.money("12345678901234567890.123456789"))
    with Rig(flavor, answer) as rig:
        balance = rig.call(rig.client.wallet.balance(Currency.USD))

        (body,) = rig.bodies()
        assert (body["operationName"], body["variables"]) == (
            "WalletBalance",
            {"currency": "USD"},
        )
    assert balance == Money(amount=Decimal("12345678901234567890.123456789"), currency=Currency.USD)
    assert isinstance(balance.amount, Decimal)


def test_balance_refuses_a_currency_this_sdk_does_not_know_before_sending(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_balance=ap.money())) as rig:
        with pytest.raises(ValueError, match="EUR"):
            rig.call(rig.client.wallet.balance(Currency("EUR")))

        assert rig.script.count == 0


def test_balances_map_every_currency_and_keep_an_unknown_one(flavor: Flavor) -> None:
    answer = data(wallet_balances=[ap.money("1.50"), ap.money("0.10", "EUR")])
    with Rig(flavor, answer) as rig:
        balances = rig.call(rig.client.wallet.balances())

    assert [(b.amount, b.currency.value) for b in balances] == [
        (Decimal("1.50"), "USD"),
        (Decimal("0.10"), "EUR"),
    ]
    assert balances[1].currency.is_unknown


def test_balances_of_an_empty_account_is_an_empty_list(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_balances=[])) as rig:
        assert rig.call(rig.client.wallet.balances()) == []


def test_a_malformed_balance_names_its_path(flavor: Flavor) -> None:
    answer = data(wallet_balances=[ap.money("1.00"), ap.money("1,00")])
    with Rig(flavor, answer) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.wallet.balances())

    assert caught.value.path == ("wallet_balances", 1, "value")
    assert "1,00" not in str(caught.value)


def test_a_balance_graphql_error_carries_its_category(flavor: Flavor) -> None:
    answer = json_response(
        {"data": None, "errors": [{"message": "x", "extensions": {"category": "wallet.locked"}}]}
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.wallet.balances())

    assert caught.value.errors[0].category == "wallet.locked"


def test_reads_are_retried_as_queries(flavor: Flavor) -> None:
    with Rig(flavor, reply(503), data(wallet_balances=[ap.money()]), **NO_WAIT) as rig:
        balances = rig.call(rig.client.wallet.balances())

        assert rig.script.count == 2
    assert len(balances) == 1


# ---- deposits and withdrawals ----


def test_deposits_map_every_field(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_deposits=[ap.deposit()])) as rig:
        (deposit,) = rig.call(rig.client.wallet.deposits())

        assert [(b["operationName"], b.get("variables", {})) for b in rig.bodies()] == [
            ("WalletDeposits", {})
        ]
    assert deposit.id == "dep-1"
    assert deposit.created_at == datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
    assert deposit.completed_at == datetime(2026, 10, 30, 10, 5, tzinfo=UTC)
    assert deposit.expired_at == datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    assert deposit.provider is PaymentProvider.AIRWALLEX
    assert deposit.status is DepositStatus.PROCESSING
    assert deposit.amount == Money.usd("100.05")
    assert deposit.comment == "a comment"
    assert deposit.provider_corresponding_id == "prov-1"
    assert deposit.provider_payment_page == "https://example.invalid/pay"
    assert isinstance(deposit.airwallex_secret, Secret)
    assert deposit.airwallex_secret.reveal() == "synthetic-airwallex-secret"
    assert deposit.person.id == "p-1"
    assert deposit.person.steam_id == ap.STEAM_ID
    assert deposit.person.steam_level == 7
    assert deposit.person.delivery_promise is DeliveryPromise.HOUR1


def test_a_deposit_never_shows_its_secret_in_repr_or_str(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_deposits=[ap.deposit()])) as rig:
        (deposit,) = rig.call(rig.client.wallet.deposits())

    for text in (repr(deposit), str(deposit), f"{deposit.airwallex_secret}"):
        assert "synthetic-airwallex-secret" not in text
    assert str(deposit.airwallex_secret) == "***"


def test_a_deposit_without_optional_parts_has_nones(flavor: Flavor) -> None:
    deposit = ap.deposit(
        airwallexSecret=None,
        completedAt=None,
        expiredAt=None,
        comment=None,
        providerCorrespondingId=None,
        providerPaymentPage=None,
    )
    with Rig(flavor, data(wallet_deposits=[deposit])) as rig:
        (mapped,) = rig.call(rig.client.wallet.deposits())

    assert (mapped.airwallex_secret, mapped.completed_at, mapped.expired_at, mapped.comment) == (
        None,
        None,
        None,
        None,
    )


def test_unknown_deposit_enum_values_are_kept_not_raised(flavor: Flavor) -> None:
    deposit = ap.deposit(
        provider="NEW_PROVIDER",
        status="NEW_STATUS",
        person=ap.person(deliveryPromise="NEW_PROMISE"),
    )
    with Rig(flavor, data(wallet_deposits=[deposit])) as rig:
        (mapped,) = rig.call(rig.client.wallet.deposits())

    assert (mapped.provider.value, mapped.provider.is_unknown) == ("NEW_PROVIDER", True)
    assert (mapped.status.value, mapped.status.is_unknown) == ("NEW_STATUS", True)
    assert mapped.person.delivery_promise is not None
    assert mapped.person.delivery_promise.value == "NEW_PROMISE"


def test_withdrawals_map_every_field(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_withdrawals=[ap.withdrawal()])) as rig:
        (w,) = rig.call(rig.client.wallet.withdrawals())

    assert w.id == "wd-1"
    assert w.completed_at == datetime(2026, 10, 30, 10, 5, tzinfo=UTC)
    assert w.expired_at == datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    assert w.provider is PaymentProvider.SEPA
    assert w.status is WithdrawalStatus.SUCCESS
    assert w.amount == Money.usd("7.77")
    assert (w.comment, w.provider_corresponding_id, w.person.id) == ("note", "prov-9", "p-2")


def test_a_new_withdrawal_status_is_kept(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_withdrawals=[ap.withdrawal(status="REVIEW")])) as rig:
        (w,) = rig.call(rig.client.wallet.withdrawals())

    assert w.status.value == "REVIEW"
    assert w.status.is_unknown


# ---- transactions ----


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        pytest.param(None, {}, id="no request -> no variable"),
        pytest.param(PageRequest(), {}, id="empty request -> no variable"),
        pytest.param(
            PageRequest(first=10, after="c"),
            {"forwardPagination": {"after": "c", "first": 10}},
            id="first and after",
        ),
    ],
)
def test_transactions_send_forward_pagination_only_when_given(
    flavor: Flavor, page: PageRequest | None, expected: dict[str, Any]
) -> None:
    with Rig(flavor, data(**ap.connection("wallet_transactions", []))) as rig:
        rig.call(rig.client.wallet.transactions(None, page))

        (body,) = rig.bodies()
        assert body["operationName"] == "WalletTransactions"
        assert body.get("variables", {}) == expected


def test_transactions_map_every_field(flavor: Flavor) -> None:
    answer = ap.connection("wallet_transactions", [ap.transaction()], "c1", True, 31)
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.wallet.transactions())

    assert (page.end_cursor, page.has_next_page, page.total_count) == ("c1", True, 31)
    (t,) = page.items
    assert t.id == "t-1"
    assert t.created_at == datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
    assert t.reason is TransactionReason.MARKET_PRODUCT
    assert t.reason_id == "deal-77"
    assert t.status is TransactionStatus.SUCCESS_HOLD
    assert t.amount == Money.usd("-10.10")
    assert t.fee == Money.usd("0.31")
    assert t.comment == "c"
    assert t.initial_currency is CryptoCurrency.USDT
    assert t.deal_action is DealAction.SELL
    assert t.method is WalletMethod.WHITEBIT_CODE
    assert t.network is CryptoNetwork.TRC20
    assert t.withdrawal_address == "synthetic-address"
    assert t.person.id == "me"
    assert t.counterparty is not None
    assert (t.counterparty.id, t.counterparty.steam_id) == ("them", "76561190000000002")


def test_a_transaction_without_optional_parts_has_nones(flavor: Flavor) -> None:
    node = ap.transaction(
        fee=None,
        counterparty=None,
        initialCurrency=None,
        marketDealActionType=None,
        method=None,
        network=None,
        withdrawalAddress=None,
        comment=None,
    )
    with Rig(flavor, data(**ap.connection("wallet_transactions", [node]))) as rig:
        (t,) = rig.call(rig.client.wallet.transactions()).items

    assert (t.fee, t.counterparty, t.initial_currency, t.deal_action, t.method, t.network) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert (t.withdrawal_address, t.comment) == (None, None)


@pytest.mark.parametrize(
    "field",
    ["reason", "status", "initialCurrency", "marketDealActionType", "method", "network"],
)
def test_unknown_transaction_enum_values_are_kept(flavor: Flavor, field: str) -> None:
    node = ap.transaction(**{field: "FUTURE_VALUE"})
    with Rig(flavor, data(**ap.connection("wallet_transactions", [node]))) as rig:
        (t,) = rig.call(rig.client.wallet.transactions()).items

    attribute = {
        "reason": "reason",
        "status": "status",
        "initialCurrency": "initial_currency",
        "marketDealActionType": "deal_action",
        "method": "method",
        "network": "network",
    }[field]
    value = getattr(t, attribute)
    assert (value.value, value.is_unknown) == ("FUTURE_VALUE", True)


def test_instant_exchange_reasons_are_known_members(flavor: Flavor) -> None:
    node = ap.transaction(reason="INSTANT_EXCHANGE_HOLD_RELEASE_IN")
    with Rig(flavor, data(**ap.connection("wallet_transactions", [node]))) as rig:
        (t,) = rig.call(rig.client.wallet.transactions()).items

    assert t.reason is TransactionReason.INSTANT_EXCHANGE_HOLD_RELEASE_IN
    assert not t.reason.is_unknown


def test_transactions_skip_null_edges_and_nodes_and_tolerate_null_lists(flavor: Flavor) -> None:
    first = {
        "wallet_transactions": {
            "edges": [
                {"cursor": "a", "node": ap.transaction(id="kept")},
                None,
                {"cursor": "x", "node": None},
            ],
            "pageInfo": None,
            "totalCount": None,
        }
    }
    second = {"wallet_transactions": {"edges": None, "pageInfo": None, "totalCount": None}}
    with Rig(flavor, data(**first), data(**second)) as rig:
        one = rig.call(rig.client.wallet.transactions())
        two = rig.call(rig.client.wallet.transactions())

    assert [t.id for t in one.items] == ["kept"]
    assert (one.has_next_page, one.end_cursor, two.items) == (False, None, ())


def test_transactions_encode_a_filter(flavor: Flavor) -> None:
    flt = WalletTransactionFilter(
        created_from=datetime(2026, 10, 1, tzinfo=UTC),
        buyer=True,
        reason=TransactionReason.DEPOSIT,
        reasons=[TransactionReason.INSTANT_EXCHANGE, TransactionReason.WITHDRAWAL],
        initial_deposit_currencies=[Currency.USD],
        deposit_methods=["SEPA"],
    )
    with Rig(flavor, data(**ap.connection("wallet_transactions", []))) as rig:
        rig.call(rig.client.wallet.transactions(flt))

        (variables,) = rig.variables()
    assert variables == {
        "search": {
            "createdAt": {"from": "2026-10-01T00:00:00+00:00"},
            "initialCurrencyDeposit": ["USD"],
            "isBuyer": True,
            "reason": "DEPOSIT",
            "reasons": ["INSTANT_EXCHANGE", "WITHDRAWAL"],
            "walletMethodsDeposit": ["SEPA"],
        }
    }


def test_transactions_send_a_raw_input_exactly(flavor: Flavor) -> None:
    raw = WalletTransactionSearchInput(is_buyer=False)
    with Rig(flavor, data(**ap.connection("wallet_transactions", []))) as rig:
        rig.call(rig.client.wallet.transactions(raw))

        assert rig.variables() == [{"search": {"isBuyer": False}}]


def test_iterate_transactions_is_lazy_and_follows_cursors_keeping_the_filter(
    flavor: Flavor,
) -> None:
    flt = WalletTransactionFilter(seller=True)
    pages = [
        data(
            **ap.connection(
                "wallet_transactions", [ap.transaction(id="a"), ap.transaction(id="b")], "c2", True
            )
        ),
        data(**ap.connection("wallet_transactions", [ap.transaction(id="c")], None, False)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.wallet.iterate_transactions(flt, 2)
        assert rig.script.count == 0, "created, not started"

        assert rig.step(items).id == "a"
        assert rig.step(items).id == "b"
        assert rig.script.count == 1, "last item of page 1: page 2 is not requested yet"
        assert rig.step(items).id == "c"
        with pytest.raises(StopIteration):
            rig.step(items)

        assert rig.variables() == [
            {"forwardPagination": {"first": 2}, "search": {"isSeller": True}},
            {"forwardPagination": {"after": "c2", "first": 2}, "search": {"isSeller": True}},
        ]


def test_iterate_transactions_names_the_list_in_the_path_of_a_missing_cursor(
    flavor: Flavor,
) -> None:
    answer = ap.connection("wallet_transactions", [ap.transaction()], None, True)
    with Rig(flavor, data(**answer)) as rig, pytest.raises(DecodeError) as caught:
        rig.drain(rig.client.wallet.iterate_transactions())

    assert caught.value.path == ("wallet_transactions", "pageInfo", "endCursor")


# ---- transfers ----


def test_transfers_map_every_field_and_send_the_page(flavor: Flavor) -> None:
    answer = ap.connection("wallet_transfers", [ap.transfer()], None, False, 1)
    with Rig(flavor, data(**answer)) as rig:
        page = rig.call(rig.client.wallet.transfers(PageRequest(first=10)))

        assert [(b["operationName"], b["variables"]) for b in rig.bodies()] == [
            ("WalletTransfers", {"forwardPagination": {"first": 10}})
        ]
    (t,) = page.items
    assert page.total_count == 1
    assert t.id == "tr-1"
    assert t.completed_at == datetime(2026, 10, 30, 10, 5, tzinfo=UTC)
    assert t.status is TransferStatus.PROCESSING
    assert t.amount == Money.usd("3.30")
    assert t.comment == "hi"
    assert (t.from_.id, t.to.id) == ("a", "b")


def test_a_new_transfer_status_is_kept(flavor: Flavor) -> None:
    answer = ap.connection("wallet_transfers", [ap.transfer(status="HELD")])
    with Rig(flavor, data(**answer)) as rig:
        (t,) = rig.call(rig.client.wallet.transfers()).items

    assert (t.status.value, t.status.is_unknown) == ("HELD", True)


def test_iterate_transfers_is_lazy_and_follows_cursors(flavor: Flavor) -> None:
    pages = [
        data(**ap.connection("wallet_transfers", [ap.transfer(id="a")], "c1", True)),
        data(**ap.connection("wallet_transfers", [ap.transfer(id="b")], None, False)),
    ]
    with Rig(flavor, *pages) as rig:
        items = rig.client.wallet.iterate_transfers(1)
        assert rig.script.count == 0

        ids = [t.id for t in rig.drain(items)]

        assert ids == ["a", "b"]
        assert rig.variables() == [
            {"forwardPagination": {"first": 1}},
            {"forwardPagination": {"after": "c1", "first": 1}},
        ]


# ---- credit ----


def test_credit_reads_the_three_figures_in_one_query_document(flavor: Flavor) -> None:
    with Rig(flavor, data(**ap.credit())) as rig:
        credit = rig.call(rig.client.wallet.credit())

        (body,) = rig.bodies()
    assert body["operationName"] == "WalletCredit"
    for field in ("wallet_credit_max", "wallet_credit_used", "wallet_credit_available"):
        assert f"{field} {{ value currency }}" in body["query"]
    assert body["query"].lstrip().startswith("query ")
    assert "mutation" not in body["query"]
    assert (credit.max, credit.used, credit.available) == (
        Money.usd("1000.00"),
        Money.usd("250.5"),
        Money.usd("749.50"),
    )


def test_credit_is_retried_as_one_query(flavor: Flavor) -> None:
    with Rig(flavor, reply(503), data(**ap.credit(max="1.00")), **NO_WAIT) as rig:
        credit = rig.call(rig.client.wallet.credit())

        assert rig.script.count == 2
        first, second = rig.bodies()
        assert first == second, "the same one document is sent again"
    assert credit.max == Money.usd("1.00")


@pytest.mark.parametrize(
    "missing", ["wallet_credit_max", "wallet_credit_used", "wallet_credit_available"]
)
def test_credit_with_a_missing_field_is_a_decode_error_naming_it(
    flavor: Flavor, missing: str
) -> None:
    figures = ap.credit()
    del figures[missing]
    with Rig(flavor, data(**figures)) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.wallet.credit())

    assert caught.value.path[0] == missing


def test_credit_with_a_malformed_amount_names_the_field_and_hides_the_value(
    flavor: Flavor,
) -> None:
    figures = ap.credit(used="1e3")
    with Rig(flavor, data(**figures)) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.wallet.credit())

    assert caught.value.path == ("wallet_credit_used", "value")
    assert "1e3" not in str(caught.value)


def test_credit_with_a_wrongly_typed_field_names_the_failing_part(flavor: Flavor) -> None:
    figures = ap.credit()
    figures["wallet_credit_max"] = {"currency": "USD", "value": 5}
    with Rig(flavor, data(**figures)) as rig, pytest.raises(DecodeError) as caught:
        rig.call(rig.client.wallet.credit())

    assert caught.value.path == ("wallet_credit_max", "value")


def test_credit_graphql_error_propagates_with_its_category(flavor: Flavor) -> None:
    answer = json_response(
        {"data": None, "errors": [{"message": "x", "extensions": {"category": "wallet.locked"}}]}
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.wallet.credit())

    assert caught.value.errors[0].category == "wallet.locked"
