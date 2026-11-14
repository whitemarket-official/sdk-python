"""The sync and async row iterators over one decoder (SDK_SPEC 3.10 rules 9 to 11)."""

import asyncio
import sys
from collections.abc import AsyncGenerator, AsyncIterator

import pytest

from support.exports import (
    PRICE_ROW,
    PRODUCT_ROW,
    Watched,
    achunked,
    chunked,
    fixture,
    json_body,
)
from whitemarket.errors import DecodeError
from whitemarket.exports import (
    ExportFormat,
    ProductRow,
    aiter_price_rows,
    aiter_product_rows,
    iter_price_rows,
    iter_product_rows,
)
from whitemarket.exports._stream import RowDecoder, price_row_decoder, product_row_decoder


@pytest.mark.parametrize("fmt", [ExportFormat.JSON, ExportFormat.CSV])
@pytest.mark.parametrize("size", [1, 5, 4096, 1 << 30])
async def test_the_async_iterator_gives_the_rows_of_the_sync_one(
    fmt: ExportFormat, size: int
) -> None:
    data = fixture(f"products.{fmt.value}")

    sync_rows = list(iter_product_rows(chunked(data, size), fmt))
    async_rows = [row async for row in aiter_product_rows(achunked(data, size), fmt)]

    assert async_rows == sync_rows
    assert len(sync_rows) == (
        4 if fmt is ExportFormat.JSON else 3
    )  # JSON has the OTHERS row; CSV does not


@pytest.mark.parametrize("fmt", [ExportFormat.JSON, ExportFormat.CSV])
async def test_prices_stream_in_both_flavors(fmt: ExportFormat) -> None:
    data = fixture(f"prices.{fmt.value}")

    sync_rows = list(iter_price_rows(chunked(data, 9), fmt))
    async_rows = [row async for row in aiter_price_rows(achunked(data, 9), fmt)]

    assert len(sync_rows) == 4
    assert async_rows == sync_rows


def test_json_and_csv_products_map_to_the_same_rows() -> None:
    csv_rows = list(iter_product_rows(chunked(fixture("products.csv"), 64), ExportFormat.CSV))
    json_rows = list(iter_product_rows(chunked(fixture("products.json"), 64)))
    assert [row.product_id[-1] for row in json_rows[:3]] == ["1", "2", "4"]

    assert [row.product_id for row in csv_rows] == [row.product_id for row in json_rows[:3]]
    for from_csv, from_json in zip(csv_rows, json_rows[:3], strict=True):
        assert from_csv.market_hash_name == from_json.market_hash_name
        assert from_csv.asset_id == from_json.asset_id
        assert from_csv.price == from_json.price
        assert from_csv.paint_index == from_json.paint_index


def test_csv_rows_use_the_same_models_and_skip_the_null_category() -> None:
    rows = list(iter_product_rows(chunked(fixture("products.csv"), 7), ExportFormat.CSV))

    assert [r.product_id[-1] for r in rows] == ["1", "2", "4"]  # the row "3" has an empty category
    assert rows[1].class_id == "18446744073709551615"
    assert rows[1].inspect_link is None
    assert rows[1].paint_index is None
    assert rows[2].phase == "Phase 2"


def test_a_csv_row_failure_has_the_file_index_of_the_record() -> None:
    body = fixture("products.csv").replace(b"7.060", b"seven")

    with pytest.raises(DecodeError) as error:
        list(iter_product_rows(chunked(body, 100), ExportFormat.CSV))

    assert error.value.path == ("products", 0, "price")


def test_a_csv_prices_count_is_a_digit_string() -> None:
    body = fixture("prices.csv").replace(b'"12"', b'"x"')

    with pytest.raises(DecodeError) as error:
        list(iter_price_rows(chunked(body, 100), ExportFormat.CSV))

    assert error.value.path == ("prices", 0, "market_product_count")


def test_rows_arrive_before_the_rest_of_the_body_is_read() -> None:
    rows = [PRODUCT_ROW] * 2000
    body = json_body(rows)
    source = Watched(body, 1000)

    iterator = iter_product_rows(source)
    first = next(iterator)

    assert isinstance(first, ProductRow)
    assert source.pulled < len(body) // 4  # laziness: only the start of the body was pulled
    assert not source.closed


def test_the_chunk_source_is_closed_when_the_iteration_ends() -> None:
    source = Watched(json_body([PRODUCT_ROW] * 3), 100)

    assert len(list(iter_product_rows(source))) == 3
    assert source.closed


def test_the_chunk_source_is_closed_when_the_consumer_stops_early() -> None:
    source = Watched(json_body([PRODUCT_ROW] * 300), 100)
    iterator = iter_product_rows(source)
    next(iterator)

    iterator.close()

    assert source.closed


def test_the_chunk_source_is_closed_when_decoding_fails() -> None:
    source = Watched(b'[{"a": SECRET}]', 4)

    with pytest.raises(DecodeError):
        list(iter_product_rows(source))

    assert source.closed


class WatchedAsync:
    def __init__(self, data: bytes, size: int) -> None:
        self._chunks = chunked(data, size)
        self.closed = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        self.closed = True


async def test_the_async_chunk_source_is_closed_at_the_end_early_stop_and_failure() -> None:
    finished = WatchedAsync(json_body([PRODUCT_ROW] * 3), 100)
    assert len([row async for row in aiter_product_rows(finished)]) == 3

    early = WatchedAsync(json_body([PRODUCT_ROW] * 300), 100)
    iterator = aiter_product_rows(early)
    assert isinstance(iterator, AsyncGenerator)
    await anext(iterator)
    await iterator.aclose()

    failing = WatchedAsync(b"{}", 1)
    with pytest.raises(DecodeError):
        _ = [row async for row in aiter_product_rows(failing)]

    assert finished.closed
    assert early.closed
    assert failing.closed


async def test_an_async_failure_comes_after_the_rows_before_it() -> None:
    body = json_body([PRODUCT_ROW, PRODUCT_ROW, {**PRODUCT_ROW, "price": 1}])
    seen: list[ProductRow] = []

    async def drain() -> None:
        async for row in aiter_product_rows(achunked(body, 60)):
            seen.append(row)

    with pytest.raises(DecodeError) as error:
        await drain()

    assert len(seen) == 2
    assert error.value.path == ("products", 2, "price")


async def test_a_cancelled_async_consumer_leaves_no_task_running() -> None:
    async def slow() -> AsyncIterator[bytes]:
        yield b"["
        await asyncio.sleep(3600)
        yield b"]"

    async def consume() -> None:
        async for _ in aiter_product_rows(slow()):
            pass

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_a_decoder_decodes_one_body_and_can_be_driven_by_hand() -> None:
    decoder = price_row_decoder()
    rows = []
    for chunk in chunked(json_body([PRICE_ROW, PRICE_ROW]), 33):
        rows.extend(decoder.feed(chunk))
    rows.extend(decoder.finish())
    decoder.close()

    assert len(rows) == 2


def decode_all(decoder: RowDecoder[ProductRow], data: bytes) -> list[ProductRow]:
    rows: list[ProductRow] = []
    for chunk in chunked(data, 100):
        rows.extend(decoder.feed(chunk))
    rows.extend(decoder.finish())
    return rows


def test_the_json_backends_agree_on_the_fixture() -> None:
    data = fixture("products.json")

    fast = decode_all(product_row_decoder(json_backend="yajl2_c"), data)
    pure = decode_all(product_row_decoder(json_backend="python"), data)

    assert len(fast) == 4
    assert fast == pure


def test_a_missing_ijson_names_the_extra_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ijson", None)

    with pytest.raises(ImportError, match=r"whitemarket-sdk\[exports\]"):
        product_row_decoder()


def test_csv_needs_no_ijson(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ijson", None)

    rows = list(iter_product_rows(chunked(fixture("products.csv"), 64), ExportFormat.CSV))

    assert len(rows) == 3
