"""`is_mutation_rejection`, `GraphQLErrorEntry.malformed`, the purchase error (SDK_SPEC 3.3)."""

from typing import Any

import pytest

from whitemarket._runtime.rejection import is_mutation_rejection
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    DecodeError,
    GraphQLError,
    GraphQLErrorEntry,
    HttpError,
    PurchaseOutcomeUnknownError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)


def failure(errors: list[Any], data: dict[str, Any] | None = None) -> GraphQLError:
    return GraphQLError.from_payload(errors, data)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(BadRequestError(), True, id="400"),
        pytest.param(AuthenticationError(), True, id="401 after the replay"),
        pytest.param(RateLimitError(), True, id="429"),
        pytest.param(ServerError(), False, id="500"),
        pytest.param(ServiceUnavailableError(), False, id="503"),
        pytest.param(HttpError(418), False, id="unexpected status"),
        pytest.param(TransportError("x"), False, id="transport"),
        pytest.param(DecodeError("x"), False, id="decode"),
        pytest.param(RuntimeError("x"), False, id="unexpected exception"),
        pytest.param(failure([{"message": "m"}]), True, id="pathless error, no data"),
        pytest.param(
            failure([{"message": "m", "path": ["f"]}], {"f": None}), True, id="root error"
        ),
        pytest.param(
            failure([{"message": "m", "path": ["f", "x"]}], {"f": None}), False, id="nested"
        ),
        pytest.param(failure([{"message": "m"}], {}), False, id="empty data"),
        pytest.param(failure([{"message": "m"}], {"f": {"id": 1}}), False, id="result in data"),
        pytest.param(failure([{"message": "m", "path": ["g"]}]), False, id="other root field"),
        pytest.param(failure([{"message": "m", "path": "f"}]), False, id="malformed path"),
        pytest.param(GraphQLError([]), False, id="no errors at all"),
    ],
)
def test_a_failure_is_a_rejection_only_when_the_mutation_cannot_have_run(
    error: BaseException, expected: bool
) -> None:
    assert is_mutation_rejection(error, "f") is expected


@pytest.mark.parametrize(
    ("raw", "malformed"),
    [
        pytest.param({"message": "m"}, False, id="minimal"),
        pytest.param({"message": "m", "path": None}, False, id="null path"),
        pytest.param({"message": "m", "path": ["a", 0]}, False, id="path of strings and ints"),
        pytest.param({"message": "m", "extensions": None}, False, id="null extensions"),
        pytest.param({"message": "m", "path": [None]}, True, id="null segment"),
        pytest.param({"message": "m", "path": [1.5]}, True, id="float segment"),
        pytest.param({"message": "m", "path": [True]}, True, id="bool segment"),
        pytest.param({"message": "m", "path": "a.b"}, True, id="string path"),
        pytest.param({"message": "m", "path": {"a": 1}}, True, id="object path"),
        pytest.param({"message": 5}, True, id="message not a string"),
        pytest.param({}, True, id="no message"),
        pytest.param("boom", True, id="not an object"),
        pytest.param({"message": "m", "extensions": "x"}, True, id="extensions not an object"),
    ],
)
def test_an_error_entry_is_malformed_when_it_is_not_shaped_like_the_graphql_spec(
    raw: Any, malformed: bool
) -> None:
    assert GraphQLErrorEntry.from_payload(raw).malformed is malformed


def test_the_purchase_error_carries_the_custom_id_and_the_last_lookup_error() -> None:
    lookup = TransportError("x")

    error = PurchaseOutcomeUnknownError("order-1", lookup)

    assert (error.custom_id, error.last_lookup_error) == ("order-1", lookup)
    assert PurchaseOutcomeUnknownError("order-1").last_lookup_error is None
