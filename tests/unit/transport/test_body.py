"""BodyAccumulator: the size limit counts decompressed bytes and holds while streaming."""

import gzip
import tracemalloc
import zlib

import pytest

from whitemarket._runtime.body import BodyAccumulator, BodyError, BodyTooLargeError


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
