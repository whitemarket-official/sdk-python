"""A million streamed rows hold a bounded amount of memory (SDK_SPEC 7, rule 9).

Slow (about two minutes under tracemalloc), so it lives outside `tests/unit` and runs with
`make test-memory`. The body is generated on the fly, chunk by chunk; nothing of it is a file.
"""

import json
import tracemalloc
from collections.abc import Iterator

import pytest

from support.exports import PRODUCT_ROW
from whitemarket.exports import ExportFormat, iter_product_rows

pytestmark = pytest.mark.memory

ROWS = 1_000_000
ROWS_PER_CHUNK = 200
PEAK_LIMIT = (
    4 * 1024 * 1024
)  # a streamed run peaks near 0.5 MiB; holding the rows would take gigabytes


def json_body(rows: int) -> Iterator[bytes]:
    """`rows` product rows as a JSON array, in chunks of `ROWS_PER_CHUNK` rows."""
    batch: list[str] = []
    started = False
    for number in range(rows):
        row = {**PRODUCT_ROW, "product_id": f"{number:036d}", "product_asset_id": 2**53 + number}
        batch.append(json.dumps(row, separators=(",", ":")))
        if len(batch) == ROWS_PER_CHUNK:
            yield (b"," if started else b"[") + ",".join(batch).encode()
            started = True
            batch = []
    if batch:
        yield (b"," if started else b"[") + ",".join(batch).encode()
    yield b"]"


def csv_body(rows: int) -> Iterator[bytes]:
    yield b"product_id,product_category,product_class_id,product_instance_id,product_asset_id,"
    yield b"name_hash,price,currency\n"
    for number in range(rows):
        yield f"{number:036d},RIFLES,1,2,{2**53 + number},AK-47 | Synthetic,7.060,USD\n".encode()


@pytest.mark.parametrize(
    ("fmt", "body"),
    [
        pytest.param(ExportFormat.JSON, json_body, id="JSON"),
        pytest.param(ExportFormat.CSV, csv_body, id="CSV"),
    ],
)
def test_a_million_rows_are_streamed_in_bounded_memory(fmt: ExportFormat, body: object) -> None:
    make_body = body
    assert callable(make_body)
    count = 0
    last_asset_id = ""

    tracemalloc.start()
    try:
        for row in iter_product_rows(make_body(ROWS), fmt):
            count += 1
            last_asset_id = row.asset_id
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == ROWS
    assert last_asset_id == str(2**53 + ROWS - 1)
    assert peak < PEAK_LIMIT
