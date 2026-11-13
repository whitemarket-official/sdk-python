"""The GraphQL executor over a scripted transport: request body and answer mapping."""

import json
from decimal import Decimal
from typing import Any

import pytest

from support.flavors import FLAVORS, Flavor
from support.http import Script, data, json_response, reply
from support.rigs import Stack, body_of
from whitemarket.errors import DecodeError, GraphQLError, NotFoundError

ACCESS = "static.access.token"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames:
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)


@pytest.fixture
def make(flavor: Flavor) -> Any:
    stacks: list[Stack] = []

    def build(*outcomes: Any) -> tuple[Stack, Script]:
        script = Script(*outcomes)
        stack = Stack(flavor, script, credential="static", token=ACCESS)
        stacks.append(stack)
        return stack, script

    yield build
    for stack in stacks:
        stack.close()


def run(
    stack: Stack, document: str = "query Q { a }", name: str | None = "Q", **variables: Any
) -> Any:
    return stack.run(stack.executor.execute(document, name, variables, "query"))


def test_the_request_body_and_the_bearer_header(make: Any) -> None:
    stack, script = make(data(a=1))

    result = run(stack, "query Q($n: Int) { a }", "Q", n=5)

    (request,) = script.requests
    assert result == {"a": 1}
    assert body_of(request) == {
        "query": "query Q($n: Int) { a }",
        "operationName": "Q",
        "variables": {"n": 5},
    }
    assert request.headers["authorization"] == f"Bearer {ACCESS}"
    assert "x-partner-token" not in request.headers


def test_no_operation_name_is_sent_when_there_is_none(make: Any) -> None:
    stack, script = make(data(a=1))

    run(stack, "{ a }", None)

    assert body_of(script.requests[0]) == {"query": "{ a }", "variables": {}}


def test_money_is_sent_as_an_exact_number_and_text_stays_utf8(make: Any) -> None:
    stack, script = make(data(a=1))

    run(stack, price=Decimal("0.020"), title="café \U0001f600")

    raw = script.requests[0].content
    assert b'"price":0.020' in raw, "an exact decimal literal, never a binary float"
    assert "café \U0001f600".encode() in raw
    assert json.loads(raw)["variables"]["title"] == "café \U0001f600"


def test_text_that_is_not_unicode_is_refused_without_echoing_it(make: Any) -> None:
    stack, script = make(data(a=1))

    with pytest.raises(ValueError, match="not valid Unicode") as caught:
        run(stack, note="TOP-SECRET-\ud800")

    assert "TOP-SECRET" not in str(caught.value)
    assert caught.value.__context__ is None
    assert script.count == 0


def test_a_float_variable_is_refused(make: Any) -> None:
    stack, script = make(data(a=1))

    with pytest.raises(TypeError, match="Decimal"):
        run(stack, price=1.5)

    assert script.count == 0


def test_a_fraction_in_the_answer_is_an_exact_decimal(make: Any) -> None:
    stack, _ = make(reply(200, b'{"data":{"fade":97.123456789012345678}}'))

    assert run(stack) == {"fade": Decimal("97.123456789012345678")}


def test_errors_raise_a_graphql_error_with_the_partial_data_and_the_category(make: Any) -> None:
    errors = [{"message": "Oops", "path": ["a"], "extensions": {"category": "x.denied"}}]
    stack, _ = make(json_response({"data": {"b": 2}, "errors": errors}))

    with pytest.raises(GraphQLError) as caught:
        run(stack)

    assert type(caught.value) is GraphQLError
    assert caught.value.partial_data == {"b": 2}
    assert caught.value.errors[0].category == "x.denied"
    assert caught.value.has_category("x.denied")


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        pytest.param(["market.product.not_found"], NotFoundError, id="not found"),
        pytest.param(
            ["market.product.not_found_in_specified_price"], GraphQLError, id="in specified price"
        ),
        pytest.param(["a.not_found", "b.other"], GraphQLError, id="mixed"),
        pytest.param(["a.not_found", "b.not_found"], NotFoundError, id="all not found"),
    ],
)
def test_not_found_is_decided_by_the_category_never_the_message(
    make: Any, categories: list[str], expected: type[GraphQLError]
) -> None:
    errors = [{"message": "Item not found.", "extensions": {"category": c}} for c in categories]
    stack, script = make(json_response({"errors": errors}))

    with pytest.raises(GraphQLError) as caught:
        run(stack)

    assert type(caught.value) is expected
    assert script.count == 1, "a GraphQL error is never retried"


def test_a_not_found_message_without_a_category_is_a_plain_graphql_error(make: Any) -> None:
    stack, _ = make(json_response({"errors": [{"message": "Oops! Item not found."}]}))

    with pytest.raises(GraphQLError) as caught:
        run(stack)

    assert type(caught.value) is GraphQLError


@pytest.mark.parametrize(
    ("answer", "path"),
    [
        pytest.param(b"not json {", (), id="not JSON"),
        pytest.param(b"", (), id="empty body"),
        pytest.param(b"[1]", (), id="a list"),
        pytest.param(b'"text"', (), id="a string"),
        pytest.param(b'{"data":[1]}', ("data",), id="data is a list"),
        pytest.param(b'{"data":"x"}', ("data",), id="data is a string"),
        pytest.param(b'{"data":{},"errors":{"a":1}}', ("errors",), id="errors is an object"),
        pytest.param(b"{}", ("data",), id="neither data nor errors"),
        pytest.param(b'{"data":null}', ("data",), id="null data without errors"),
        pytest.param(b"[" * 200_000, (), id="nested too deep"),
        pytest.param(b'{"data":{"a":NaN}}', (), id="NaN"),
    ],
)
def test_an_unexpected_shape_is_a_decode_error_that_does_not_echo_the_body(
    make: Any, answer: bytes, path: tuple[str, ...]
) -> None:
    stack, _ = make(reply(200, answer))

    with pytest.raises(DecodeError) as caught:
        run(stack)

    assert caught.value.path == path
    assert caught.value.__context__ is None


def test_a_decode_error_never_holds_the_response(make: Any) -> None:
    stack, _ = make(reply(200, b'{"data":"SECRET-RESPONSE-VALUE"}'))

    with pytest.raises(DecodeError) as caught:
        run(stack)

    assert "SECRET-RESPONSE-VALUE" not in str(caught.value)
