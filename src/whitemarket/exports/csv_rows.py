"""Streaming decoder of a CSV export (SDK_SPEC 3.10 rule 11).

RFC 4180: `,` separates, `"` quotes (`""` inside), a record ends at CRLF or LF outside quotes, a
UTF-8 BOM is ignored. The first record is the header; columns are matched by name. The body arrives
as byte chunks and is decoded incrementally, so a multi-byte character split between chunks is
fine. A record is cut from the text before it is parsed with the standard `csv` module, which is
what bounds it to `MAX_ROW_BYTES`.
"""

import codecs
import csv
from collections.abc import Iterator

from whitemarket.errors import DecodeError
from whitemarket.exports.limits import MAX_ROW_BYTES, PUSH_STEP

_BOM = "\ufeff"  # U+FEFF, written as an escape so the source has no invisible character
_BYTES_PER_CHAR = 4  # the most one character takes in UTF-8


def _over_limit(text: str) -> bool:
    """True when `text` takes more than `MAX_ROW_BYTES` in UTF-8 (short text is not encoded)."""
    if len(text) > MAX_ROW_BYTES:
        return True
    return len(text) * _BYTES_PER_CHAR > MAX_ROW_BYTES and len(text.encode()) > MAX_ROW_BYTES


class CsvRecordReader:
    """Push parser: `feed(chunk)` yields one `{column: value or None}` dict per record, `finish()`
    ends the body.

    Every failure is a `DecodeError` at `<root>` (header problems) or `<root>[<index of the
    record>]`, raised after the records that came before it were yielded. After a failure the
    reader is unusable.
    """

    def __init__(self, root: str) -> None:
        self._root = root
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._text = ""  # undelivered text; starts at the beginning of a record
        self._find_from = 0  # where the search for the next line feed resumes
        self._counted = 0  # quotes before this offset are in `_quoted`
        self._quoted = False  # inside a quoted field at `_counted`
        self._first_text = True
        self._header: tuple[str, ...] | None = None
        self._index = 0  # data records yielded so far
        self._done = False

    def feed(self, chunk: bytes) -> Iterator[dict[str, str | None]]:
        for start in range(0, len(chunk), PUSH_STEP):
            if self._done:
                return
            text, valid = self._decode(chunk[start : start + PUSH_STEP], final=False)
            yield from self._take(text)
            if not valid:
                raise self._invalid_utf8()

    def finish(self) -> Iterator[dict[str, str | None]]:
        if self._done:
            return
        text, valid = self._decode(b"", final=True)
        yield from self._take(text)
        if not valid:
            raise self._invalid_utf8()
        self._done = True
        self._count_quotes(len(self._text))
        if self._quoted:
            raise DecodeError("the body ends inside a quoted field", self._path())
        tail = self._text.removesuffix("\r")
        self._text = ""
        record = self._record(tail) if tail else None
        if record is not None:
            yield record
        if self._header is None:
            raise DecodeError("no CSV header", (self._root,))

    def close(self) -> None:
        """Release the reader; safe to call at any time and more than once."""
        self._done = True

    def _invalid_utf8(self) -> DecodeError:
        self._done = True
        return DecodeError("the body is not valid UTF-8", self._path())

    def _path(self) -> tuple[str | int, ...]:
        return (self._root,) if self._header is None else (self._root, self._index)

    def _decode(self, data: bytes, *, final: bool) -> tuple[str, bool]:
        """The text of `data` and whether all of it was valid UTF-8 (the valid part comes out)."""
        try:
            return self._strip_bom(self._decoder.decode(data, final=final)), True
        except UnicodeDecodeError as error:
            # the decoder keeps its buffer (up to three bytes of a character cut by the last chunk)
            # when it raises; the bytes before the bad one are decoded again, on their own
            pending = len(self._decoder.getstate()[0])
            text = self._decoder.decode(data[: max(error.start - pending, 0)])
            return self._strip_bom(text), False

    def _strip_bom(self, text: str) -> str:
        if self._first_text and text:
            self._first_text = False
            return text.removeprefix(_BOM)
        return text

    def _take(self, text: str) -> Iterator[dict[str, str | None]]:
        self._text += text
        while True:
            line_end = self._text.find("\n", self._find_from)
            if line_end < 0:
                break
            self._count_quotes(line_end)
            if self._quoted:
                self._find_from = line_end + 1
                continue
            body = self._text[:line_end]
            self._text = self._text[line_end + 1 :]
            self._find_from = self._counted = 0
            body = body.removesuffix("\r")
            record = self._record(body) if body else None
            if record is not None:
                yield record
        self._find_from = len(self._text)
        if _over_limit(self._text.removesuffix("\r")):
            self._done = True
            raise DecodeError("a CSV record is too long", self._path())

    def _count_quotes(self, upto: int) -> None:
        if self._text.count('"', self._counted, upto) % 2:
            self._quoted = not self._quoted
        self._counted = upto + 1

    def _record(self, body: str) -> dict[str, str | None] | None:
        """The row of one record, None for the header."""
        if _over_limit(body):
            self._done = True
            raise DecodeError("a CSV record is too long", self._path())
        try:
            fields = next(csv.reader([body], strict=True))
        except csv.Error:
            fields = None
        if fields is None:  # not chained: the message could quote the record
            self._done = True
            raise DecodeError("not a valid CSV record", self._path())
        if self._header is None:
            self._header = self._read_header(fields)
            return None
        row = self._combine(self._header, fields)
        self._index += 1
        return row

    def _read_header(self, names: list[str]) -> tuple[str, ...]:
        if "" in names or len(set(names)) != len(names):
            self._done = True
            raise DecodeError("the CSV header has an empty or repeated column name", (self._root,))
        return tuple(names)

    def _combine(self, header: tuple[str, ...], fields: list[str]) -> dict[str, str | None]:
        if len(fields) != len(header):
            self._done = True
            raise DecodeError("the field count differs from the header", self._path())
        return {name: value or None for name, value in zip(header, fields, strict=True)}
