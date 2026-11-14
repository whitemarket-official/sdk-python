"""Helpers of the export tests: fixture files, chunking, row builders, a watched chunk source."""

import json
from collections.abc import AsyncIterator, Iterable, Iterator
from pathlib import Path
from typing import Any

import ijson
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "exports"

BACKENDS = [
    pytest.param(name, id=f"ijson {name}")
    for name in ("yajl2_c", "python")
    if ijson.get_backend(name) is not None
]

CHUNK_SIZES = [
    pytest.param(1, id="1 byte chunks"),
    pytest.param(7, id="7 byte chunks"),
    pytest.param(4096, id="4096 byte chunks"),
    pytest.param(1 << 30, id="one chunk"),
]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def chunked(data: bytes, size: int) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


async def achunked(data: bytes, size: int) -> AsyncIterator[bytes]:
    for chunk in chunked(data, size):
        yield chunk


def json_body(rows: Iterable[Any]) -> bytes:
    return json.dumps(list(rows)).encode()


class Watched:
    """A chunk source that counts the bytes pulled from it and notes whether it was closed."""

    def __init__(self, data: bytes, size: int) -> None:
        self._chunks = chunked(data, size)
        self.pulled = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        chunk = next(self._chunks)
        self.pulled += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


PRICE_ROW: dict[str, Any] = {
    "market_hash_name": "AK-47 | Synthetic Redline (Field-Tested)",
    "price": "7.060",
    "market_product_link": "https://white.market/item?appId=730&nameHash=x",
    "market_product_count": 12,
    "cheapest_asset_id": 9007199254740993,
    "cheapest_float": "0.2517",
    "paint_index": "282",
    "paint_seed": "661",
    "inspect_link": "steam://synthetic",
}

PRICES_BODY = json_body([PRICE_ROW])  # a prices file of one row


PRODUCT_ROW: dict[str, Any] = {
    "product_id": "00000000-0000-4000-8000-000000000001",
    "product_category": "RIFLES",
    "product_type": "Rifle",
    "product_subtype": "AK-47",
    "product_class_id": 310776560,
    "product_instance_id": 188530139,
    "product_asset_id": 9007199254740993,
    "product_float": "0.2517",
    "product_paint_index": 282,
    "product_phase": None,
    "name_hash": "AK-47 | Synthetic Redline (Field-Tested)",
    "price": "7.060",
    "currency": "USD",
    "product_paint_seed": 661,
    "deliveryType": "auto",
    "deliveryPromise": "10min",
    "inspectLink": "steam://synthetic",
}
