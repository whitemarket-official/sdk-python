"""CSV streaming of rows (SDK_SPEC 3.10 rule 11)."""

from collections.abc import Iterable
from typing import Any

import pytest

from support.exports import CHUNK_SIZES, Watched, chunked, fixture
from whitemarket.errors import DecodeError
from whitemarket.exports._csv_rows import CsvRecordReader
from whitemarket.exports._limits import MAX_ROW_BYTES, PUSH_STEP

AB = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def read(body: bytes, size: int = 1 << 30) -> list[dict[str, str | None]]:
    rows, error = read_until_failure(chunked(body, size))
    assert error is None
    return rows


def read_until_failure(
    chunks: Iterable[bytes],
) -> tuple[list[dict[str, str | None]], DecodeError | None]:
    reader = CsvRecordReader("products")
    rows: list[dict[str, str | None]] = []
    try:
        for chunk in chunks:
            rows.extend(reader.feed(chunk))
        rows.extend(reader.finish())
    except DecodeError as error:
        return rows, error
    return rows, None


@pytest.mark.parametrize("size", CHUNK_SIZES)
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(b"a,b\n1,2\n3,4\n", AB, id="LF"),
        pytest.param(b"a,b\r\n1,2\r\n3,4\r\n", AB, id="CRLF"),
        pytest.param(b"a,b\n1,2\n3,4", AB, id="no final line end"),
        pytest.param(b"a,b\r\n1,2\r\n3,4", AB, id="CRLF and no final line end"),
        pytest.param(
            b"a,b,c\n,2,\n1,,3\n",
            [{"a": None, "b": "2", "c": None}, {"a": "1", "b": None, "c": "3"}],
            id="empty values are null",
        ),
        pytest.param(b'a,b\n"",2\n', [{"a": None, "b": "2"}], id="a quoted empty value is null"),
        pytest.param(
            b'a,b\n"x\n,""y""",z\n',
            [{"a": 'x\n,"y"', "b": "z"}],
            id="a quoted newline, comma and doubled quotes",
        ),
        pytest.param(
            b'a,b\r\n"x\r\ny",z\r\n', [{"a": "x\r\ny", "b": "z"}], id="a CRLF inside quotes is kept"
        ),
        pytest.param(b"\na,b\n\n1,2\n\r\n3,4\n\n", AB, id="empty lines are skipped"),
        pytest.param(b"\xef\xbb\xbfa,b\n1,2\n3,4\n", AB, id="a BOM before the header"),
        pytest.param(b"a,b\n", [], id="a header only"),
        pytest.param(b"a,b", [], id="a header only, no line end"),
        pytest.param(
            "a,b\n\u0421\u0442\u0438\u043a\u0435\u0440 \u2605,2\n".encode(),
            [{"a": "\u0421\u0442\u0438\u043a\u0435\u0440 \u2605", "b": "2"}],
            id="multibyte text split between chunks",
        ),
        pytest.param(b"a\n1\n2\n", [{"a": "1"}, {"a": "2"}], id="a single column"),
        pytest.param(b'a,b\n1,"2"\n', [{"a": "1", "b": "2"}], id="a quoted last field"),
        pytest.param(b'a,b\n"1",2\r\n', [{"a": "1", "b": "2"}], id="a quoted first field"),
    ],
)
def test_records_come_out_whatever_the_chunking(
    body: bytes, expected: list[dict[str, str | None]], size: int
) -> None:
    assert read(body, size) == expected


def test_a_bom_only_at_the_start_is_stripped() -> None:
    assert read(b"a\n\xef\xbb\xbfx\n") == [{"a": "﻿x"}]


def test_the_columns_are_matched_by_name_not_position() -> None:
    assert read(b"b,a\n2,1\n") == [{"b": "2", "a": "1"}]


@pytest.mark.parametrize(
    ("body", "path"),
    [
        pytest.param(b"", ("products",), id="an empty body: no header"),
        pytest.param(b"\n\r\n\n", ("products",), id="only empty lines: no header"),
        pytest.param(b"\xef\xbb\xbf", ("products",), id="only a BOM: no header"),
        pytest.param(b"a,,b\n1,2,3\n", ("products",), id="an empty column name"),
        pytest.param(b"a,b,\n1,2,3\n", ("products",), id="an empty last column name"),
        pytest.param(b"a,b,a\n1,2,3\n", ("products",), id="a repeated column name"),
        pytest.param(b'"a,b', ("products",), id="a header that is an unterminated quote"),
        pytest.param(b"a,b\n1\n", ("products", 0), id="the first row with fewer fields"),
        pytest.param(b"a,b\n1,2\n3,4,5\n", ("products", 1), id="the second row with more fields"),
        pytest.param(
            b"a,b\n1,2\n3,4\n5,6\n7\n8,9\n", ("products", 3), id="the fourth row is short"
        ),
        pytest.param(b'a,b\n1,"2\n', ("products", 0), id="ends inside a quoted field"),
        pytest.param(
            b'a,b\n1,2\n3,4\n5,"6\n', ("products", 2), id="ends inside a quote, third row"
        ),
        pytest.param(b'a\n"', ("products", 0), id="ends right after an opening quote"),
        pytest.param(b'a\n"x"y\n', ("products", 0), id="text after a closing quote"),
        pytest.param(b"a\n\xff\n", ("products", 0), id="invalid UTF-8"),
        pytest.param(b"a\n1\n\xe2\x98", ("products", 1), id="UTF-8 cut short at the end"),
        pytest.param(b"a\n\n\n1\n\n2\n3,4\n", ("products", 2), id="empty lines do not count"),
    ],
)
@pytest.mark.parametrize("size", [1, 3, 1 << 30], ids=lambda s: f"chunks of {s}")
def test_a_broken_body_fails_at_its_path(
    body: bytes, path: tuple[str | int, ...], size: int
) -> None:
    rows, error = read_until_failure(chunked(body, size))

    assert error is not None
    assert error.path == path
    assert error.__cause__ is None
    assert error.__context__ is None
    assert len(rows) == (path[1] if len(path) == 2 else 0)  # the rows before it came out first


def test_a_failure_does_not_quote_the_body() -> None:
    _, error = read_until_failure([b'a\n"SECRET"x\n'])

    assert error is not None
    assert "SECRET" not in str(error)


def test_the_header_of_the_fixture_names_the_json_keys() -> None:
    rows = read(fixture("products.csv"), 4096)

    assert len(rows) == 4
    assert rows[1]["inspectLink"] is None  # a quoted empty string
    assert rows[1]["product_paint_index"] is None
    assert rows[2]["product_category"] is None
    assert rows[3]["name_hash"] == "\u2605 Synthetic Knife | Doppler (Factory New)"


# --- the record cap ----------------------------------------------------------


def record_of(size_bytes: int, char: str = "x") -> bytes:
    """A one-field record of exactly `size_bytes` bytes of UTF-8."""
    width = len(char.encode())
    assert size_bytes % width == 0
    return (char * (size_bytes // width)).encode()


@pytest.mark.parametrize(
    ("char", "length", "passes"),
    [
        pytest.param("x", MAX_ROW_BYTES, True, id="128 KiB of ASCII"),
        pytest.param("x", MAX_ROW_BYTES + 1, False, id="128 KiB + 1 of ASCII"),
        pytest.param("\u044f", MAX_ROW_BYTES, True, id="128 KiB of two-byte characters"),
        pytest.param(
            "я", MAX_ROW_BYTES + 2, False, id="128 KiB + 2 bytes: fewer characters than bytes"
        ),
        pytest.param(
            "★", MAX_ROW_BYTES - MAX_ROW_BYTES % 3, True, id="three-byte characters under the cap"
        ),
        pytest.param(
            "★", MAX_ROW_BYTES - MAX_ROW_BYTES % 3 + 3, False, id="three-byte, over the cap"
        ),
    ],
)
@pytest.mark.parametrize(
    "ending",
    [b"\n", b"\r\n", b""],
    ids=["LF", "CRLF", "no line end"],
)
@pytest.mark.parametrize("size", [100, PUSH_STEP, 1 << 30], ids=lambda s: f"chunks of {s}")
def test_a_record_is_capped_at_128_kib_of_utf8(
    char: str, length: int, passes: bool, ending: bytes, size: int
) -> None:
    body = b"a\n1\n2\n" + record_of(length, char) + ending + (b"3\n" if ending else b"")

    rows, error = read_until_failure(chunked(body, size))

    if passes:
        assert error is None
        assert len(rows) == (4 if ending else 3)
        assert rows[2]["a"] == record_of(length, char).decode()
    else:
        assert error is not None
        assert error.path == ("products", 2)
        assert len(rows) == 2


@pytest.mark.parametrize(
    ("body", "path"),
    [
        pytest.param(record_of(MAX_ROW_BYTES + 1) + b"\n1\n", ("products",), id="the header"),
        pytest.param(record_of(MAX_ROW_BYTES + 1), ("products",), id="the header, no line end"),
        pytest.param(
            b'a\n1\n"' + record_of(MAX_ROW_BYTES + 1), ("products", 1), id="an open quote"
        ),
        pytest.param(
            b'a\n1\n"' + (b"line\n" * 40_000), ("products", 1), id="a quoted field over many lines"
        ),
    ],
)
def test_the_cap_applies_to_the_header_and_to_unterminated_quotes(
    body: bytes, path: tuple[str | int, ...]
) -> None:
    _, error = read_until_failure(chunked(body, 4000))

    assert error is not None
    assert error.path == path


def test_a_hostile_record_is_refused_before_the_body_is_read_to_its_end() -> None:
    source = Watched(b"a\n" + b"x" * (50 * MAX_ROW_BYTES), 10_000)

    rows, error = read_until_failure(source)

    assert rows == []
    assert error is not None
    assert error.path == ("products", 0)
    assert source.pulled <= MAX_ROW_BYTES + 3 * PUSH_STEP + 10_000


def test_a_record_may_be_empty_columns_only() -> None:
    assert read(b"a,b\n,\n") == [{"a": None, "b": None}]


def test_the_reader_is_unusable_after_a_failure() -> None:
    reader = CsvRecordReader("products")
    with pytest.raises(DecodeError):
        list(reader.feed(b"a,a\n"))

    assert list(reader.feed(b"1\n")) == []
    assert list(reader.finish()) == []


def test_close_is_idempotent_and_stops_the_reader() -> None:
    reader = CsvRecordReader("prices")
    reader.close()
    reader.close()

    assert list(reader.feed(b"a\n1\n")) == []


def test_the_root_names_the_path() -> None:
    reader = CsvRecordReader("prices")

    with pytest.raises(DecodeError) as error:
        list(reader.finish())

    assert error.value.path == ("prices",)


def test_a_row_value_type_is_str_or_none() -> None:
    values: list[Any] = [v for row in read(b"a,b\n1,\n") for v in row.values()]

    assert values == ["1", None]
