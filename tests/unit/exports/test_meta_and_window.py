"""`parse_meta` and `ExportWindow` (SDK_SPEC 3.10)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from support.exports import fixture
from whitemarket.errors import DecodeError
from whitemarket.exports import ExportFormat, ExportKind, ExportMeta, ExportWindow
from whitemarket.exports.meta import parse_meta

META: dict[str, Any] = {
    "file": "730.json",
    "data_as_of": "2026-10-30T09:24:02+00:00",
    "generated_at": "2026-10-30T09:25:37+00:00",
    "items": 20970,
}


def body(**changes: Any) -> bytes:
    return json.dumps({**META, **changes}).encode()


def test_the_fixture_parses_into_aware_datetimes() -> None:
    meta = parse_meta(fixture("prices.meta.json"))

    assert meta == ExportMeta(
        file="730.json",
        data_as_of=datetime(2026, 10, 30, 9, 24, 2, tzinfo=UTC),
        generated_at=datetime(2026, 10, 30, 9, 25, 37, tzinfo=UTC),
        items=4,
    )
    assert meta.data_as_of.utcoffset() == timedelta(0)
    assert meta.generated_at - meta.data_as_of == timedelta(seconds=95)


def test_a_str_body_works_like_bytes() -> None:
    assert parse_meta(body().decode()) == parse_meta(body())


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        pytest.param("2026-10-30T09:24:02Z", datetime(2026, 10, 30, 9, 24, 2, tzinfo=UTC), id="Z"),
        pytest.param(
            "2026-10-30T11:24:02+02:00",
            datetime(2026, 10, 30, 9, 24, 2, tzinfo=UTC),
            id="an offset",
        ),
        pytest.param(
            "2026-10-30T09:24:02.250+00:00",
            datetime(2026, 10, 30, 9, 24, 2, 250000, tzinfo=UTC),
            id="fractional seconds",
        ),
        pytest.param(
            "2026-10-30T04:24:02-05:00",
            datetime(2026, 10, 30, 9, 24, 2, tzinfo=UTC),
            id="a minus offset",
        ),
    ],
)
def test_the_offset_forms_the_server_may_use(stamp: str, expected: datetime) -> None:
    meta = parse_meta(body(data_as_of=stamp))

    assert meta.data_as_of == expected
    assert meta.data_as_of.tzinfo is not None


@pytest.mark.parametrize(
    "stamp",
    [
        pytest.param("2026-10-30T09:24:02", id="no offset"),
        pytest.param("2026-10-30", id="a date only"),
        pytest.param("2026-10-30 09:24:02+00:00", id="a space instead of T"),
        pytest.param("2026-10-30t09:24:02z", id="lower case"),
        pytest.param("2026-13-30T09:24:02+00:00", id="month 13"),
        pytest.param("2026-10-30T25:24:02+00:00", id="hour 25"),
        pytest.param("2026-10-30T09:24:02+00:00\n", id="a trailing line feed"),
        pytest.param("2026-10-30T09:24:02+0000", id="an offset without a colon"),
        pytest.param("٢026-10-30T09:24:02+00:00", id="a non-ASCII digit"),
        pytest.param("", id="empty"),
        pytest.param(None, id="null"),
        pytest.param(1761816242, id="a number"),
    ],
)
@pytest.mark.parametrize("key", ["data_as_of", "generated_at"])
def test_a_bad_date_fails_at_its_key(stamp: Any, key: str) -> None:
    with pytest.raises(DecodeError) as error:
        parse_meta(body(**{key: stamp}))

    assert error.value.path == ("meta", key)


@pytest.mark.parametrize(
    "items",
    [
        pytest.param(-1, id="negative"),
        pytest.param(1.5, id="a fraction"),
        pytest.param(True, id="a bool"),
        pytest.param("4", id="a string"),
        pytest.param(None, id="null"),
    ],
)
def test_a_bad_item_count_fails_at_items(items: Any) -> None:
    with pytest.raises(DecodeError) as error:
        parse_meta(body(items=items))

    assert error.value.path == ("meta", "items")


@pytest.mark.parametrize("items", [0, 4_511_700, 2**63], ids=["zero", "millions", "beyond int64"])
def test_item_counts_are_exact_integers(items: int) -> None:
    assert parse_meta(body(items=items)).items == items


@pytest.mark.parametrize("key", ["file", "data_as_of", "generated_at", "items"])
def test_a_missing_key_fails_at_that_key(key: str) -> None:
    data = {k: v for k, v in META.items() if k != key}

    with pytest.raises(DecodeError) as error:
        parse_meta(json.dumps(data))

    assert error.value.path == ("meta", key)


@pytest.mark.parametrize(
    "text",
    ["", "{", "[1]", "null", '"x"', "1", "{}x", '{"file":"a"}{', "\xff", '{"a":' + "[" * 100_000],
    ids=[
        "empty",
        "cut",
        "a list",
        "null",
        "a string",
        "a number",
        "junk",
        "two objects",
        "bytes",
        "deep",
    ],
)
def test_a_body_that_is_not_the_expected_json_fails_at_meta(text: str) -> None:
    with pytest.raises(DecodeError) as error:
        parse_meta(text.encode("latin-1"))

    assert error.value.path == ("meta",)


def test_a_file_name_that_is_not_a_string_fails() -> None:
    with pytest.raises(DecodeError) as error:
        parse_meta(body(file=730))

    assert error.value.path == ("meta", "file")


def test_the_body_is_never_quoted_in_the_message() -> None:
    with pytest.raises(DecodeError) as error:
        parse_meta('{"file": "SECRET", "data_as_of": 5}')

    assert "SECRET" not in str(error.value)
    assert error.value.__context__ is None


def test_an_unknown_key_is_ignored() -> None:
    assert parse_meta(body(extra_key=1)).file == "730.json"


# --- the window --------------------------------------------------


@pytest.mark.parametrize(
    ("window", "suffix"),
    [
        pytest.param(ExportWindow.ALL, "", id="ALL"),
        pytest.param(ExportWindow.MINUTES10, ".10min", id="MINUTES10"),
        pytest.param(ExportWindow.HOUR1, ".1hour", id="HOUR1"),
        pytest.param(ExportWindow.HOURS12, ".12hours", id="HOURS12"),
        pytest.param(ExportWindow.HOURS24, ".24hours", id="HOURS24"),
    ],
)
def test_a_window_is_the_url_suffix_of_the_file_name(window: ExportWindow, suffix: str) -> None:
    assert window.suffix == suffix
    assert f"730{window.suffix}.json" == f"730{suffix}.json"


def test_the_windows_are_exactly_the_five_of_the_spec() -> None:
    assert [w.name for w in ExportWindow] == ["ALL", "MINUTES10", "HOUR1", "HOURS12", "HOURS24"]


def test_kinds_and_formats_are_the_url_parts() -> None:
    assert [k.value for k in ExportKind] == ["prices", "products"]
    assert [f.value for f in ExportFormat] == ["json", "csv"]
