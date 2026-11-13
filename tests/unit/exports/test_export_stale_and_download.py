"""`max_age`, downloads and streamed products on a scripted HTTP client (SDK_SPEC 3.10 rules 1, 7,
9). Every test runs for both flavors.
"""

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from support.export_rig import (
    BASE,
    GZIP,
    META_BODY,
    META_URL,
    PRICES_URL,
    Rig,
    gz,
    ok,
)
from support.exports import PRICE_ROW, PRODUCT_ROW, fixture, json_body
from support.flavors import FLAVORS, Flavor
from support.http import Chunks, reply
from whitemarket.errors import (
    DecodeError,
    GeneralExportError,
    HttpError,
    StaleExportError,
    TransportError,
)
from whitemarket.exports import ExportFormat, ExportKind, ExportWindow

each_flavor = pytest.mark.parametrize("flavor", FLAVORS, ids=lambda f: f.name)
PRICES = json_body([PRICE_ROW])
HOUR = 3600


@pytest.fixture
def rigs() -> Any:
    made: list[Rig] = []

    def make(flavor: Flavor, *outcomes: Any, **kwargs: Any) -> Rig:
        rig = Rig(flavor, *outcomes, **kwargs)
        made.append(rig)
        return rig

    yield make
    for rig in made:
        rig.close()


def meta_aged(seconds: float) -> bytes:
    """A meta whose `data_as_of` is `seconds` before the rig clock (2026-11-06T12:00:00Z)."""
    moment = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC) - timedelta(seconds=seconds)
    stamp = moment.isoformat()
    return b'{"file":"730.json","data_as_of":"%s","generated_at":"%s","items":1}' % (
        stamp.encode(),
        stamp.encode(),
    )


# --- max_age ---------------------------------------------------------------------------------


@each_flavor
@pytest.mark.parametrize("call", ["prices", "stream_prices", "stream_products"])
def test_data_older_than_max_age_is_stale_and_the_file_is_not_downloaded(
    flavor: Flavor, rigs: Any, call: str
) -> None:
    rig = rigs(flavor, ok(meta_aged(HOUR + 1)))

    with pytest.raises(StaleExportError) as caught:
        rig.call(call, max_age=timedelta(hours=1))

    assert len(rig.requests) == 1
    assert rig.urls[0].endswith(".meta.json")
    assert caught.value.max_age_seconds == HOUR
    assert caught.value.data_as_of.isoformat() == "2026-11-06T10:59:59+00:00"


@each_flavor
@pytest.mark.parametrize(
    ("age", "fresh"),
    [
        pytest.param(HOUR - 1, True, id="a second inside"),
        pytest.param(HOUR, True, id="exactly the limit"),
        pytest.param(HOUR + 1, False, id="a second over"),
    ],
)
def test_the_max_age_boundary(flavor: Flavor, rigs: Any, age: int, fresh: bool) -> None:
    rig = rigs(flavor, ok(meta_aged(age)), ok(PRICES))

    if fresh:
        assert len(rig.prices(max_age=HOUR)) == 1
        assert rig.urls == [META_URL, PRICES_URL]
    else:
        with pytest.raises(StaleExportError):
            rig.prices(max_age=HOUR)


@each_flavor
def test_max_age_of_products_asks_for_the_meta_of_that_file(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(meta_aged(10)), ok(gz(fixture("products.json")), **GZIP))

    rows = rig.collect(rig.call("stream_products", window=ExportWindow.HOUR1, max_age=HOUR))

    assert rows
    assert rig.urls == [
        f"{BASE}/v1/products/730.1hour.json.meta.json",
        f"{BASE}/v1/products/730.1hour.json",
    ]


@each_flavor
@pytest.mark.parametrize("max_age", [-1, timedelta(seconds=-1)])
def test_a_negative_max_age_is_an_argument_error_before_any_request(
    flavor: Flavor, rigs: Any, max_age: Any
) -> None:
    rig = rigs(flavor, ok(META_BODY))

    with pytest.raises(ValueError, match="max_age"):
        rig.prices(max_age=max_age)

    assert rig.requests == []


@each_flavor
def test_a_failing_meta_fails_the_call_with_its_own_error(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, reply(404))

    with pytest.raises(HttpError):
        rig.prices(max_age=HOUR)

    assert len(rig.requests) == 1


@each_flavor
def test_a_meta_that_is_not_valid_is_a_decode_error(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(b'{"file":"x"}'))

    with pytest.raises(DecodeError, match=r"meta\.data_as_of"):
        rig.prices(max_age=HOUR)


# --- download --------------------------------------------------------------------------------

DOWNLOAD = (ExportKind.PRICES, 730, None, ExportFormat.JSON)


@each_flavor
def test_a_download_is_written_to_the_path_decoded(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(gz(PRICES), **GZIP))
    target = tmp_path / "prices.json"

    rig.call("download", *DOWNLOAD, target)

    assert target.read_bytes() == PRICES
    assert [p.name for p in tmp_path.iterdir()] == ["prices.json"]


@each_flavor
def test_a_download_has_no_size_limit(flavor: Flavor, rigs: Any, tmp_path: Path) -> None:
    body = b"[" + b" " * 3_000_000 + b"]"
    rig = rigs(flavor, ok(gz(body), **GZIP), max_body_bytes=1000)
    target = tmp_path / "big.json"

    rig.call("download", *DOWNLOAD, target)

    assert target.stat().st_size == len(body)


@each_flavor
def test_a_download_gets_the_mode_of_a_new_file(flavor: Flavor, rigs: Any, tmp_path: Path) -> None:
    rig = rigs(flavor, ok(PRICES))
    target = tmp_path / "p.json"
    umask = os.umask(0o022)
    try:
        rig.call("download", *DOWNLOAD, target)
    finally:
        os.umask(umask)

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@each_flavor
def test_a_download_accepts_a_pathlike_and_replaces_an_existing_file(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(PRICES))
    target = tmp_path / "p.json"
    target.write_bytes(b"old")

    rig.call("download", *DOWNLOAD, target)

    assert target.read_bytes() == PRICES


@each_flavor
@pytest.mark.parametrize("failure", ["status", "network", "body"])
def test_a_failed_download_leaves_the_old_file_and_no_temporary_file(
    flavor: Flavor, rigs: Any, tmp_path: Path, failure: str
) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    outcome = {
        "status": reply(404),
        "network": refused,
        "body": ok(gz(PRICES)[:-8], **GZIP),
    }[failure]
    rig = rigs(flavor, outcome)
    target = tmp_path / "p.json"
    target.write_bytes(b"old")

    with pytest.raises((HttpError, TransportError)):
        rig.call("download", *DOWNLOAD, target)

    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]


@each_flavor
def test_a_download_failing_halfway_removes_its_temporary_file(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    # The body fails after some chunks were written: a Content-Length that is never reached.
    rig = rigs(
        flavor,
        lambda request: httpx.Response(
            200, headers={"Content-Length": "100"}, stream=Chunks([b"[ ", b"  "])
        ),
    )

    with pytest.raises(TransportError, match="shorter than Content-Length"):
        rig.call("download", *DOWNLOAD, tmp_path / "p.json")

    assert list(tmp_path.iterdir()) == []


@each_flavor
def test_a_directory_as_destination_is_refused_before_the_request(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(PRICES))

    with pytest.raises(GeneralExportError, match="directory"):
        rig.call("download", *DOWNLOAD, tmp_path)

    assert rig.requests == []


@each_flavor
def test_a_destination_in_a_missing_directory_is_a_general_export_error(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(PRICES))

    with pytest.raises(GeneralExportError, match="temporary file"):
        rig.call("download", *DOWNLOAD, tmp_path / "missing" / "p.json")


@each_flavor
def test_a_download_into_a_binary_stream_leaves_it_open(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(gz(PRICES), **GZIP))

    with (tmp_path / "s.bin").open("wb") as stream:
        rig.call("download", *DOWNLOAD, stream)
        assert not stream.closed

    assert (tmp_path / "s.bin").read_bytes() == PRICES


class Trickle:
    """A writable stream that takes at most 3 bytes per write."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.flushed = False

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        taken = bytes(data[:3])
        self.data += taken
        return len(taken)

    def flush(self) -> None:
        self.flushed = True


@each_flavor
def test_a_stream_that_takes_less_than_it_is_given_gets_the_rest(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(PRICES))
    stream = Trickle()

    rig.call("download", *DOWNLOAD, stream)

    assert bytes(stream.data) == PRICES
    assert stream.flushed


class Stuck(Trickle):
    def write(self, data: Any) -> int:
        return 0


class ReadOnly(Trickle):
    def writable(self) -> bool:
        return False


@each_flavor
@pytest.mark.parametrize(
    ("stream", "message"),
    [
        pytest.param(Stuck, "no progress", id="no progress"),
        pytest.param(ReadOnly, "not writable", id="read only"),
    ],
)
def test_a_stream_that_cannot_be_written_is_a_general_export_error(
    flavor: Flavor, rigs: Any, stream: type[Trickle], message: str
) -> None:
    rig = rigs(flavor, ok(PRICES))

    with pytest.raises(GeneralExportError, match=message):
        rig.call("download", *DOWNLOAD, stream())


@each_flavor
def test_a_download_follows_the_same_rules_for_the_url(
    flavor: Flavor, rigs: Any, tmp_path: Path
) -> None:
    rig = rigs(flavor, ok(PRICES))

    rig.call(
        "download", ExportKind.PRODUCTS, 570, ExportWindow.HOURS12, ExportFormat.CSV, tmp_path / "x"
    )

    assert rig.urls == [f"{BASE}/v1/products/570.12hours.csv"]


# --- streamed products -----------------------------------------------------------------------


class Watched(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A body that notes how much was pulled and whether it was closed."""

    def __init__(self, parts: list[bytes]) -> None:
        self.parts = parts
        self.pulled = 0
        self.closed = False

    def __iter__(self) -> Any:
        for part in self.parts:
            self.pulled += 1
            yield part

    async def __aiter__(self) -> Any:
        for part in self.parts:
            self.pulled += 1
            yield part

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.closed = True


def product_json(count: int) -> list[bytes]:
    rows = [
        {**PRODUCT_ROW, "product_id": f"00000000-0000-4000-8000-{n:012d}"} for n in range(count)
    ]
    text = json_body(rows)
    return [text[i : i + 200] for i in range(0, len(text), 200)]


@each_flavor
def test_stopping_the_iteration_closes_the_connection_and_reads_no_more(
    flavor: Flavor, rigs: Any
) -> None:
    body = Watched(product_json(200))
    rig = rigs(flavor, lambda request: httpx.Response(200, stream=body))

    rows = rig.collect(rig.call("stream_products"), limit=3)

    assert len(rows) == 3
    assert body.closed
    assert body.pulled < len(body.parts)


@each_flavor
def test_closing_a_stream_never_iterated_closes_the_connection(flavor: Flavor, rigs: Any) -> None:
    body = Watched(product_json(5))
    rig = rigs(flavor, lambda request: httpx.Response(200, stream=body))

    stream = rig.call("stream_products")
    assert not body.closed
    rig.run(stream.aclose()) if flavor.is_async else stream.close()

    assert body.closed


@each_flavor
def test_a_finished_stream_is_closed(flavor: Flavor, rigs: Any) -> None:
    body = Watched(product_json(3))
    rig = rigs(flavor, lambda request: httpx.Response(200, stream=body))

    assert len(rig.collect(rig.call("stream_products"))) == 3
    assert body.closed


@each_flavor
def test_a_bad_row_fails_at_its_iteration_after_the_rows_before_it(
    flavor: Flavor, rigs: Any
) -> None:
    rows = [PRODUCT_ROW, PRODUCT_ROW, {**PRODUCT_ROW, "price": "nope"}, PRODUCT_ROW]
    body = Watched([json_body(rows)])
    rig = rigs(flavor, lambda request: httpx.Response(200, stream=body))
    stream = rig.call("stream_products")  # the request is sent here, the failure is later
    seen: list[Any] = []

    with pytest.raises(DecodeError, match=r"products\[2\]"):
        rig.drain(stream, seen)

    assert len(seen) == 2
    assert body.closed


@each_flavor
def test_a_body_that_breaks_off_fails_at_the_break_after_the_rows_before_it(
    flavor: Flavor, rigs: Any
) -> None:
    rows = [{**PRODUCT_ROW, "product_id": f"00000000-0000-4000-8000-{n:012d}"} for n in range(300)]
    whole = gz(json_body(rows))
    cut = whole[: len(whole) * 4 // 5]
    parts = [cut[i : i + 100] for i in range(0, len(cut), 100)]
    rig = rigs(flavor, lambda request: httpx.Response(200, headers=GZIP, stream=Watched(parts)))
    stream = rig.call("stream_products")
    seen: list[Any] = []

    with pytest.raises(TransportError, match="gzip"):
        rig.drain(stream, seen)

    assert seen  # the rows decoded before the break were delivered


@each_flavor
def test_products_have_no_body_size_limit(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(gz(json_body([PRODUCT_ROW] * 50)), **GZIP), max_body_bytes=100)

    assert len(rig.collect(rig.call("stream_products"))) == 50


@each_flavor
def test_the_stream_is_a_context_manager(flavor: Flavor, rigs: Any) -> None:
    body = Watched(product_json(50))
    rig = rigs(flavor, lambda request: httpx.Response(200, stream=body))
    stream = rig.call("stream_products")

    async def first_then_leave() -> Any:
        async with stream:
            return await stream.__anext__()

    if flavor.is_async:
        row = rig.run(first_then_leave())
    else:
        with stream:
            row = next(stream)

    assert row.product_id.endswith("000000")
    assert body.closed
