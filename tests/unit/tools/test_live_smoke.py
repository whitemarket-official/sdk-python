"""tools/live_smoke: read-only guard, query catalog, PASS rule and report (SDK_SPEC 6.4).

No network: the smoke's generated client runs on a recording executor that refuses every call.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from live_smoke import catalog, classify, env, report
from live_smoke.guard import ReadOnlyExecutor, ReadOnlyViolationError

from whitemarket._generated.sync_client import GeneratedClient
from whitemarket.errors import (
    GraphQLError,
    NotFoundError,
    TransportError,
)

OPERATIONS = Path(__file__).resolve().parents[3] / "graphql" / "operations"
OPERATION_NAME = re.compile(r"^(query|mutation)\s+(\w+)", re.MULTILINE)
LEAKY_TEXT = "SECRET-MESSAGE-do-not-print"


class StopCallError(Exception):
    """Raised by the recording executor after it noted the call."""


class RecordingExecutor:
    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str | None, Mapping[str, object], str]] = []

    def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: str,
    ) -> dict[str, Any]:
        self.calls.append((document, operation_name, variables, operation_type))
        if self.answer is None:
            raise StopCallError
        return self.answer


def operations(kind: str) -> dict[str, str]:
    """Operation name -> document of every `graphql/operations/<kind>/*.graphql`."""
    found: dict[str, str] = {}
    for path in sorted((OPERATIONS / kind).glob("*.graphql")):
        text = path.read_text(encoding="utf-8")
        match = OPERATION_NAME.search(text)
        assert match is not None, path.name
        found[match.group(2)] = text
    return found


def entry(category: str | None) -> dict[str, Any]:
    error: dict[str, Any] = {"message": LEAKY_TEXT}
    if category is not None:
        error["extensions"] = {"category": category}
    return error


@pytest.mark.parametrize("name", sorted(operations("mutation")))
def test_every_generated_mutation_is_refused_before_it_is_sent(name: str) -> None:
    inner = RecordingExecutor({})

    with pytest.raises(ReadOnlyViolationError):
        ReadOnlyExecutor(inner).execute(operations("mutation")[name], name, {}, "mutation")

    assert inner.calls == []


@pytest.mark.parametrize(
    ("document", "declared"),
    [
        pytest.param("mutation X { a }", "query", id="mutation document declared as query"),
        pytest.param("query X { a }", "mutation", id="query document declared as mutation"),
        pytest.param("{ a }", "query", id="shorthand is not a `query` document"),
        pytest.param("fragment F on T { a } query X { ...F }", "query", id="fragment first"),
        pytest.param("# query\nmutation X { a }", "query", id="comment before a mutation"),
    ],
)
def test_the_guard_needs_both_the_declared_type_and_the_document(
    document: str, declared: Any
) -> None:
    inner = RecordingExecutor({})

    with pytest.raises(ReadOnlyViolationError):
        ReadOnlyExecutor(inner).execute(document, "X", {}, declared)

    assert inner.calls == []


def test_the_violation_message_does_not_echo_an_odd_operation_name() -> None:
    with pytest.raises(ReadOnlyViolationError) as raised:
        ReadOnlyExecutor(RecordingExecutor({})).execute(
            "mutation X { a }", "a\nb c", {}, "mutation"
        )

    assert str(raised.value) == "the live smoke refuses to run a?b?c: it is not a query"


def test_a_query_passes_through_unchanged() -> None:
    inner = RecordingExecutor({"a": 1})

    data = ReadOnlyExecutor(inner).execute("  query X {\n a }", "X", {"v": 1}, "query")

    assert data == {"a": 1}
    assert inner.calls == [("  query X {\n a }", "X", {"v": 1}, "query")]


def run_catalog_step(key: str) -> RecordingExecutor:
    inner = RecordingExecutor()
    step = catalog.steps(GeneratedClient(ReadOnlyExecutor(inner)))[key]
    with pytest.raises(StopCallError):
        step()
    return inner


def test_the_catalog_covers_exactly_the_generated_queries() -> None:
    generated = set(operations("query"))

    assert set(catalog.steps(GeneratedClient(RecordingExecutor()))) == generated, (
        "add the new query to tools/live_smoke/catalog.py"
    )


@pytest.mark.parametrize("key", sorted(operations("query")))
def test_each_catalog_step_runs_exactly_its_own_query(key: str) -> None:
    inner = run_catalog_step(key)

    ((document, name, _variables, operation_type),) = inner.calls
    assert (name, operation_type) == (key, "query")
    assert document.lstrip().startswith("query ")


def test_the_specified_calls_use_the_specified_variables() -> None:
    assert run_catalog_step("MarketList").calls[0][2] == {"forwardPagination": {"first": 1}}
    assert run_catalog_step("DealBuyerStatuses").calls[0][2] == {"ids": ["non-existent"]}
    trade = run_catalog_step("MarketTradeUrl").calls[0][2]
    assert trade == {"link": {"value": catalog.SYNTHETIC_TRADE_URL}}
    assert "/tradeoffer/new/" in catalog.SYNTHETIC_TRADE_URL
    uuid_variable = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    )
    for key, variable in [
        ("DealItem", "id"),
        ("DealHistoryItem", "id"),
        ("MarketItem", "idOrSlug"),
    ]:
        assert uuid_variable.fullmatch(str(run_catalog_step(key).calls[0][2][variable]))


@pytest.mark.parametrize(
    ("errors", "status"),
    [
        pytest.param([entry("market.product.not_found")], report.Status.PASSED, id="not found"),
        pytest.param([entry("deal.invalid")], report.Status.PASSED, id="business category"),
        pytest.param(
            [entry("deal.invalid"), entry("x.y")], report.Status.PASSED, id="two business"
        ),
        pytest.param([entry(None)], report.Status.FAILED, id="uncategorized"),
        pytest.param([entry("")], report.Status.FAILED, id="empty category"),
        pytest.param([entry("auth.token.expired")], report.Status.FAILED, id="auth"),
        pytest.param([entry("AUTH.token")], report.Status.FAILED, id="auth upper case"),
        pytest.param([entry("internal.error")], report.Status.FAILED, id="internal"),
        pytest.param([entry("server.down")], report.Status.FAILED, id="server"),
        pytest.param([entry("deal.invalid"), entry("auth.x")], report.Status.FAILED, id="one bad"),
        pytest.param(
            [entry("deal.invalid"), entry(None)], report.Status.FAILED, id="one uncategorized"
        ),
    ],
)
def test_the_pass_rule_for_categorized_graphql_errors(
    errors: list[dict[str, Any]], status: report.Status
) -> None:
    result = classify.classify("query X", GraphQLError.from_payload(errors), 7)

    assert (result.status, result.milliseconds) == (status, 7)


def test_not_found_is_a_reachable_graphql_error() -> None:
    error = GraphQLError.from_payload([entry("market.product.not_found")])

    assert isinstance(error, NotFoundError)


def test_a_non_graphql_error_fails_with_its_class_only() -> None:
    result = classify.classify("query X", TransportError(LEAKY_TEXT), 3)

    assert result == report.StepResult("query X", report.Status.FAILED, 3, "TransportError", "")


def test_the_report_holds_no_message_text() -> None:
    failing = classify.classify(
        "query A", GraphQLError.from_payload([entry("auth.token.expired")]), 5
    )
    unsafe = classify.classify(
        "query B", GraphQLError.from_payload([entry(f"auth {LEAKY_TEXT}\n| y")]), 6
    )
    reachable = classify.classify("query C", GraphQLError.from_payload([entry("deal.invalid")]), 1)
    transport = classify.classify("query D", TransportError(LEAKY_TEXT), 2)

    text = report.render([failing, unsafe, reachable, transport])

    assert LEAKY_TEXT not in text
    assert "(invalid)" in text
    assert "| query A | FAIL | 5 | GraphQLError | auth.token.expired |" in text
    assert "PASS 1, FAIL 3" in text


def test_the_exit_code_is_one_only_when_a_step_failed() -> None:
    ok = report.StepResult("a", report.Status.PASSED, 1)
    bad = report.StepResult("b", report.Status.FAILED, 1)

    assert (report.exit_code([ok]), report.exit_code([ok, bad])) == (0, 1)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        pytest.param("WHITEMARKET_PARTNER_TOKEN=abc\n", "abc", id="plain"),
        pytest.param("export WHITEMARKET_PARTNER_TOKEN='a b'\n", "a b", id="export, single quotes"),
        pytest.param('WHITEMARKET_PARTNER_TOKEN="a#b"\n', "a#b", id="double quotes keep #"),
        pytest.param(
            "# c\n\nOTHER=1\nWHITEMARKET_PARTNER_TOKEN=abc # note\n", "abc", id="comments"
        ),
        pytest.param("OTHER=1\n", None, id="absent"),
        pytest.param("WHITEMARKET_PARTNER_TOKEN_X=abc\n", None, id="prefix of another key"),
    ],
)
def test_dotenv_value(text: str, value: str | None) -> None:
    assert env.dotenv_value(text, "WHITEMARKET_PARTNER_TOKEN") == value
