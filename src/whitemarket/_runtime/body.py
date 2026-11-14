"""Bounded reading of a response body: the size limit counts DECOMPRESSED bytes (SDK_SPEC 1.3).

Pure state machine, no IO: the transport feeds it the raw (still compressed) chunks as they
arrive and stops at the first problem, so a gzip bomb is cut at the limit and never held whole.
The transport asks for `Accept-Encoding: gzip` only and decodes it here instead of letting httpx
do it, because httpx decompresses a whole network chunk in one step (no output bound).
"""

import re
import zlib
from collections.abc import Iterator
from typing import Final

# The most one decompression step may produce; keeps a step small however the limit is set.
_STEP_BYTES: Final = 1024 * 1024
_SLICE_BYTES: Final = 256  # compressed bytes handed to zlib at once
_GZIP_WINDOW: Final = 16 + zlib.MAX_WBITS


BodyBytes = bytes | bytearray  # a finished body: the buffer itself, so a large body is held once


def body_pieces(body: BodyBytes, size: int = _STEP_BYTES) -> Iterator[bytes]:
    """The body as `bytes` pieces of at most `size`, copied one at a time (never the whole)."""
    with memoryview(body) as view:
        for start in range(0, len(view), size):
            yield bytes(view[start : start + size])


class BodyError(Exception):
    """A body that cannot be used. The message names the problem, never the content."""


_TRAILING: Final = "the response body has data after the end of the gzip stream"


class BodyTooLargeError(BodyError):
    """The decompressed body is longer than the limit."""


def body_is_gzip(content_encoding: str | None) -> bool:
    """Whether a `Content-Encoding` is gzip; anything but identity or gzip raises `BodyError`."""
    encoding = (content_encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return False
    if encoding in ("gzip", "x-gzip"):
        return True
    raise BodyError("the response has an unsupported content encoding")


_CONTENT_LENGTH: Final = re.compile(r"[0-9]{1,18}", re.ASCII)


def announced_length(header: str | None) -> int | None:
    """The `Content-Length` a response announces; `None` when the header is absent (no check).

    One value, or several identical ones (RFC 9110 8.6), give that number. Anything else (`+1000`,
    `1000, 999`, letters, an empty value) raises `BodyError`: the length cannot be trusted, so the
    body cannot be checked against it.
    """
    if header is None:
        return None
    values = {part.strip() for part in header.split(",")}
    if len(values) != 1:
        raise BodyError("the response has an invalid Content-Length")
    (value,) = values
    if _CONTENT_LENGTH.fullmatch(value) is None:
        raise BodyError("the response has an invalid Content-Length")
    return int(value)


class BodyAccumulator:
    """Decodes a body, counting DECOMPRESSED bytes against `limit` (`None`: no limit).

    `truncate=False` (a success body): more than `limit` bytes raise `BodyTooLargeError`, and a
    gzip body that ends before its end marker raises `BodyError`. `truncate=True` (an error body,
    kept only as a diagnostic excerpt): the body is cut at `limit` and whatever decoded before a
    failure is kept.

    `strict=True` is for a body that must be complete (exports): data after the end of the gzip
    stream is an error instead of being ignored, and `expected_raw_bytes` (the announced
    `Content-Length`, counted on the raw bytes) must match exactly.

    `feed` keeps the decoded bytes for `finish`; `decode` hands them to the caller and keeps none
    (a streamed body).
    """

    def __init__(
        self,
        *,
        limit: int | None,
        gzip: bool,
        truncate: bool = False,
        strict: bool = False,
        expected_raw_bytes: int | None = None,
    ) -> None:
        self._limit = limit
        self._truncate = truncate
        self._strict = strict
        self._expected = expected_raw_bytes
        self._raw = 0
        self._inflater = zlib.decompressobj(_GZIP_WINDOW) if gzip else None
        self._body = bytearray()
        self._size = 0
        self._done = False
        self._failed = False

    @property
    def done(self) -> bool:
        """True when no further chunk is wanted (the gzip member ended or the cut was made)."""
        return self._done

    def feed(self, chunk: bytes) -> None:
        """Take a raw chunk and keep its decoded bytes (`finish` returns them all)."""
        for piece in self.decode(chunk):
            self._body += piece

    def decode(self, chunk: bytes) -> Iterator[bytes]:
        """Take a raw chunk; yield its decoded bytes, one bounded step at a time.

        The generator must be consumed: the chunk is processed as it runs. A step is at most about
        1 MiB, whatever the chunk decompresses to.
        """
        self._count_raw(len(chunk))
        if self._done:
            if self._strict and chunk:
                raise BodyError(_TRAILING)
            return
        if self._inflater is None:
            yield from self._append(chunk)
            return
        yield from self._inflate(chunk)

    def finish(self) -> BodyBytes:
        """The kept body; a gzip stream that stopped early or a short body is an error.

        It is the buffer itself, not a copy: a large body is never held twice.

        (Unless truncating, where the body is a diagnostic excerpt and whatever arrived is it.)
        """
        if not self._truncate:
            if self._inflater is not None and not self._inflater.eof and not self._done:
                raise BodyError("the gzip body ends before its end marker")
            if self._expected is not None and self._raw < self._expected:
                raise BodyError("the response body is shorter than Content-Length")
        return self._body

    def _count_raw(self, size: int) -> None:
        self._raw += size
        if self._expected is not None and self._raw > self._expected:
            raise BodyError("the response body is longer than Content-Length")

    def _step_room(self) -> int:
        if self._limit is None:
            return _STEP_BYTES
        return min(self._limit - self._size + 1, _STEP_BYTES)

    def _inflate(self, chunk: bytes) -> Iterator[bytes]:
        inflater = self._inflater
        if inflater is None:
            return
        pending = chunk
        while pending and not self._done:
            # Small slices: zlib returns no output of a call that fails, so a slice bounds what
            # an error body loses of its decoded start.
            piece, pending = pending[:_SLICE_BYTES], pending[_SLICE_BYTES:]
            while piece and not self._done:
                try:
                    out = inflater.decompress(piece, self._step_room())
                except zlib.error:
                    if self._truncate:
                        self._done = True
                        return
                    raise BodyError("the gzip body is corrupt") from None
                yield from self._append(out)
                if inflater.eof:
                    self._done = True  # a member ended: bytes after it are not part of the body
                    if self._strict and (inflater.unused_data or pending):
                        raise BodyError(_TRAILING)
                    return
                piece = inflater.unconsumed_tail

    def _append(self, data: bytes) -> Iterator[bytes]:
        if self._limit is not None:
            room = self._limit - self._size
            if len(data) > room:
                if not self._truncate:
                    raise BodyTooLargeError(f"the response body is longer than {self._limit} bytes")
                data = data[:room]
                self._done = True
        self._size += len(data)
        if data:
            yield data
        if self._limit is not None and self._size >= self._limit and self._truncate:
            self._done = True
