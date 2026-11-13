"""BodyAccumulator: the size limit counts decompressed bytes and holds while streaming."""

import gzip
import tracemalloc
import zlib

import pytest

from whitemarket._runtime.body import (
    BodyAccumulator,
    BodyError,
    BodyTooLargeError,
    announced_length,
    body_is_gzip,
)


def _feed_in_pieces(accumulator: BodyAccumulator, data: bytes, size: int) -> bytes:
    for start in range(0, len(data), size):
        accumulator.feed(data[start : start + size])
        if accumulator.done:
            break
    return accumulator.finish()


@pytest.mark.parametrize(
    ("size", "ok"),
    [(99, True), (100, True), (101, False)],
    ids=["below the limit", "at the limit", "one byte over"],
)
def test_the_identity_limit_boundary(size: int, ok: bool) -> None:
    accumulator = BodyAccumulator(limit=100, gzip=False)

    if ok:
        assert _feed_in_pieces(accumulator, b"x" * size, 7) == b"x" * size
    else:
        with pytest.raises(BodyTooLargeError):
            _feed_in_pieces(accumulator, b"x" * size, 7)


def test_a_gzip_body_is_decoded_in_any_chunking() -> None:
    payload = b'{"data":{"k":"' + b"v" * 5000 + b'"}}'

    body = _feed_in_pieces(BodyAccumulator(limit=10_000, gzip=True), gzip.compress(payload), 13)

    assert body == payload


def test_the_limit_counts_decompressed_bytes_not_compressed_ones() -> None:
    bomb = gzip.compress(b"\0" * 1_000_000)
    assert len(bomb) < 2000

    with pytest.raises(BodyTooLargeError):
        _feed_in_pieces(BodyAccumulator(limit=100_000, gzip=True), bomb, 64)


def test_a_bomb_is_cut_without_inflating_it_whole() -> None:
    bomb = gzip.compress(b"\0" * 50_000_000)
    accumulator = BodyAccumulator(limit=1000, gzip=True)
    tracemalloc.start()
    try:
        with pytest.raises(BodyTooLargeError):
            accumulator.feed(bomb)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 5_000_000, "the 50 MB body was never inflated in one step"

    assert sum(map(len, accumulator._parts)) <= 1000


@pytest.mark.parametrize(
    ("chunks", "message"),
    [
        pytest.param([gzip.compress(b"hello")[:-6]], "end marker", id="truncated"),
        pytest.param([b"not gzip at all"], "corrupt", id="garbage"),
        pytest.param([], "end marker", id="empty"),
    ],
)
def test_a_broken_gzip_body_is_an_error(chunks: list[bytes], message: str) -> None:
    accumulator = BodyAccumulator(limit=1000, gzip=True)

    def read_all() -> None:
        for chunk in chunks:
            accumulator.feed(chunk)
        accumulator.finish()

    with pytest.raises(BodyError, match=message):
        read_all()


def test_bytes_after_the_gzip_member_are_ignored() -> None:
    accumulator = BodyAccumulator(limit=1000, gzip=True)

    accumulator.feed(gzip.compress(b"abc") + b"trailing")
    accumulator.feed(b"more")

    assert accumulator.finish() == b"abc"


def test_an_error_body_is_cut_at_the_limit_and_keeps_what_decoded_before_a_failure() -> None:
    cut = BodyAccumulator(limit=10, gzip=False, truncate=True)
    cut.feed(b"0123456789abcdef")
    assert (cut.done, cut.finish()) == (True, b"0123456789")

    broken = BodyAccumulator(limit=100, gzip=True, truncate=True)
    packed = zlib.compressobj(wbits=31)
    broken.feed(packed.compress(b"partial answer") + packed.flush(zlib.Z_SYNC_FLUSH))
    broken.feed(b"\xff\xff\xff\xff")
    assert broken.finish() == b"partial answer"


# --- strict, unbounded and streamed bodies (the export reader) -------------------------------

PAYLOAD = b'["' + b"v" * 3000 + b'"]'


def _decoded(accumulator: BodyAccumulator, raw: bytes, size: int) -> bytes:
    out = b""
    for start in range(0, len(raw), size):
        out += b"".join(accumulator.decode(raw[start : start + size]))
    accumulator.finish()
    return out


def _decoded_all(accumulator: BodyAccumulator, chunks: list[bytes]) -> None:
    for chunk in chunks:
        b"".join(accumulator.decode(chunk))


def _feed_all(accumulator: BodyAccumulator, chunks: list[bytes]) -> None:
    for chunk in chunks:
        accumulator.feed(chunk)
    accumulator.finish()


@pytest.mark.parametrize("size", [1, 7, 256, 100_000])
def test_decode_yields_the_body_without_keeping_it(size: int) -> None:
    accumulator = BodyAccumulator(limit=None, gzip=True, strict=True)

    assert _decoded(accumulator, gzip.compress(PAYLOAD), size) == PAYLOAD
    assert accumulator.finish() == b""  # nothing is kept by decode


def test_a_limit_of_none_reads_a_body_of_any_size() -> None:
    accumulator = BodyAccumulator(limit=None, gzip=True, strict=True)
    raw = gzip.compress(b"x" * 5_000_000)

    assert len(_decoded(accumulator, raw, 4096)) == 5_000_000


def test_one_decode_step_is_bounded_whatever_a_chunk_expands_to() -> None:
    accumulator = BodyAccumulator(limit=None, gzip=True, strict=True)
    bomb = gzip.compress(b"\x00" * 50_000_000)  # a few tens of KiB compressed

    sizes = [len(piece) for piece in accumulator.decode(bomb)]

    assert max(sizes) <= 1024 * 1024
    assert sum(sizes) == 50_000_000


@pytest.mark.parametrize(
    "tail",
    [pytest.param(b"x", id="one byte"), pytest.param(gzip.compress(b"more"), id="a member")],
)
@pytest.mark.parametrize("together", [True, False], ids=["same chunk", "next chunk"])
def test_strict_rejects_data_after_the_gzip_end(tail: bytes, together: bool) -> None:
    accumulator = BodyAccumulator(limit=None, gzip=True, strict=True)
    raw = gzip.compress(PAYLOAD)

    chunks = [raw + tail] if together else [raw, tail]

    with pytest.raises(BodyError, match="after the end of the gzip stream"):
        _decoded_all(accumulator, chunks)


def test_not_strict_ignores_data_after_the_gzip_end() -> None:
    accumulator = BodyAccumulator(limit=1000, gzip=True)

    body = _feed_in_pieces(accumulator, gzip.compress(b"abc") + b"trailing", 5)

    assert body == b"abc"


@pytest.mark.parametrize(
    ("expected", "problem"),
    [(None, None), (5, None), (6, "shorter"), (4, "longer")],
)
def test_the_raw_byte_count_must_match_the_announced_length(
    expected: int | None, problem: str | None
) -> None:
    accumulator = BodyAccumulator(limit=100, gzip=False, expected_raw_bytes=expected)

    if problem is None:
        accumulator.feed(b"ab")
        accumulator.feed(b"cde")
        assert accumulator.finish() == b"abcde"
        return
    with pytest.raises(BodyError, match=problem):
        _feed_all(accumulator, [b"ab", b"cde"])


def test_the_length_of_a_gzip_body_counts_the_compressed_bytes() -> None:
    raw = gzip.compress(PAYLOAD)
    accumulator = BodyAccumulator(limit=None, gzip=True, strict=True, expected_raw_bytes=len(raw))

    assert _decoded(accumulator, raw, 50) == PAYLOAD


@pytest.mark.parametrize(
    ("header", "length"),
    [
        (None, None),
        ("0", 0),
        ("1000", 1000),
        (" 1000 ", 1000),
        ("1000, 1000", 1000),
        ("1000,1000,1000", 1000),
        ("9" * 18, int("9" * 18)),
    ],
)
def test_announced_length_accepts_one_plain_number(header: str | None, length: int | None) -> None:
    assert announced_length(header) == length


@pytest.mark.parametrize(
    "header",
    ["+1000", "-1", "1000, 999", "abc", "", "1e3", "0x10", "1 000", "9" * 19, "1000;", "١٢٣"],
)
def test_announced_length_refuses_anything_else(header: str) -> None:
    with pytest.raises(BodyError, match="invalid Content-Length"):
        announced_length(header)


@pytest.mark.parametrize(
    ("encoding", "gzipped"),
    [(None, False), ("", False), ("identity", False), (" GZIP ", True), ("x-gzip", True)],
)
def test_body_is_gzip(encoding: str | None, gzipped: bool) -> None:
    assert body_is_gzip(encoding) is gzipped


@pytest.mark.parametrize("encoding", ["br", "deflate", "gzip, identity", "compress"])
def test_body_is_gzip_refuses_other_encodings(encoding: str) -> None:
    with pytest.raises(BodyError, match="unsupported content encoding"):
        body_is_gzip(encoding)
