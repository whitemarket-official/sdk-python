"""The pure rules of export redirects, URLs and freshness limits (SDK_SPEC 3.10 rules 2, 5)."""

from datetime import timedelta
from typing import Any

import pytest

from whitemarket._runtime import endpoints
from whitemarket._runtime.export_redirect import Origin, redirect_target
from whitemarket._runtime.export_urls import export_file_url, max_age_seconds
from whitemarket.errors import TransportError
from whitemarket.exports import ExportFormat, ExportKind, ExportWindow

ORIGIN = Origin("https", "export.test", 443)


@pytest.mark.parametrize(
    ("base", "location", "target"),
    [
        pytest.param("https://export.test", "/v1/a", "https://export.test/v1/a", id="path"),
        pytest.param("https://export.test:443", "/v1/a", "https://export.test/v1/a", id="443"),
        pytest.param(
            "https://export.test:8443", "/v1/a", "https://export.test:8443/v1/a", id="port"
        ),
        pytest.param("https://export.test:444", "/v1/a", "https://export.test:444/v1/a", id="444"),
        pytest.param("https://EXPORT.test", "/v1/a", "https://export.test/v1/a", id="lower case"),
        pytest.param("https://export.test", "/a?b=c", "https://export.test/a?b=c", id="query"),
        pytest.param(
            "https://export.test", "https://export.test/z", "https://export.test/z", id="absolute"
        ),
        pytest.param(
            "https://export.test:8443",
            "https://export.test:8443/z",
            "https://export.test:8443/z",
            id="absolute with the port",
        ),
    ],
)
def test_a_redirect_target_on_the_origin_is_accepted(base: str, location: str, target: str) -> None:
    origin = Origin.of(base)
    assert origin is not None

    assert redirect_target(location, origin) == target


@pytest.mark.parametrize(
    "location",
    [
        "/x\x00y",
        "/x\ty",
        "/x\ny",
        "/x y",
        "",
        "/café",
        "https://export.test/x\r\nX-Injected: 1",
        "http://export.test/x",
        "//export.test/x",
        "https://export.test@evil.example.test/x",
        "https://export.test:99999/x",
        "https://export.test:abc/x",
    ],
)
def test_a_location_that_is_not_a_clean_same_origin_https_url_is_refused(location: str) -> None:
    with pytest.raises(TransportError) as caught:
        redirect_target(location, ORIGIN)

    assert caught.value.__cause__ is None


def test_the_scheme_check_follows_the_origin_schemes_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Origin.of("http://export.test") is None
    monkeypatch.setattr(endpoints, "_ORIGIN_SCHEMES", ("https", "http"))

    assert Origin.of("http://export.test") == Origin("http", "export.test", 80)
    assert redirect_target("/x", Origin("http", "export.test", 80)) == "http://export.test/x"
    with pytest.raises(TransportError):
        redirect_target("https://export.test/x", Origin("http", "export.test", 80))


@pytest.mark.parametrize(
    ("window", "format", "kind", "path"),
    [
        (None, ExportFormat.JSON, ExportKind.PRICES, "prices/730.json"),
        (ExportWindow.HOUR1, ExportFormat.CSV, ExportKind.PRODUCTS, "products/730.1hour.csv"),
    ],
)
def test_the_file_url(
    window: ExportWindow | None, format: ExportFormat, kind: ExportKind, path: str
) -> None:
    assert (
        export_file_url("https://x.test/", kind, 730, window, format) == f"https://x.test/v1/{path}"
    )


@pytest.mark.parametrize(
    ("max_age", "seconds"),
    [
        (None, None),
        (0, 0.0),
        (60, 60.0),
        (1.5, 1.5),
        (timedelta(minutes=2), 120.0),
    ],
)
def test_max_age_in_seconds(max_age: timedelta | float | None, seconds: float | None) -> None:
    assert max_age_seconds(max_age) == seconds


@pytest.mark.parametrize(
    ("max_age", "error"),
    [
        (-1, ValueError),
        (timedelta(seconds=-1), ValueError),
        (float("nan"), ValueError),
        (True, TypeError),
    ],
)
def test_an_invalid_max_age_is_refused(max_age: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        max_age_seconds(max_age)
