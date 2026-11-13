"""Bounded reading of a response body: the size limit counts DECOMPRESSED bytes (SDK_SPEC 1.3).

Pure state machine, no IO: the transport feeds it the raw (still compressed) chunks as they
arrive and stops at the first problem, so a gzip bomb is cut at the limit and never held whole.
The transport asks for `Accept-Encoding: gzip` only and decodes it here instead of letting httpx
do it, because httpx decompresses a whole network chunk in one step (no output bound).
"""

import zlib
from typing import Final

# The most one decompression step may produce; keeps a step small however the limit is set.
_STEP_BYTES: Final = 1024 * 1024
_SLICE_BYTES: Final = 256  # compressed bytes handed to zlib at once
_GZIP_WINDOW: Final = 16 + zlib.MAX_WBITS


class BodyError(Exception):
    """A body that cannot be used. The message names the problem, never the content."""


class BodyTooLargeError(BodyError):
    """The decompressed body is longer than the limit."""


class BodyAccumulator:
    """Collects a body up to `limit` decompressed bytes.

    `truncate=False` (a success body): more than `limit` bytes raise `BodyTooLargeError`, and a
    gzip body that ends before its end marker raises `BodyError`. `truncate=True` (an error body,
    kept only as a diagnostic excerpt): the body is cut at `limit` and whatever decoded before a
    failure is kept.
    """

    def __init__(self, *, limit: int, gzip: bool, truncate: bool = False) -> None:
        self._limit = limit
        self._truncate = truncate
        self._inflater = zlib.decompressobj(_GZIP_WINDOW) if gzip else None
        self._parts: list[bytes] = []
        self._size = 0
        self._done = False
        self._failed = False

    @property
    def done(self) -> bool:
        """True when no further chunk is wanted (the gzip member ended or the cut was made)."""
        return self._done

    def feed(self, chunk: bytes) -> None:
        if self._done:
            return
        if self._inflater is None:
            self._append(chunk)
            return
        self._inflate(chunk)

    def finish(self) -> bytes:
        """The body; a gzip stream that stopped early is an error unless truncating."""
        if (
            self._inflater is not None
            and not self._inflater.eof
            and not self._done
            and not self._truncate
        ):
            raise BodyError("the gzip body ends before its end marker")
        return b"".join(self._parts)

    def _inflate(self, chunk: bytes) -> None:
        inflater = self._inflater
        if inflater is None:
            return
        pending = chunk
        while pending and not self._done:
            # Small slices: zlib returns no output of a call that fails, so a slice bounds what
            # an error body loses of its decoded start.
            piece, pending = pending[:_SLICE_BYTES], pending[_SLICE_BYTES:]
            while piece and not self._done:
                room = min(self._limit - self._size + 1, _STEP_BYTES)
                try:
                    out = inflater.decompress(piece, room)
                except zlib.error:
                    if self._truncate:
                        self._done = True
                        return
                    raise BodyError("the gzip body is corrupt") from None
                self._append(out)
                if inflater.eof:
                    self._done = True  # a member ended: bytes after it are not part of the body
                    return
                piece = inflater.unconsumed_tail

    def _append(self, data: bytes) -> None:
        room = self._limit - self._size
        if len(data) > room:
            if not self._truncate:
                raise BodyTooLargeError(f"the response body is longer than {self._limit} bytes")
            data = data[:room]
            self._done = True
        self._parts.append(data)
        self._size += len(data)
        if self._size >= self._limit and self._truncate:
            self._done = True
