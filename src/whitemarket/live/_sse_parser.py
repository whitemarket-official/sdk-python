"""Incremental parser of a `text/event-stream` body (the SSE live transport)."""

import re
from collections import deque

from whitemarket.errors.base import TransportError

_TERMINATOR = re.compile(rb"[\r\n]")
_LINE_OVERHEAD = 6  # `data:` and one space
_CR = 0x0D
_LF = 0x0A


class SseParser:
    """Feed raw chunks (split anywhere, also inside CRLF), take the complete events with `next`.

    Only `data` fields are used; comments (`:`), `event`, `id`, `retry` and unknown fields are
    ignored. A line ends with CRLF, LF or CR; one space after the colon is removed; several `data`
    lines of one event are joined with LF; the empty line dispatches the event, and an event
    without a `data` line is not dispatched. An event still open when the stream ends is
    dropped, as the SSE specification says.

    An event is decoded as UTF-8 once it is complete, so a multibyte character split across chunks
    survives. Bytes that are not valid UTF-8 become U+FFFD (`errors="replace"`): the parser handles
    bytes, and whether the JSON inside is valid is the decoder's business.

    `max_message_bytes` caps the joined data of one event. A raw line may be at most 6 bytes longer
    (`data:` and one space), so a line is never buffered past the cap plus that overhead; a
    violation raises `TransportError` before more is buffered. Complete events wait in a queue only
    until the caller takes them. Neither error message holds a byte of the stream.
    """

    def __init__(self, max_message_bytes: int) -> None:
        if max_message_bytes < 1:
            raise ValueError("max_message_bytes must be at least 1")
        self._max = max_message_bytes
        self._line = bytearray()
        self._data = bytearray()
        self._has_data = False
        self._skip_line_feed = False
        self._events: deque[str] = deque()

    def feed(self, chunk: bytes) -> None:
        """Parse one chunk. Raises `TransportError` when a line or an event exceeds the cap."""
        length = len(chunk)
        pos = 0
        if self._skip_line_feed and length > 0:
            self._skip_line_feed = False
            if chunk[0] == _LF:
                pos = 1

        while pos < length:
            terminator = _TERMINATOR.search(chunk, pos)
            end = length if terminator is None else terminator.start()
            self._append_to_line(chunk, pos, end)
            if terminator is None:
                return
            pos = end + 1
            self._process_line()
            if chunk[end] == _CR:
                if pos < length:
                    if chunk[pos] == _LF:
                        pos += 1
                else:
                    self._skip_line_feed = True

    def next(self) -> str | None:
        """The data of the next complete event, or None when none is complete yet."""
        return self._events.popleft() if self._events else None

    def _append_to_line(self, chunk: bytes, start: int, end: int) -> None:
        if len(self._line) + (end - start) > self._max + _LINE_OVERHEAD:
            raise TransportError("A live event line exceeds the size limit.")
        self._line += chunk[start:end]

    def _process_line(self) -> None:
        line = bytes(self._line)
        self._line.clear()

        if not line:
            if self._has_data:
                self._events.append(self._data.decode("utf-8", "replace"))
                self._data.clear()
                self._has_data = False
            return

        colon = line.find(b":")
        if colon == 0:
            return
        field = line if colon < 0 else line[:colon]
        if field != b"data":
            return

        value = b"" if colon < 0 else line[colon + 1 :]
        if value[:1] == b" ":
            value = value[1:]

        if len(self._data) + (1 if self._has_data else 0) + len(value) > self._max:
            raise TransportError("A live event exceeds the size limit.")
        if self._has_data:
            self._data += b"\n"
        self._data += value
        self._has_data = True
