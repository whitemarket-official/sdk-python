"""`require_text` and `unset_if_none`: the argument checks every API module shares."""

import re
from typing import Any

import pytest

from whitemarket._runtime.text_args import require_text
from whitemarket._runtime.unset import UNSET, unset_if_none


@pytest.mark.parametrize(
    ("value", "options"),
    [
        pytest.param("abc", {}, id="plain text"),
        pytest.param("", {}, id="empty is fine unless asked otherwise"),
        pytest.param("a\nb", {}, id="a control character is fine unless asked otherwise"),
        pytest.param(" padded ", {"non_empty": True, "no_control": True}, id="spaces are text"),
        pytest.param("имя", {"non_empty": True, "no_control": True}, id="non-ASCII"),
    ],
)
def test_a_sendable_text_is_returned_unchanged(value: str, options: dict[str, bool]) -> None:
    assert require_text(value, "x", **options) == value


@pytest.mark.parametrize(
    ("value", "options", "message"),
    [
        pytest.param("a\ud800b", {}, "x must be valid Unicode text", id="lone surrogate"),
        pytest.param("", {"non_empty": True}, "x must not be empty", id="empty"),
        pytest.param("a\x00b", {"no_control": True}, "x must not contain control", id="NUL"),
        pytest.param("a\x7fb", {"no_control": True}, "x must not contain control", id="DEL"),
        pytest.param("a\x85b", {"no_control": True}, "x must not contain control", id="C1"),
    ],
)
def test_an_unsendable_text_is_a_value_error_that_does_not_show_the_text(
    value: str, options: dict[str, bool], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)) as caught:
        require_text(value, "x", **options)

    assert value not in str(caught.value) or value == ""
    assert caught.value.__context__ is None, "no context keeps the text"


@pytest.mark.parametrize("value", [None, 1, b"abc"])
def test_a_non_string_is_a_type_error(value: Any) -> None:
    with pytest.raises(TypeError, match="x must be a str"):
        require_text(value, "x")


@pytest.mark.parametrize("value", [0, "", False, 0.0])
def test_unset_if_none_keeps_every_falsy_value(value: Any) -> None:
    assert unset_if_none(value) is value


def test_unset_if_none_turns_none_into_unset() -> None:
    assert unset_if_none(None) is UNSET
