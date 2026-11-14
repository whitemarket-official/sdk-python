"""`is_batch_rejection`, `GraphQLError.data_present`, `BatchIncompleteError` (SDK_SPEC 3.5)."""

from typing import Any

import pytest

from whitemarket._runtime.json_codec import RequestNotSentError
from whitemarket._runtime.rejection import is_batch_rejection
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    BatchIncompleteError,
    DecodeError,
    GraphQLError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.selling import BatchItemResult, BatchOutcome


def failure(errors: list[Any], data: dict[str, Any] | None = None, **kw: Any) -> GraphQLError:
    return GraphQLError.from_payload(errors, data, **kw)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(BadRequestError(), True, id="400"),
        pytest.param(AuthenticationError(), True, id="401 after the replay"),
        pytest.param(RateLimitError(), True, id="429"),
        pytest.param(RequestNotSentError("x"), True, id="request not encodable, nothing sent"),
        pytest.param(ValueError("x"), False, id="any other ValueError"),
        pytest.param(ServerError(), False, id="500"),
        pytest.param(ServiceUnavailableError(), False, id="503"),
        pytest.param(HttpError(418), False, id="unexpected status"),
        pytest.param(TransportError("x"), False, id="transport"),
        pytest.param(DecodeError("x"), False, id="decode"),
        pytest.param(RuntimeError("x"), False, id="unexpected exception"),
        pytest.param(failure([{"message": "m"}], data_present=False), True, id="request error"),
        pytest.param(
            failure([{"message": "m"}, {"message": "n"}], data_present=False),
            True,
            id="two request errors",
        ),
        pytest.param(failure([{"message": "m"}], data_present=True), False, id="data: null"),
        pytest.param(failure([{"message": "m"}], {}), False, id="empty data"),
        pytest.param(
            failure([{"message": "m", "path": ["f"]}], data_present=False),
            False,
            id="root path, no data key",
        ),
        pytest.param(
            failure([{"message": "m"}, {"message": "n", "path": ["f"]}], data_present=False),
            False,
            id="one error with a path",
        ),
        pytest.param(
            failure([{"message": "m", "path": "f"}], data_present=False),
            False,
            id="malformed path",
        ),
        pytest.param(GraphQLError([], data_present=False), False, id="no errors at all"),
    ],
)
def test_a_batch_failure_is_a_rejection_only_for_a_request_error(
    error: BaseException, expected: bool
) -> None:
    assert is_batch_rejection(error) is expected


def test_data_present_is_open_by_default_and_follows_a_non_null_data() -> None:
    assert GraphQLError([]).data_present is False
    assert GraphQLError([], {"f": None}).data_present is True
    assert GraphQLError([], None, data_present=True).data_present is True
    assert failure([{"message": "m"}], None, data_present=True).data_present is True


def test_the_incomplete_error_counts_the_outcomes_and_keeps_the_results() -> None:
    outcomes = [
        BatchOutcome.SUCCEEDED,
        BatchOutcome.SUCCEEDED,
        BatchOutcome.FAILED,
        BatchOutcome.UNKNOWN,
        BatchOutcome.NOT_SENT,
    ]
    results = [BatchItemResult(index=i, outcome=o) for i, o in enumerate(outcomes)]

    error = BatchIncompleteError(results)

    assert str(error) == "batch incomplete: 2 succeeded, 1 failed, 1 unknown, 1 not sent"
    assert error.results == tuple(results)
