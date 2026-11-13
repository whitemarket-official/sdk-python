"""Row decoders and the sync and async iterators over a stream of body chunks (SDK_SPEC 3.10 rules
8 to 12).

The decoders are push parsers without any I/O: `feed(chunk)` yields the rows that chunk completes.
The sync and the async iterator are thin loops over one `RowDecoder`, so the parsing logic exists
once. The chunks are the already decompressed bytes of the body, in any size (the decoders split
them internally).
"""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Iterator
from functools import partial
from typing import Any, Generic, Protocol, TypeVar

from whitemarket.exports.csv_rows import CsvRecordReader
from whitemarket.exports.json_rows import JsonArrayReader
from whitemarket.exports.kinds import ExportFormat, ExportKind
from whitemarket.exports.mappers import Path, map_price_row, map_product_row
from whitemarket.exports.rows import PriceRow, ProductRow

Row = TypeVar("Row")


class _RecordReader(Protocol):
    def feed(self, chunk: bytes) -> Iterator[Any]: ...

    def finish(self) -> Iterator[Any]: ...

    def close(self) -> None: ...


class RowDecoder(Generic[Row]):
    """Turns body chunks into row models; one instance decodes one body.

    A row that fails to decode, or a body that breaks off, raises `DecodeError` (path
    `<kind>[<index>]...`) after the rows before it were yielded. The index counts every record of
    the file, including the skipped rows of a products file whose category is null, which are not
    yielded.
    """

    def __init__(
        self,
        reader: _RecordReader,
        root: str,
        mapper: Callable[[Any, Path], Row | None],
    ) -> None:
        self._reader = reader
        self._root = root
        self._mapper = mapper
        self._index = 0

    def feed(self, chunk: bytes) -> Iterator[Row]:
        return self._map(self._reader.feed(chunk))

    def finish(self) -> Iterator[Row]:
        return self._map(self._reader.finish())

    def close(self) -> None:
        """Release the parser; the iterators below call it when they end, whatever the reason."""
        self._reader.close()

    def _map(self, records: Iterator[Any]) -> Iterator[Row]:
        for record in records:
            path: Path = (self._root, self._index)
            self._index += 1
            row = self._mapper(record, path)
            if row is not None:
                yield row


def price_row_decoder(
    format: ExportFormat = ExportFormat.JSON,
    *,
    json_backend: str | None = None,
) -> RowDecoder[PriceRow]:
    """A decoder of a prices file. `json_backend` is an `ijson` backend (tests; default: best)."""
    root = ExportKind.PRICES.value
    if format is ExportFormat.CSV:
        return RowDecoder(CsvRecordReader(root), root, partial(map_price_row, text=True))
    return RowDecoder(JsonArrayReader(root, backend=json_backend), root, map_price_row)


def product_row_decoder(
    format: ExportFormat = ExportFormat.JSON,
    *,
    json_backend: str | None = None,
) -> RowDecoder[ProductRow]:
    """A decoder of a products file; null-category rows are skipped, keeping the file index."""
    root = ExportKind.PRODUCTS.value
    if format is ExportFormat.CSV:
        return RowDecoder(CsvRecordReader(root), root, map_product_row)
    return RowDecoder(JsonArrayReader(root, backend=json_backend), root, map_product_row)


def iter_rows(decoder: RowDecoder[Row], chunks: Iterable[bytes]) -> Iterator[Row]:
    """Decode `chunks` lazily, one row in memory; the chunk source is closed at the end."""
    try:
        for chunk in chunks:
            yield from decoder.feed(chunk)
        yield from decoder.finish()
    finally:
        decoder.close()
        close: Any = getattr(chunks, "close", None)
        if close is not None:
            close()


async def aiter_rows(decoder: RowDecoder[Row], chunks: AsyncIterable[bytes]) -> AsyncIterator[Row]:
    """The async twin of `iter_rows`: the same decoder, fed from an async chunk source."""
    try:
        async for chunk in chunks:
            for row in decoder.feed(chunk):
                yield row
        for row in decoder.finish():
            yield row
    finally:
        decoder.close()
        aclose: Any = getattr(chunks, "aclose", None)
        if aclose is not None:
            await aclose()


def iter_price_rows(
    chunks: Iterable[bytes],
    format: ExportFormat = ExportFormat.JSON,
) -> Iterator[PriceRow]:
    """Stream the rows of a prices file."""
    return iter_rows(price_row_decoder(format), chunks)


def iter_product_rows(
    chunks: Iterable[bytes],
    format: ExportFormat = ExportFormat.JSON,
) -> Iterator[ProductRow]:
    """Stream the rows of a products file."""
    return iter_rows(product_row_decoder(format), chunks)


def aiter_price_rows(
    chunks: AsyncIterable[bytes],
    format: ExportFormat = ExportFormat.JSON,
) -> AsyncIterator[PriceRow]:
    """Stream the rows of a prices file from an async chunk source."""
    return aiter_rows(price_row_decoder(format), chunks)


def aiter_product_rows(
    chunks: AsyncIterable[bytes],
    format: ExportFormat = ExportFormat.JSON,
) -> AsyncIterator[ProductRow]:
    """Stream the rows of a products file from an async chunk source."""
    return aiter_rows(product_row_decoder(format), chunks)
