"""Streaming decoder of a JSON array of rows (SDK_SPEC 3.10 rules 10 and 12).

The body is fed in chunks to an `ijson` push parser that builds one row at a time. Numbers come as
`int` (any size, never rounded) or `Decimal` (a float token), never `float` (`use_float=False`).

`ijson` cannot report where a row begins or how long it is, so the cap is applied to the input
handed over since the last finished row, in steps of `PUSH_STEP` bytes: a row of at most
`MAX_ROW_BYTES` is never refused, one longer than `MAX_ROW_BYTES + 3 * PUSH_STEP` always is (the
small read-ahead of rule 10), in between either may happen. The nesting limit is checked on the
finished row, which the row cap bounds.
"""

import re
import sys
from collections.abc import Iterable, Iterator
from contextlib import suppress
from importlib import import_module
from typing import Any, cast

from whitemarket.errors import DecodeError
from whitemarket.exports._limits import MAX_ROW_BYTES, MAX_ROW_DEPTH, PUSH_STEP

_WHITE_SPACE = b" \t\n\r"
_DIGITS = b"0123456789"
_ALLOWANCE = (
    PUSH_STEP  # room for the separators between rows, so a row of exactly the cap is never refused
)


class _Sink:
    """The target of the `items_coro` pipeline: collects the rows of one step."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def send(self, row: Any) -> None:
        self.rows.append(row)

    def take(self) -> list[Any]:
        rows, self.rows = self.rows, []
        return rows


def _load_ijson(backend: str | None) -> Any:
    try:
        ijson = import_module("ijson")
    except ImportError as exc:
        raise ImportError(
            "streaming exports need ijson: pip install 'whitemarket-sdk[exports]'"
        ) from exc
    return ijson if backend is None else ijson.get_backend(backend)


def is_too_deep(row: Any) -> bool:
    """True when `row` (a decoded JSON value) nests containers deeper than `MAX_ROW_DEPTH`."""
    stack: list[tuple[Any, int]] = [(row, 1)]
    while stack:
        value, depth = stack.pop()
        children: Iterable[Any]
        if isinstance(value, dict):
            children = cast("dict[str, Any]", value).values()
        elif isinstance(value, list):
            children = cast("Iterable[Any]", value)
        else:
            continue
        if depth > MAX_ROW_DEPTH:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


class JsonArrayReader:
    """Push parser: `feed(chunk)` yields the decoded rows of the top-level array, `finish()` ends
    the body.

    Every failure is a `DecodeError` at `<root>` (the body is not an array) or `<root>[<index of
    the row being read>]`, raised after the rows that came before it were yielded. The messages
    never hold server bytes: the parser's own message quotes the input, so it is neither chained
    nor kept. After a failure the reader is unusable.
    """

    def __init__(self, root: str, *, backend: str | None = None) -> None:
        self._root = root
        self._sink = _Sink()
        ijson = _load_ijson(backend)
        self._parse_errors: tuple[type[BaseException], ...] = (
            import_module("ijson.common").JSONError,
            ValueError,  # integer or text conversion limits, bytes the pure Python backend refuses
            RecursionError,
            ArithmeticError,  # decimal.InvalidOperation on a token such as 1e99999999999999999999
        )
        self._coroutine = ijson.items_coro(self._sink, "item", use_float=False)
        self._max_digits = sys.get_int_max_str_digits()
        self._long_run = re.compile(b"[0-9]{%d}" % (self._max_digits + 1))
        self._digit_carry = 0  # digits at the end of the previous piece
        self._started = False  # the opening `[` was seen
        self._pending = 0  # bytes handed over since the last finished row
        self._index = 0  # rows yielded so far = the index of the row being read
        self._done = False

    def feed(self, chunk: bytes) -> Iterator[Any]:
        for start in range(0, len(chunk), PUSH_STEP):
            yield from self._step(chunk[start : start + PUSH_STEP])

    def finish(self) -> Iterator[Any]:
        if not self._started:
            raise self._fail("the body is not a JSON array", (self._root,))
        yield from self._step(b"")
        self.close()

    def _step(self, piece: bytes) -> Iterator[Any]:
        if self._done:
            return
        if not self._started and not self._open(piece):
            return
        cut = self._long_digit_run(piece)
        failure = self._push(piece if cut is None else piece[:cut])
        if cut is not None and failure is None:
            failure = "a run of digits is too long"
        rows = self._sink.take()
        if rows:
            self._pending = 0
        else:
            self._pending += len(piece)
            if failure is None and self._pending > MAX_ROW_BYTES + _ALLOWANCE:
                failure = "a row is too long"
        for row in rows:
            if is_too_deep(row):
                raise self._fail("a row is nested too deep", (self._root, self._index))
            self._index += 1
            yield row
        if failure is not None:
            raise self._fail(failure, (self._root, self._index))

    def _long_digit_run(self, piece: bytes) -> int | None:
        """Where to stop feeding `piece` for a run of too many digits, else None.

        The C backend of ijson 3.6.0 crashes the interpreter (segfault) on an integer token
        longer than `sys.get_int_max_str_digits()` digits (observed, 3.13); no row of a real export
        comes near it. A run of more digits than the limit, in a number or a string, is refused for
        every backend so that they all give the same rows.
        """
        limit = self._max_digits
        if limit == 0:  # the interpreter has no limit, so the parser cannot fail on it
            return None
        rest = piece.lstrip(_DIGITS)
        if self._digit_carry + len(piece) - len(rest) > limit:
            return 0
        if not rest:
            self._digit_carry += len(piece)
            return None
        found = self._long_run.search(rest)
        if found is not None:
            return len(piece) - len(rest) + found.start()
        self._digit_carry = len(rest) - len(rest.rstrip(_DIGITS))
        return None

    def close(self) -> None:
        """Release the parser; safe to call at any time and more than once."""
        self._done = True
        # a parser closed mid-document complains; there is nothing to report
        with suppress(*self._parse_errors):
            self._coroutine.close()

    def _fail(self, reason: str, path: tuple[str | int, ...]) -> DecodeError:
        self.close()
        return DecodeError(reason, path)

    def _open(self, piece: bytes) -> bool:
        """Check the first byte that is not white space; False while there has been none."""
        stripped = piece.lstrip(_WHITE_SPACE)
        if not stripped:
            return False
        if stripped[:1] != b"[":
            raise self._fail("the body is not a JSON array", (self._root,))
        self._started = True
        return True

    def _push(self, piece: bytes) -> str | None:
        """Hand `piece` to the parser; the reason of a failure, None when it went well."""
        try:
            self._coroutine.send(piece)
        except StopIteration:
            return None  # the end of the body was fed and the array is complete
        except self._parse_errors:
            return "the array is cut short" if not piece else "not valid JSON"
        return None
