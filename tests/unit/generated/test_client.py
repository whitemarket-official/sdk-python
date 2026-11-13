"""The generated client on a fake executor (plan T1.4): connection query, mutation, raw call.

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

import inspect
from decimal import Decimal

import pytest

from support.executors import Harness
from support.payloads import market_list_payload
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._generated.input_types import ForwardPaginationInput, MarketProductSearchInput
from whitemarket._generated.sync_client import GeneratedClient
from whitemarket._runtime.json_codec import encode

KINDS = pytest.mark.parametrize("kind", ["async", "sync"])
FADE = Decimal("95.130000000000000001")  # not representable as a binary float


@KINDS
def test_connection_query_runs_as_a_query_with_exact_variables(kind: str) -> None:
    harness = Harness(kind, market_list_payload([]))

    result = harness.call(
        "market_list",
        search=MarketProductSearchInput(csgo_fade_from=FADE, name_strict=True),
        forward_pagination=ForwardPaginationInput(first=2),
    )

    (call,) = harness.calls
    assert (call.operation_name, call.operation_type) == ("MarketList", "query")
    assert call.document.strip().startswith("query MarketList(")
    assert call.variables == {
        "search": {"csgoFadeFrom": FADE, "nameStrict": True},
        "forwardPagination": {"first": 2},
    }
    # The transport writes the Decimal as a JSON number literal: the digits survive.
    assert '"csgoFadeFrom":95.130000000000000001' in encode(call.variables)
    assert result.market_list.total_count == 0
    assert result.market_list.page_info.has_next_page is False


@KINDS
def test_an_argument_that_was_not_passed_is_left_out_of_the_variables(kind: str) -> None:
    harness = Harness(kind, market_list_payload([]))

    harness.call("market_list")
    harness.call("market_list", search=None)

    assert [dict(c.variables) for c in harness.calls] == [{}, {"search": None}]


@KINDS
def test_mutation_runs_as_a_mutation(kind: str) -> None:
    harness = Harness(kind, {"market_lifetime_all": True})

    result = harness.call("market_lifetime_all", value=600)

    (call,) = harness.calls
    assert (call.operation_name, call.operation_type) == ("MarketLifetimeAll", "mutation")
    assert call.variables == {"value": 600}
    assert result.market_lifetime_all is True


@KINDS
def test_a_raw_document_without_a_declared_type_takes_it_from_the_document(kind: str) -> None:
    # Only a document that is clearly a query is retried (CLAUDE.md rule 2; PHP RawDocument).
    harness = Harness(kind, {"test_ping": "pong"})

    data = harness.call("execute", "query Ping { test_ping }", {"n": Decimal("1.50")}, "Ping")
    harness.call("execute", "mutation M { market_lifetime_all(value: 600) }")

    first, second = harness.calls
    assert data == {"test_ping": "pong"}
    assert (first.operation_name, first.operation_type) == ("Ping", "query")
    assert second.operation_type == "mutation"
    call = first
    assert call.variables == {"n": Decimal("1.50")}


@KINDS
def test_a_raw_document_can_declare_itself_a_query(kind: str) -> None:
    harness = Harness(kind, {"test_ping": "pong"})

    harness.call("execute", "query Ping { test_ping }", operation_type="query")

    assert harness.calls[0].operation_type == "query"
    assert harness.calls[0].operation_name is None
    assert harness.calls[0].variables == {}


@KINDS
@pytest.mark.parametrize(
    "bad",
    [1.5, float("nan"), Decimal("NaN"), Decimal("Infinity"), {"nested": [1.5]}],
    ids=["float", "nan", "decimal-nan", "decimal-inf", "nested-float"],
)
def test_a_raw_document_refuses_a_float_or_a_non_finite_number(kind: str, bad: object) -> None:
    harness = Harness(kind, {})

    with pytest.raises((TypeError, ValueError)):
        harness.call("execute", "mutation M { x }", {"v": bad})

    assert harness.calls == [], "nothing is sent"


def test_the_sync_client_has_the_async_clients_methods() -> None:
    def public(cls: type) -> dict[str, bool]:
        return {
            name: inspect.iscoroutinefunction(member)
            for name, member in inspect.getmembers(cls, inspect.isfunction)
            if not name.startswith("_")
        }

    async_methods, sync_methods = public(AsyncGeneratedClient), public(GeneratedClient)
    assert set(async_methods) == set(sync_methods)
    assert len(sync_methods) >= 69, "one method per operation"
    assert all(async_methods[n] for n in async_methods if n != "get_data")
    assert not any(sync_methods.values())
