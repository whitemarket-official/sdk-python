"""`map_list` and `optional_secret`: the shared pieces of the model mappers."""

import pytest

from whitemarket._mappers.common import Path, map_list, optional_secret
from whitemarket.errors import DecodeError


def _positive(value: int, path: Path) -> int:
    if value < 0:
        raise DecodeError("negative", path)
    return value * 10


def test_every_row_is_mapped_in_order() -> None:
    assert map_list([1, 2, 3], _positive, ("rows",)) == [10, 20, 30]


def test_an_empty_answer_is_an_empty_list() -> None:
    assert map_list([], _positive, ("rows",)) == []


def test_a_failing_row_is_reported_at_its_own_index() -> None:
    with pytest.raises(DecodeError) as caught:
        map_list([1, 2, -3], _positive, ("rows",))

    assert caught.value.path == ("rows", 2)


@pytest.mark.parametrize("value", [None, ""])
def test_a_null_or_empty_value_is_no_secret(value: str | None) -> None:
    assert optional_secret(value) is None


def test_a_value_becomes_a_secret_that_hides_it() -> None:
    secret = optional_secret("tok-123")

    assert secret is not None
    assert secret.reveal() == "tok-123"
    assert "tok-123" not in repr(secret)
