"""JSON streaming of rows (SDK_SPEC 3.10 rules 10 and 12), every ijson backend, many chunkings."""

import sys
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import pytest

from support.exports import BACKENDS, CHUNK_SIZES, Watched, chunked
from whitemarket.errors import DecodeError
from whitemarket.exports._json_rows import JsonArrayReader, is_too_deep
from whitemarket.exports._limits import MAX_ROW_BYTES, MAX_ROW_DEPTH, PUSH_STEP

pytestmark = pytest.mark.parametrize("backend", BACKENDS)


def read(body: bytes, backend: str, size: int = 1 << 30) -> list[Any]:
    reader = JsonArrayReader("products", backend=backend)
    rows: list[Any] = []
    for chunk in chunked(body, size):
        rows.extend(reader.feed(chunk))
    rows.extend(reader.finish())
    return rows


def read_until_failure(
    chunks: Iterable[bytes], backend: str
) -> tuple[list[Any], DecodeError | None]:
    """The rows delivered before the failure, and the failure."""
    reader = JsonArrayReader("products", backend=backend)
    rows: list[Any] = []
    try:
        for chunk in chunks:
            rows.extend(reader.feed(chunk))
        rows.extend(reader.finish())
    except DecodeError as error:
        return rows, error
    return rows, None


def row_of_size(size: int) -> bytes:
    """A JSON object of exactly `size` bytes of text."""
    frame = b'{"a":""}'
    return b'{"a":"' + b"x" * (size - len(frame)) + b'"}'


@pytest.mark.parametrize("size", CHUNK_SIZES)
def test_rows_come_out_whatever_the_chunking(backend: str, size: int) -> None:
    body = b' \n[ {"a":1} ,\n{"b":[1,2,{"c":null}]},"x",true, 7 ]\n '

    assert read(body, backend, size) == [{"a": 1}, {"b": [1, 2, {"c": None}]}, "x", True, 7]


@pytest.mark.parametrize(
    "body", [b"[]", b" [ ] \n"], ids=["empty array", "empty array with spaces"]
)
def test_an_empty_array_has_no_rows(backend: str, body: bytes) -> None:
    assert read(body, backend) == []


def test_numbers_are_never_binary_floats(backend: str) -> None:
    rows = read(
        b'[{"big":9007199254740993,"huge":123456789012345678901234567890,"f":1.50,"e":1e3}]',
        backend,
    )

    row = rows[0]
    assert row["big"] == 9007199254740993  # 2**53 + 1
    assert row["huge"] == 123456789012345678901234567890  # beyond 64 bits, still exact
    assert row["f"] == Decimal("1.50")
    assert isinstance(row["f"], Decimal)
    assert isinstance(row["e"], Decimal)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b'{"a":1}', id="an object"),
        pytest.param(b"1", id="a number"),
        pytest.param(b'"text"', id="a string"),
        pytest.param(b"null", id="null"),
        pytest.param(b"", id="an empty body"),
        pytest.param(b" \n\t ", id="only white space"),
        pytest.param(b"\xef\xbb\xbf[]", id="a BOM before the array"),
    ],
)
def test_a_body_that_is_not_an_array_fails_at_the_root(backend: str, body: bytes) -> None:
    rows, error = read_until_failure(chunked(body, 3), backend)

    assert rows == []
    assert error is not None
    assert error.path == ("products",)


@pytest.mark.parametrize(
    ("body", "good", "path_index"),
    [
        pytest.param(b'[{"a":1},{"a":SECRET}]', 1, 1, id="a syntax error in the second row"),
        pytest.param(b'[{"a":1},{"a":2},{"a":3,,}]', 2, 2, id="a syntax error in the third row"),
        pytest.param(b'[SECRET,{"a":1}]', 0, 0, id="a syntax error in the first row"),
        pytest.param(b'[{"a":1},{"a":', 1, 1, id="cut short inside the second row"),
        pytest.param(b'[{"a":1},{"a":2}', 2, 2, id="cut short after the last row"),
        pytest.param(b'[{"a":1},', 1, 1, id="cut short after a comma"),
        pytest.param(b"[", 0, 0, id="cut short after the bracket"),
        pytest.param(b'[{"a":1}] SECRET', 1, 1, id="data after the end"),
        pytest.param(b'[{"a":1}][{"a":2}]', 1, 1, id="a second array after the end"),
        pytest.param(b'[{"a":1}}', 1, 1, id="a wrong closing bracket"),
    ],
)
@pytest.mark.parametrize("size", [3, 1 << 30], ids=["3 byte chunks", "one chunk"])
def test_a_broken_body_fails_at_the_row_being_read_after_the_rows_before_it(
    backend: str, body: bytes, good: int, path_index: int, size: int
) -> None:
    rows, error = read_until_failure(chunked(body, size), backend)

    assert len(rows) == good
    assert error is not None
    assert error.path == ("products", path_index)
    assert "SECRET" not in str(error)
    assert "SECRET" not in repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None  # the parser's message quotes the input


@pytest.mark.parametrize(
    ("size", "passes"),
    [
        pytest.param(MAX_ROW_BYTES - 1, True, id="128 KiB - 1"),
        pytest.param(MAX_ROW_BYTES, True, id="128 KiB"),
        pytest.param(MAX_ROW_BYTES + 4 * PUSH_STEP, False, id="128 KiB + 4 steps"),
        pytest.param(MAX_ROW_BYTES * 4, False, id="512 KiB"),
    ],
)
@pytest.mark.parametrize(
    "chunk", [1000, PUSH_STEP, 1 << 30], ids=["1000 B", "one step", "one chunk"]
)
def test_the_row_cap_is_128_kib_with_a_small_read_ahead(
    backend: str, size: int, passes: bool, chunk: int
) -> None:
    body = b'[{"a":1},' + row_of_size(size) + b',{"b":2}]'

    rows, error = read_until_failure(chunked(body, chunk), backend)

    if passes:
        assert error is None
        assert len(rows) == 3
        assert rows[2] == {"b": 2}
    else:
        assert error is not None
        assert error.path == ("products", 1)
        assert rows == [{"a": 1}]


def test_a_hostile_row_is_refused_before_the_body_is_read_to_its_end(backend: str) -> None:
    prefix = b'[{"a":"'
    source = Watched(prefix + b"x" * (50 * MAX_ROW_BYTES), 10_000)

    rows, error = read_until_failure(source, backend)

    assert rows == []
    assert error is not None
    assert error.path == ("products", 0)
    assert source.pulled <= MAX_ROW_BYTES + 3 * PUSH_STEP + 2 * 10_000


@pytest.mark.parametrize(
    ("levels", "passes"),
    [
        pytest.param(1, True, id="a flat row"),
        pytest.param(MAX_ROW_DEPTH, True, id="511 levels"),
        pytest.param(MAX_ROW_DEPTH + 1, False, id="512 levels"),
        pytest.param(5000, False, id="5000 levels"),
    ],
)
def test_a_row_nested_deeper_than_511_levels_is_refused(
    backend: str, levels: int, passes: bool
) -> None:
    # the row object is level 1, so it holds `levels - 1` arrays around the number
    row = (
        b'{"a":' + b"[" * (levels - 1) + b"1" + b"]" * (levels - 1) + b"}"
        if levels > 1
        else b'{"a":1}'
    )
    body = b'[{"ok":1},' + row + b",{}]"

    rows, error = read_until_failure(chunked(body, 500), backend)

    if passes:
        assert error is None
        assert len(rows) == 3
    else:
        assert error is not None
        assert error.path == ("products", 1)
        assert rows == [{"ok": 1}]


def test_a_text_that_is_not_utf8_fails_at_its_row(backend: str) -> None:
    rows, error = read_until_failure(chunked(b'[{"a":1},{"a":"\xff\xfe"}]', 5), backend)

    assert rows == [{"a": 1}]
    assert error is not None
    assert error.path == ("products", 1)


def test_the_reader_is_unusable_after_a_failure(backend: str) -> None:
    reader = JsonArrayReader("products", backend=backend)
    with pytest.raises(DecodeError):
        list(reader.feed(b"[1,@]"))

    assert list(reader.feed(b"[2]")) == []
    assert list(reader.finish()) == []


def test_the_root_names_the_path(backend: str) -> None:
    reader = JsonArrayReader("prices", backend=backend)

    with pytest.raises(DecodeError) as error:
        list(reader.feed(b"{}"))

    assert error.value.path == ("prices",)


LIMIT_DIGITS = sys.get_int_max_str_digits()


@pytest.mark.skipif(LIMIT_DIGITS == 0, reason="the interpreter has no integer digit limit")
@pytest.mark.parametrize(
    ("digits", "passes"),
    [
        pytest.param(LIMIT_DIGITS - 1, True, id="limit - 1 digits"),
        pytest.param(LIMIT_DIGITS, True, id="limit digits"),
        pytest.param(LIMIT_DIGITS + 1, False, id="limit + 1 digits"),
        pytest.param(5 * LIMIT_DIGITS, False, id="five times the limit"),
    ],
)
@pytest.mark.parametrize("chunk", [1, 7, 1000, PUSH_STEP, 1 << 30], ids=lambda c: f"chunks of {c}")
def test_an_integer_with_too_many_digits_is_refused_not_a_crash(
    backend: str, digits: int, passes: bool, chunk: int
) -> None:
    # ijson 3.6.0 (yajl2_c) segfaults on such an integer; the refusal is the guard against it
    body = b'[{"a":1},{"n":' + b"9" * digits + b'},{"b":2}]'

    rows, error = read_until_failure(chunked(body, chunk), backend)

    if passes:
        assert error is None
        assert rows[1]["n"] == int("9" * digits)
        assert rows[2] == {"b": 2}
    else:
        assert error is not None
        assert error.path == ("products", 1)
        assert rows == [{"a": 1}]


@pytest.mark.skipif(LIMIT_DIGITS == 0, reason="the interpreter has no integer digit limit")
def test_digit_runs_are_counted_across_the_whole_run_not_per_piece(backend: str) -> None:
    half = b"1" * (LIMIT_DIGITS // 2 + 1)
    body = b'[{"a":"' + half + b"x" + half + b'"}]'  # two runs, each under the limit

    rows, error = read_until_failure(chunked(body, PUSH_STEP), backend)

    assert error is None
    assert len(rows) == 1


@pytest.mark.parametrize("token", [b"1e99999999999999999999", b"-1E-99999999999999999999"])
def test_an_exponent_the_decimal_type_cannot_hold_is_a_decode_error(
    backend: str, token: bytes
) -> None:
    rows, error = read_until_failure(chunked(b'[{"a":1},{"n":' + token + b"}]", 5), backend)

    assert error is not None
    assert error.path == ("products", 1)
    assert rows == [{"a": 1}]


def test_closing_a_reader_in_the_middle_of_a_document_is_quiet(backend: str) -> None:
    reader = JsonArrayReader("products", backend=backend)
    assert list(reader.feed(b'[{"a":1},{"a":')) == [{"a": 1}]

    reader.close()
    reader.close()

    assert list(reader.feed(b"2}]")) == []


@pytest.mark.parametrize(
    ("levels", "deep"),
    [
        pytest.param(1, False, id="flat"),
        pytest.param(MAX_ROW_DEPTH, False, id="511"),
        pytest.param(MAX_ROW_DEPTH + 1, True, id="512"),
        pytest.param(200_000, True, id="200000, built without recursion"),
    ],
)
def test_is_too_deep_counts_containers_without_recursion(
    backend: str, levels: int, deep: bool
) -> None:
    row: Any = 1
    for _ in range(levels - 1):
        row = [row]
    row = {"a": row}

    assert is_too_deep(row) is deep
    del row  # tear a deep structure down at the end of the test, not at interpreter exit
