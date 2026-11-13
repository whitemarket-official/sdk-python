"""The JSON codec of the transport: exact numbers in both directions (CLAUDE.md rule 3)."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

import pytest
from pydantic import BaseModel, ConfigDict, Field

from whitemarket._runtime.json_codec import decode, encode, to_plain
from whitemarket._runtime.unset import UNSET


class Color(Enum):
    RED = "RED"


class Range(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str | None = Field(default=None, serialization_alias="from")
    to: Decimal | None = None


# --- decode -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("95.130000000000000001", Decimal("95.130000000000000001")),
        ("1e3", Decimal("1E+3")),
        ("-0.0", Decimal("-0.0")),
        ("9223372036854775809", 9223372036854775809),
        ("18446744073709551617", 18446744073709551617),
        ("0.1", Decimal("0.1")),
    ],
)
def test_decode_keeps_fractions_as_decimal_and_integers_exact(text: str, expected: object) -> None:
    value = decode(text)

    assert value == expected
    assert type(value) is type(expected)


def test_decode_accepts_bytes_and_nested_values() -> None:
    assert decode(b'{"a": [1.5, {"b": 2}]}') == {"a": [Decimal("1.5"), {"b": 2}]}


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity", '{"a": NaN}'])
def test_decode_refuses_non_finite_constants(text: str) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        decode(text)


# --- to_plain ---------------------------------------------------------------------------------
def test_to_plain_dumps_models_by_alias_without_unset_fields() -> None:
    plain = to_plain({"r": Range(from_="1", to=Decimal("2.50"))})

    assert plain == {"r": {"from": "1", "to": Decimal("2.50")}}
    assert to_plain(Range(to=Decimal(1))) == {"to": Decimal(1)}, "unset fields are not sent"
    assert to_plain(Range(to=None)) == {"to": None}, "an explicit null is sent"


def test_to_plain_drops_unset_arguments_and_keeps_none() -> None:
    assert to_plain({"a": UNSET, "b": None, "c": 0, "d": False}) == {"b": None, "c": 0, "d": False}


def test_to_plain_converts_enums_datetimes_and_lists() -> None:
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    assert to_plain({"e": Color.RED, "t": when, "l": [Color.RED, (1, 2)]}) == {
        "e": "RED",
        "t": "2026-01-02T03:04:05+00:00",
        "l": ["RED", [1, 2]],
    }


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(datetime.fromisoformat("2026-01-02T03:04:05"), id="naive datetime"),
        pytest.param(
            [datetime.fromisoformat("2026-01-02T00:00:00")], id="naive datetime in a list"
        ),
    ],
)
def test_to_plain_refuses_a_naive_datetime(value: object) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        to_plain(value)


@pytest.mark.parametrize(
    ("value", "refused"),
    [
        pytest.param(Decimal("1E+1000"), False, id="exponent 1000 is the largest accepted"),
        pytest.param(Decimal("1E+1001"), True, id="exponent 1001"),
        pytest.param(Decimal("1E-1000"), False, id="exponent -1000 is the largest accepted"),
        pytest.param(Decimal("1E-1001"), True, id="exponent -1001"),
        pytest.param(Decimal("0E+1001"), True, id="zero with a huge exponent"),
        pytest.param(Decimal("1E+9999999"), True, id="would be a 10 MB literal"),
    ],
)
def test_a_decimal_with_a_huge_exponent_is_refused_not_expanded(
    value: Decimal, refused: bool
) -> None:
    if refused:
        with pytest.raises(ValueError, match="exponent"):
            encode(value)
    else:
        assert len(encode(value)) > 1000


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (1.5, TypeError),
        ({"a": [1.5]}, TypeError),
        (float("nan"), TypeError),
        (Decimal("NaN"), ValueError),
        (Decimal("-Infinity"), ValueError),
        ({1: "x"}, TypeError),
        (b"bytes", TypeError),
        (object(), TypeError),
    ],
    ids=[
        "float",
        "nested-float",
        "nan",
        "decimal-nan",
        "decimal-inf",
        "int-key",
        "bytes",
        "object",
    ],
)
def test_to_plain_refuses_what_has_no_exact_json_form(
    value: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        to_plain(value)


# --- encode -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("95.130000000000000001"), "95.130000000000000001"),
        (Decimal("1E+3"), "1000"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("-0.50"), "-0.50"),
        (Decimal(0), "0"),
        (2**63, "9223372036854775808"),
        (True, "true"),
        (None, "null"),
        ('é\n"', '"é\\n\\""'),
        ({"a": Decimal("1.10"), "b": [1, None]}, '{"a":1.10,"b":[1,null]}'),
    ],
    ids=[
        "fraction",
        "exponent",
        "small",
        "negative",
        "zero",
        "big-int",
        "bool",
        "none",
        "string",
        "nested",
    ],
)
def test_encode_writes_a_decimal_as_a_number_literal(value: object, text: str) -> None:
    assert encode(value) == text
    assert json.loads(encode(value), parse_float=Decimal) == json.loads(text, parse_float=Decimal)


@pytest.mark.parametrize(
    "value", [1.5, Decimal("NaN"), Decimal("Infinity"), {1: 2}, b"x", object()]
)
def test_encode_refuses_floats_non_finite_numbers_and_unknown_types(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        encode(value)


def test_a_decimal_round_trips_through_encode_and_decode() -> None:
    original = {"price": Decimal("0.1000000000000000055511151231257827021181583404541015625")}

    assert decode(encode(original)) == original
