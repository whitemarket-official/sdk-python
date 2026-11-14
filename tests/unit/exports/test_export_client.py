"""The export client, sync and async twins, on a scripted HTTP client (SDK_SPEC 3.10, 1.3, 1.4).

Port of the HTTP-side cases of the PHP ExportClientTest / ExportTransportTest.
"""

from datetime import timedelta
from typing import Any

import pytest

from support.export_rig import (
    BASE,
    GZIP,
    META_BODY,
    gz,
    ok,
)
from support.exports import PRICE_ROW, PRICES_BODY, fixture, json_body
from support.flavors import Flavor, each_flavor
from support.http import reply
from whitemarket import ExportOptions
from whitemarket.errors import (
    DecodeError,
    HttpError,
)
from whitemarket.exports import ExportFormat, ExportKind, ExportWindow, PriceList

# --- URLs and arguments ----------------------------------------------------------------------


@each_flavor
@pytest.mark.parametrize(
    ("window", "suffix"),
    [
        pytest.param(None, "", id="default window"),
        pytest.param(ExportWindow.ALL, "", id="all"),
        pytest.param(ExportWindow.MINUTES10, ".10min", id="10 minutes"),
        pytest.param(ExportWindow.HOUR1, ".1hour", id="1 hour"),
        pytest.param(ExportWindow.HOURS12, ".12hours", id="12 hours"),
        pytest.param(ExportWindow.HOURS24, ".24hours", id="24 hours"),
    ],
)
def test_prices_url_follows_the_window(flavor: Flavor, rigs: Any, window: Any, suffix: str) -> None:
    rig = rigs(flavor, ok(PRICES_BODY))

    rig.prices(window=window)

    assert rig.urls == [f"{BASE}/v1/prices/730{suffix}.json"]


@each_flavor
@pytest.mark.parametrize("app", [1, 730, 2**31 - 1])
def test_a_valid_app_id_is_in_the_url(flavor: Flavor, rigs: Any, app: int) -> None:
    rig = rigs(flavor, ok(PRICES_BODY))

    rig.prices(app=app)

    assert rig.urls == [f"{BASE}/v1/prices/{app}.json"]


@each_flavor
@pytest.mark.parametrize(
    ("app", "error"),
    [
        pytest.param(0, ValueError, id="zero"),
        pytest.param(-1, ValueError, id="negative"),
        pytest.param(2**31, ValueError, id="one over the range"),
        pytest.param(True, TypeError, id="a bool"),
    ],
)
def test_an_invalid_app_id_fails_before_any_request(
    flavor: Flavor, rigs: Any, app: Any, error: type[Exception]
) -> None:
    rig = rigs(flavor, ok(PRICES_BODY))

    for method in ("prices", "stream_prices", "stream_products"):
        with pytest.raises(error):
            rig.call(method, app=app)
    with pytest.raises(error):
        rig.meta(app=app)
    with pytest.raises(error):
        rig.call("download", ExportKind.PRICES, app, None, ExportFormat.JSON, "unused")

    assert rig.requests == []


@each_flavor
@pytest.mark.parametrize(
    ("kind", "format", "path"),
    [
        pytest.param(ExportKind.PRICES, ExportFormat.JSON, "prices/730.json", id="prices json"),
        pytest.param(ExportKind.PRICES, ExportFormat.CSV, "prices/730.csv", id="prices csv"),
        pytest.param(ExportKind.PRODUCTS, ExportFormat.JSON, "products/730.json", id="products"),
    ],
)
def test_meta_asks_for_the_sidecar_of_the_file(
    flavor: Flavor, rigs: Any, kind: ExportKind, format: ExportFormat, path: str
) -> None:
    rig = rigs(flavor, ok(META_BODY))

    meta = rig.meta(kind, format=format)

    assert rig.urls == [f"{BASE}/v1/{path}.meta.json"]
    assert (meta.file, meta.items) == ("730.json", 4)
    assert meta.data_as_of.isoformat() == "2026-11-06T11:50:00+00:00"


@pytest.mark.parametrize(
    "base_url",
    [
        pytest.param("http://export.test", id="plain http"),
        pytest.param("https://export.test/v1", id="with a path"),
        pytest.param("https://user:pw@export.test", id="with credentials"),
        pytest.param("export.test", id="no scheme"),
    ],
)
def test_the_base_url_must_be_an_https_origin(base_url: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        ExportOptions(base_url=base_url)


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"connect_timeout": 0}, id="connect"),
        pytest.param({"idle_timeout": -1}, id="idle"),
        pytest.param({"max_body_bytes": 0}, id="body limit"),
        pytest.param({"user_agent_suffix": "bad\nvalue"}, id="user agent"),
    ],
)
def test_invalid_options_are_refused(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"."):
        ExportOptions(**options)


# --- requests --------------------------------------------------------------------------------


@each_flavor
def test_a_request_asks_for_gzip_and_carries_no_credential(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(META_BODY), ok(PRICES_BODY), user_agent_suffix="app/1")

    rig.prices(max_age=timedelta(hours=1))

    assert len(rig.requests) == 2
    for request in rig.requests:
        assert request.method == "GET"
        assert request.headers["accept-encoding"] == "gzip"
        assert request.headers["user-agent"].startswith("whitemarket-sdk-python/")
        assert request.headers["user-agent"].endswith(" app/1")
        # Only what httpx and the SDK add: no Authorization, no X-partner-token, no cookie.
        assert set(request.headers) <= {
            "host",
            "accept",
            "connection",
            "accept-encoding",
            "user-agent",
        }


@each_flavor
def test_prices_returns_the_parsed_list(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(fixture("prices.json")))

    prices = rig.prices()

    assert isinstance(prices, PriceList)
    assert len(prices) == 4


@each_flavor
def test_a_gzip_body_is_decoded(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(gz(PRICES_BODY), **GZIP))

    assert len(rig.prices()) == 1


@each_flavor
def test_stream_prices_gives_the_rows_in_file_order(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(fixture("prices.json")))

    rows = rig.collect(rig.call("stream_prices"))

    assert [row.paint_index for row in rows][:2] == ["282", "0"]
    assert len(rows) == 4


@each_flavor
def test_stream_prices_sends_its_request_when_called_and_fails_there(
    flavor: Flavor, rigs: Any
) -> None:
    rig = rigs(flavor, reply(404))

    with pytest.raises(HttpError) as error:
        rig.call("stream_prices")

    assert error.value.status == 404


@each_flavor
def test_a_body_that_is_not_the_expected_json_is_a_decode_error_with_a_path(
    flavor: Flavor, rigs: Any
) -> None:
    rig = rigs(flavor, ok(json_body([PRICE_ROW, {**PRICE_ROW, "price": 1}])))

    with pytest.raises(DecodeError) as error:
        rig.prices()

    assert str(error.value).startswith("prices[1].price: ")


# --- products --------------------------------------------------------------------------------


@each_flavor
@pytest.mark.parametrize("format", list(ExportFormat))
def test_stream_products_gives_the_rows_of_both_formats(
    flavor: Flavor, rigs: Any, format: ExportFormat
) -> None:
    rig = rigs(flavor, ok(gz(fixture(f"products.{format.value}")), **GZIP))

    rows = rig.collect(rig.call("stream_products", format=format))

    assert rig.urls == [f"{BASE}/v1/products/730.{format.value}"]
    assert rows
    assert all(row.price.amount > 0 for row in rows)


@each_flavor
def test_stream_products_sends_its_request_when_called_and_fails_there(
    flavor: Flavor, rigs: Any
) -> None:
    rig = rigs(flavor, reply(404))

    with pytest.raises(HttpError) as error:
        rig.call("stream_products")

    assert error.value.status == 404
