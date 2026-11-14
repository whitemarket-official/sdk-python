"""`wallet.transfer()` and `wallet.take_credit()`: money moves, so they are sent once and an
ambiguous failure is told apart from a rejection (SDK_SPEC 3.8 rules 2, 3, 5; CLAUDE.md rule 2).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
import pytest

from support import account_payloads as ap
from support.clients import Rig
from support.flavors import Flavor
from support.http import Reply, data, json_response, reply
from whitemarket import RetryPolicy
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    DecodeError,
    GraphQLError,
    MutationOutcomeUnknownError,
    RateLimitError,
    TransportError,
)
from whitemarket.models import Currency, Money

RECIPIENT = "synthetic-recipient-0042"
AMOUNT = Money(amount=Decimal("123.456789"), currency=Currency.USD)
LEAKS = ("123.456789", RECIPIENT)  # neither may appear in a message


def transfer_call(rig: Rig) -> Any:
    return rig.client.wallet.transfer(RECIPIENT, AMOUNT)


def take_credit_call(rig: Rig) -> Any:
    return rig.client.wallet.take_credit(AMOUNT)


@dataclass(frozen=True)
class Method:
    """One money mutation: how to call it, its root field and what its failure must say."""

    name: str
    call: Callable[[Rig], Any]
    field: str
    success: dict[str, Any]
    operation: str  # the SDK method the error names
    hint: str  # where the error says to check

    def __repr__(self) -> str:
        return self.name


TRANSFER = Method(
    "transfer",
    transfer_call,
    "wallet_transfer_send",
    ap.transfer(),
    "wallet.transfer",
    "wallet.transfers()",
)
TAKE_CREDIT = Method(
    "take_credit",
    take_credit_call,
    "wallet_credit_get",
    ap.debt(),
    "wallet.take_credit",
    "wallet.credit()",
)
METHODS = [TRANSFER, TAKE_CREDIT]


def graphql_failure(path: list[str] | None, partial: dict[str, Any] | None = None) -> Reply:
    error: dict[str, Any] = {"message": "boom", "extensions": {"category": "wallet.some"}}
    if path is not None:
        error["path"] = path
    return json_response({"data": partial, "errors": [error]})


def rejections(m: Method) -> list[tuple[str, Reply, type[Exception]]]:
    """Failures that prove the server did not run the mutation."""
    f = m.field
    return [
        ("HTTP 400", reply(400), BadRequestError),
        ("HTTP 401 after the one replay", reply(401), AuthenticationError),
        ("HTTP 429", reply(429), RateLimitError),
        ("GraphQL error of the root field", graphql_failure([f]), GraphQLError),
        ("GraphQL error without a path", graphql_failure(None), GraphQLError),
        ("root-path error with the field null", graphql_failure([f], {f: None}), GraphQLError),
    ]


def ambiguous(m: Method) -> list[tuple[str, Any]]:
    """Failures that do not tell whether the server ran the mutation."""
    f = m.field
    nested = {"message": "x", "path": [f, "person"]}
    return [
        ("HTTP 500", reply(500)),
        ("HTTP 502", reply(502)),
        ("HTTP 503", reply(503)),
        ("HTTP 503 + Retry-After", reply(503, headers={"Retry-After": "30"})),
        ("HTTP 504", reply(504)),
        ("timeout after the request", httpx.ReadTimeout("synthetic timeout")),
        ("connect error", httpx.ConnectError("synthetic connect")),
        ("unreadable body", reply(200, b"<html>not json</html>")),
        ("answer fails to decode", data(**{f: {**m.success, "createdAt": "not a date"}})),
        (
            "error on a nested path next to a result",
            json_response({"data": {f: m.success}, "errors": [nested]}),
        ),
        ("error on a nested path, data null", graphql_failure([f, "person"])),
        ("error on a foreign path", graphql_failure(["other"])),
        ("root error with a foreign data key", graphql_failure([f], {"other": 1})),
        ("root error next to a result", graphql_failure([f], {f: m.success})),
        (
            "malformed error entry",
            json_response({"data": None, "errors": [{"message": "x", "path": "wallet"}]}),
        ),
    ]


REJECTION_CASES = [
    pytest.param(m, outcome, expected, id=f"{m.name}: {label}")
    for m in METHODS
    for label, outcome, expected in rejections(m)
]
AMBIGUOUS_CASES = [
    pytest.param(m, outcome, id=f"{m.name}: {label}")
    for m in METHODS
    for label, outcome in ambiguous(m)
]


def test_success_is_sent_once_with_the_exact_variables(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_transfer_send=ap.transfer())) as rig:
        result = rig.call(transfer_call(rig))

        (body,) = rig.bodies()
    assert body["operationName"] == "WalletTransferSend"
    assert body["query"].lstrip().startswith("mutation WalletTransferSend")
    assert body["variables"] == {
        "amount": {"currency": "USD", "value": "123.456789"},
        "to": RECIPIENT,
    }
    assert (result.id, result.amount, result.from_.id, result.to.id) == (
        "tr-1",
        Money.usd("3.30"),
        "a",
        "b",
    )


def test_take_credit_success_maps_the_debt(flavor: Flavor) -> None:
    with Rig(flavor, data(wallet_credit_get=ap.debt())) as rig:
        debt = rig.call(take_credit_call(rig))

        (body,) = rig.bodies()
    assert body["operationName"] == "WalletCreditGet"
    assert body["query"].lstrip().startswith("mutation WalletCreditGet")
    assert body["variables"] == {"moneyInput": {"currency": "USD", "value": "123.456789"}}
    assert (debt.id, debt.amount) == ("debt-1", Money.usd("25.00"))
    assert debt.created_at.isoformat() == "2026-10-30T10:00:00+00:00"


@pytest.mark.parametrize(
    "to",
    [
        pytest.param("", id="empty"),
        pytest.param("a\nb", id="newline"),
        pytest.param("a\x00b", id="NUL"),
        pytest.param("a\x7fb", id="DEL"),
        pytest.param("a\x85b", id="C1 control"),
        pytest.param("a\ud800b", id="lone surrogate (not UTF-8)"),
    ],
)
def test_transfer_refuses_a_bad_recipient_before_sending(flavor: Flavor, to: str) -> None:
    with Rig(flavor, data(wallet_transfer_send=ap.transfer())) as rig:
        with pytest.raises(ValueError, match="recipient") as caught:
            rig.call(rig.client.wallet.transfer(to, AMOUNT))

        assert rig.script.count == 0
    assert to not in str(caught.value) or to == ""


@pytest.mark.parametrize(
    "to",
    [
        pytest.param("76561190000000001", id="Steam id"),
        pytest.param("0b6c1c0a-5a44-4e49-8f27-1f2d3c4b5a69", id="person id"),
        pytest.param(" padded ", id="spaces are not control characters, sent unchanged"),
        pytest.param("имя", id="non-ASCII"),
    ],
)
def test_transfer_sends_a_valid_recipient_unchanged(flavor: Flavor, to: str) -> None:
    with Rig(flavor, data(wallet_transfer_send=ap.transfer())) as rig:
        rig.call(rig.client.wallet.transfer(to, AMOUNT))

        assert rig.variables()[0]["to"] == to


@pytest.mark.parametrize("m", METHODS, ids=repr)
def test_an_unknown_currency_is_refused_before_sending(flavor: Flavor, m: Method) -> None:
    amount = Money(amount=Decimal("1"), currency=Currency("EUR"))
    sends = (
        (lambda rig: rig.client.wallet.transfer(RECIPIENT, amount))
        if m is TRANSFER
        else (lambda rig: rig.client.wallet.take_credit(amount))
    )
    with Rig(flavor, data()) as rig:
        with pytest.raises(ValueError, match="EUR"):
            rig.call(sends(rig))
        assert rig.script.count == 0


@pytest.mark.parametrize(("m", "outcome", "expected"), REJECTION_CASES)
def test_a_rejection_propagates_as_its_own_error(
    flavor: Flavor, m: Method, outcome: Reply, expected: type[Exception]
) -> None:
    with Rig(flavor, outcome, retry=RetryPolicy(max_attempts=3, base_delay=0)) as rig:
        with pytest.raises(expected) as caught:
            rig.call(m.call(rig))

        assert not isinstance(caught.value, MutationOutcomeUnknownError)
        assert rig.script.count <= 2, "at most the one 401 replay, never a retry"


@pytest.mark.parametrize(("m", "outcome"), AMBIGUOUS_CASES)
def test_any_other_failure_is_outcome_unknown_after_one_request(
    flavor: Flavor, m: Method, outcome: Any
) -> None:
    with Rig(flavor, outcome, retry=RetryPolicy(max_attempts=3, base_delay=0)) as rig:
        with pytest.raises(MutationOutcomeUnknownError) as caught:
            rig.call(m.call(rig))

        assert rig.script.count == 1, "a mutation is never retried"
    error = caught.value
    assert error.operation == m.operation
    assert str(error) == (
        f"{m.operation} may or may not have been executed; check {m.hint} before trying again"
    )
    assert error.__cause__ is not None, "the original failure is kept"
    for leak in LEAKS:
        assert leak not in str(error)
        assert leak not in repr(error)


def test_the_original_failure_is_the_cause(flavor: Flavor) -> None:
    with Rig(flavor, reply(500)) as rig, pytest.raises(MutationOutcomeUnknownError) as caught:
        rig.call(transfer_call(rig))

    assert type(caught.value.__cause__).__name__ == "ServerError"


def test_a_transport_failure_is_outcome_unknown_not_a_transport_error(flavor: Flavor) -> None:
    with (
        Rig(flavor, httpx.ReadTimeout("t")) as rig,
        pytest.raises(MutationOutcomeUnknownError) as caught,
    ):
        rig.call(take_credit_call(rig))

    assert isinstance(caught.value.__cause__, TransportError)


def test_a_decode_failure_after_a_200_is_outcome_unknown(flavor: Flavor) -> None:
    broken = ap.transfer(amount={"currency": "USD", "value": "1,5"})
    with (
        Rig(flavor, data(wallet_transfer_send=broken)) as rig,
        pytest.raises(MutationOutcomeUnknownError) as caught,
    ):
        rig.call(transfer_call(rig))

    assert isinstance(caught.value.__cause__, DecodeError)


def test_secrets_and_amounts_are_never_logged(
    flavor: Flavor, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        Rig(flavor, reply(500)) as rig,
        caplog.at_level(logging.DEBUG),
        pytest.raises(MutationOutcomeUnknownError),
    ):
        rig.call(transfer_call(rig))

    for leak in LEAKS:
        assert leak not in caplog.text
