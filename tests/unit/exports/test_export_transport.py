"""The HTTP rules of the export client: statuses, retries, body checks, redirects, the cache,
`max_age` (SDK_SPEC 3.10 rules 2, 3, 7; 1.4). Every test runs for both flavors.
"""

import gzip
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from support.export_rig import (
    BASE,
    GZIP,
    META_BODY,
    PRICES_URL,
    RETRY_WAITS,
    Rig,
    gz,
    ok,
)
from support.exports import PRICES_BODY
from support.flavors import Flavor, each_flavor
from support.http import Chunks, reply
from whitemarket import NotModified, RetryPolicy
from whitemarket.errors import (
    AuthenticationError,
    DecodeError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.exports import ExportFormat, ExportKind, ExportValidators

RETRY_AFTER = {"Retry-After": "7"}


# --- statuses and retries --------------------------------------------------------------------

THREE = 3


def repeated(status: int, count: int = THREE, **headers: str) -> list[Any]:
    return [reply(status, b"", headers) for _ in range(count)]


@each_flavor
@pytest.mark.parametrize(
    ("script", "error", "attempts", "waits"),
    [
        pytest.param(repeated(503), ServiceUnavailableError, 3, RETRY_WAITS, id="503 x3"),
        pytest.param(repeated(500), ServerError, 3, RETRY_WAITS, id="500 retried"),
        pytest.param(repeated(429), RateLimitError, 3, RETRY_WAITS, id="429 retried"),
        pytest.param(repeated(501), ServerError, 3, RETRY_WAITS, id="501 retried (every 5xx)"),
        pytest.param(repeated(507), ServerError, 3, RETRY_WAITS, id="507 retried (every 5xx)"),
        pytest.param(repeated(599), ServerError, 3, RETRY_WAITS, id="599 retried (5xx bound)"),
        pytest.param(
            repeated(501, **RETRY_AFTER), ServerError, 3, RETRY_WAITS, id="501 + Retry-After"
        ),
        pytest.param(repeated(503, 1, **RETRY_AFTER), ServiceUnavailableError, 1, [], id="503 RA"),
        pytest.param(repeated(429, 1, **RETRY_AFTER), RateLimitError, 1, [], id="429 RA"),
        pytest.param([reply(404)], HttpError, 1, [], id="404 not retried"),
        pytest.param([reply(499)], HttpError, 1, [], id="499 not retried"),
        pytest.param([reply(600)], HttpError, 1, [], id="600 not retried"),
        pytest.param([reply(206, b"part")], HttpError, 1, [], id="206 is not a download"),
        pytest.param([reply(202, b"accepted")], HttpError, 1, [], id="202 is not a download"),
        pytest.param([reply(204)], HttpError, 1, [], id="204 is not a download"),
        pytest.param([reply(304)], HttpError, 1, [], id="304 to a plain call"),
        pytest.param([reply(302)], HttpError, 1, [], id="redirect without Location"),
    ],
)
def test_statuses_and_the_retry_table(
    flavor: Flavor,
    rigs: Any,
    *,
    script: list[Any],
    error: type[HttpError],
    attempts: int,
    waits: list[float],
) -> None:
    rig = rigs(flavor, *script)

    with pytest.raises(error) as caught:
        rig.prices()

    assert type(caught.value) is error
    assert (len(rig.requests), rig.sleeps) == (attempts, waits)


@each_flavor
def test_a_retry_after_header_is_kept_on_the_error(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, reply(429, b"", RETRY_AFTER))

    with pytest.raises(RateLimitError) as caught:
        rig.prices()

    assert caught.value.retry_after == 7


@each_flavor
def test_a_retry_that_succeeds_returns_the_file(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, reply(503), reply(500), ok(PRICES_BODY))

    assert len(rig.prices()) == 1
    assert (len(rig.requests), rig.sleeps) == (3, RETRY_WAITS)


@each_flavor
def test_the_attempts_follow_the_retry_policy(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, reply(500), retry=RetryPolicy(max_attempts=5, base_delay=0))

    with pytest.raises(ServerError):
        rig.prices()

    assert len(rig.requests) == 5


@each_flavor
def test_an_error_excerpt_is_redacted_and_bounded(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, reply(404, b'{"password": "hunter2", "message": "nope"}'))

    with pytest.raises(HttpError) as caught:
        rig.prices()

    assert "hunter2" not in caught.value.body_excerpt
    assert "nope" in caught.value.body_excerpt


# --- client failures -------------------------------------------------------------------------


class BoomError(Exception):
    """A client's own exception: it holds a request-like secret on purpose."""

    def __init__(self) -> None:
        super().__init__("synthetic middleware failure with SECRET-IN-MESSAGE")


def network_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@each_flavor
def test_a_network_error_is_retried_then_a_transport_error_without_a_cause(
    flavor: Flavor, rigs: Any
) -> None:
    rig = rigs(flavor, network_error)

    with pytest.raises(TransportError) as caught:
        rig.prices()

    assert (len(rig.requests), rig.sleeps) == (3, RETRY_WAITS)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "ConnectError" in str(caught.value)


@each_flavor
def test_a_network_error_that_clears_is_retried_into_success(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, network_error, ok(PRICES_BODY))

    assert len(rig.prices()) == 1


@each_flavor
def test_a_clients_own_exception_is_a_transport_error_without_a_cause_and_not_retried(
    flavor: Flavor, rigs: Any
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise BoomError

    rig = rigs(flavor, boom)

    with pytest.raises(TransportError) as caught:
        rig.prices()

    assert len(rig.requests) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SECRET-IN-MESSAGE" not in str(caught.value)


@each_flavor
def test_a_sdk_exception_from_the_client_is_a_transport_error_too(
    flavor: Flavor, rigs: Any
) -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        raise AuthenticationError(b"Bearer synthetic")

    rig = rigs(flavor, unauthorized)

    with pytest.raises(TransportError) as caught:
        rig.prices()

    assert (type(caught.value), len(rig.requests)) == (TransportError, 1)
    assert caught.value.__context__ is None


# --- the body --------------------------------------------------------------------------------


def stream_of(*parts: bytes, status: int = 200, headers: dict[str, str] | None = None) -> Any:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {}, stream=Chunks(parts))

    return answer


LIMIT = 200


def padded(call: str, size: int) -> bytes:
    core = META_BODY if call == "meta" else b"[]"
    return core + b" " * (size - len(core))


@each_flavor
@pytest.mark.parametrize("call", ["prices", "stream_prices", "meta"])
def test_a_body_of_exactly_max_body_bytes_decoded_is_read(
    flavor: Flavor, rigs: Any, call: str
) -> None:
    rig = rigs(flavor, ok(gz(padded(call, LIMIT)), **GZIP), max_body_bytes=LIMIT)

    assert rig.meta() if call == "meta" else rig.call(call) is not None


@each_flavor
@pytest.mark.parametrize("call", ["prices", "stream_prices", "meta"])
def test_a_body_one_byte_over_max_body_bytes_decoded_is_a_transport_error(
    flavor: Flavor, rigs: Any, call: str
) -> None:
    rig = rigs(flavor, ok(gz(padded(call, LIMIT + 1)), **GZIP), max_body_bytes=LIMIT)

    with pytest.raises(TransportError, match=f"longer than {LIMIT} bytes"):
        rig.meta() if call == "meta" else rig.call(call)


@each_flavor
def test_a_compressed_body_under_the_limit_that_expands_over_it_is_refused(
    flavor: Flavor, rigs: Any
) -> None:
    bomb = gz(b"[" + b" " * 10_000_000 + b"]")
    rig = rigs(flavor, ok(bomb, **GZIP), max_body_bytes=1000)

    with pytest.raises(TransportError, match="longer than 1000 bytes"):
        rig.prices()


EMPTY = b"[]"  # a valid file for both kinds
UNDECODABLE = [
    pytest.param(b"not gzip at all", GZIP, id="corrupt gzip"),
    pytest.param(gzip.compress(b"x" * 5000)[:20], GZIP, id="truncated gzip"),
    pytest.param(b"data", {"Content-Encoding": "br"}, id="unsupported encoding"),
    pytest.param(gzip.compress(EMPTY) + b"x", GZIP, id="trailing bytes after gzip"),
    pytest.param(gzip.compress(EMPTY) * 2, GZIP, id="second gzip member"),
    pytest.param(gzip.compress(EMPTY) + b"\x00" * 20, GZIP, id="zero padding after gzip"),
]


def run_call(rig: Rig, call: str, destination: Any) -> None:
    if call == "stream_products":
        rig.collect(rig.call("stream_products"))
    elif call == "download":
        rig.call("download", ExportKind.PRICES, 730, None, ExportFormat.JSON, destination)
    else:
        rig.prices()


@each_flavor
@pytest.mark.parametrize(("body", "headers"), UNDECODABLE)
@pytest.mark.parametrize("call", ["prices", "stream_products", "download"])
def test_an_undecodable_or_incomplete_body_is_a_transport_error(
    flavor: Flavor, rigs: Any, *, tmp_path: Any, call: str, body: bytes, headers: dict[str, str]
) -> None:
    rig = rigs(flavor, ok(body, **headers))

    with pytest.raises(TransportError) as caught:
        run_call(rig, call, tmp_path / "out.json")

    assert caught.value.__cause__ is None
    assert list(tmp_path.iterdir()) == []  # nothing renamed into place, no temporary file left


# --- Content-Length --------------------------------------------------------------------------


@each_flavor
@pytest.mark.parametrize("compressed", [False, True], ids=["identity", "gzip"])
@pytest.mark.parametrize(
    ("announce", "good"),
    [
        pytest.param(str, True, id="exact"),
        pytest.param(lambda n: f"{n}, {n}", True, id="identical repeats"),
        pytest.param(lambda n: str(n + 1), False, id="longer announced"),
        pytest.param(lambda n: str(n - 1), False, id="shorter announced"),
        pytest.param(lambda n: f"+{n}", False, id="plus sign"),
        pytest.param(lambda n: f"{n}, {n - 1}", False, id="different values"),
        pytest.param(lambda n: "abc", False, id="letters"),
        pytest.param(lambda n: "", False, id="empty"),
        pytest.param(lambda n: "1" * 19, False, id="19 digits"),
    ],
)
def test_content_length_must_match_the_raw_bytes(
    flavor: Flavor, rigs: Any, compressed: bool, announce: Callable[[int], str], good: bool
) -> None:
    raw = gz(PRICES_BODY) if compressed else PRICES_BODY
    headers = {"Content-Length": announce(len(raw)), **(GZIP if compressed else {})}
    # A scripted body is not checked by httpx itself, so the SDK's own check is what is tested.
    rig = rigs(flavor, stream_of(raw[:10], raw[10:], headers=headers))

    if good:
        assert len(rig.prices()) == 1
        return
    with pytest.raises(TransportError):
        rig.prices()


@each_flavor
def test_a_response_without_content_length_is_not_checked(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, stream_of(PRICES_BODY[:5], PRICES_BODY[5:]))

    assert len(rig.prices()) == 1


# --- redirects -------------------------------------------------------------------------------


def redirect(location: str, status: int = 302) -> Any:
    return reply(status, b"", {"Location": location})


@each_flavor
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        pytest.param("/v1/other/730.json", id="absolute path"),
        pytest.param(f"{BASE}/v1/other/730.json", id="same origin URL"),
        pytest.param("https://EXPORT.test/v1/other/730.json", id="host in upper case"),
        pytest.param("https://export.test:443/v1/other/730.json", id="explicit default port"),
    ],
)
def test_a_redirect_to_the_same_host_and_port_over_https_is_followed(
    flavor: Flavor, rigs: Any, status: int, location: str
) -> None:
    rig = rigs(flavor, redirect(location, status), ok(PRICES_BODY))

    assert len(rig.prices()) == 1
    assert [r.url.host for r in rig.requests] == ["export.test", "export.test"]
    assert rig.requests[1].url.path == "/v1/other/730.json"


@each_flavor
def test_three_redirects_are_followed_and_a_fourth_is_not(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, redirect("/a"), redirect("/b"), redirect("/c"), ok(PRICES_BODY))
    assert len(rig.prices()) == 1
    assert len(rig.requests) == 4

    rig = rigs(
        flavor, redirect("/a"), redirect("/b"), redirect("/c"), redirect("/d"), ok(PRICES_BODY)
    )
    with pytest.raises(TransportError, match="more than 3 times") as caught:
        rig.prices()

    assert len(rig.requests) == 4  # no fifth request
    assert caught.value.__cause__ is None


REFUSED = [
    pytest.param("https://evil.example.test/v1/prices/730.json", "another host", id="other host"),
    pytest.param("https://sub.export.test/x", "another host", id="subdomain"),
    pytest.param("https://export.test.evil.example.test/x", "another host", id="lookalike"),
    pytest.param("https://export.test:8443/x", "another host", id="other port"),
    pytest.param("https://export.test:444/x", "another host", id="port next to the default"),
    pytest.param("http://export.test/x", "not an https URL", id="plain http"),
    pytest.param("//evil.example.test/x", "not an https URL", id="protocol-relative"),
    pytest.param("x/y.json", "not an https URL", id="relative without a slash"),
    pytest.param("https://user:pass@export.test/x", "not an https URL", id="credentials"),
    pytest.param("https://user@export.test/x", "not an https URL", id="user only"),
    pytest.param("https://:pass@export.test/x", "not an https URL", id="password only"),
    pytest.param("HTTPS://export.test/x", "not an https URL", id="upper-case scheme"),
    pytest.param("ftp://export.test/x", "not an https URL", id="other scheme"),
    pytest.param("/x y", "invalid location", id="whitespace"),
]


@each_flavor
@pytest.mark.parametrize(("location", "reason"), REFUSED)
def test_any_other_redirect_is_a_transport_error_and_nothing_is_sent_there(
    flavor: Flavor, rigs: Any, location: str, reason: str
) -> None:
    rig = rigs(flavor, redirect(location), ok(PRICES_BODY))

    with pytest.raises(TransportError, match=reason) as caught:
        rig.prices()

    assert len(rig.requests) == 1
    assert caught.value.__cause__ is None
    assert location not in str(caught.value)  # server input is not echoed


INJECTED_CLIENT_OPTIONS = [
    pytest.param({"follow_redirects": True}, id="client that follows redirects"),
    pytest.param(
        {
            "headers": {"Authorization": "Bearer LEAK", "X-Partner-Token": "LEAK"},
            "cookies": {"session": "LEAK"},
            "auth": httpx.BasicAuth("user", "LEAK"),
        },
        id="client with default credentials",
    ),
]


@each_flavor
@pytest.mark.parametrize("options", INJECTED_CLIENT_OPTIONS)
def test_an_injected_client_neither_follows_a_redirect_nor_sends_its_credentials(
    flavor: Flavor, rigs: Any, options: dict[str, Any]
) -> None:
    rig = rigs(
        flavor,
        redirect("https://other.test/v1/x"),
        ok(PRICES_BODY),
        client_options={"follow_redirects": True, **options},
    )

    with pytest.raises(TransportError, match="another host"):
        rig.prices()

    assert [r.url.host for r in rig.requests] == ["export.test"], "the redirect was not followed"
    sent = rig.requests[0].headers
    assert not {"authorization", "x-partner-token", "cookie"} & set(sent.keys())


@each_flavor
def test_a_redirect_on_a_custom_port_stays_on_that_port(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, redirect("/v1/x"), ok(PRICES_BODY), base_url="https://export.test:8443")

    rig.prices()

    assert rig.urls[1] == "https://export.test:8443/v1/x"


@each_flavor
def test_the_redirect_target_gets_the_same_headers(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, redirect("/v1/x"), ok(PRICES_BODY))

    rig.prices()

    assert rig.requests[1].headers["accept-encoding"] == "gzip"
    assert "authorization" not in rig.requests[1].headers


# --- the conditional cache -------------------------------------------------------------------


@pytest.fixture
def make_cache() -> Callable[[Flavor], Any]:
    return lambda flavor: flavor.cls("export_cache", "InMemoryExportCache")()


@each_flavor
def test_a_conditional_call_without_a_cache_is_an_argument_error(flavor: Flavor, rigs: Any) -> None:
    rig = rigs(flavor, ok(PRICES_BODY))

    with pytest.raises(ValueError, match="needs a cache"):
        rig.prices(conditional=True)

    assert rig.requests == []


@each_flavor
def test_the_validators_of_a_parsed_200_are_stored_and_sent_next_time(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    cache = make_cache(flavor)
    rig = rigs(
        flavor,
        ok(PRICES_BODY, ETag='"abc"', **{"Last-Modified": "Fri, 06 Nov 2026 11:00:00 GMT"}),
        reply(304),
        cache=cache,
    )

    first = rig.prices(conditional=True)
    second = rig.prices(conditional=True)

    assert len(first) == 1
    assert second == NotModified(PRICES_URL)
    assert "if-none-match" not in rig.requests[0].headers
    assert rig.requests[1].headers["if-none-match"] == '"abc"'
    assert rig.requests[1].headers["if-modified-since"] == "Fri, 06 Nov 2026 11:00:00 GMT"
    assert len(rig.requests) == 2


@each_flavor
def test_only_the_validators_the_server_sent_are_sent_back(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    rig = rigs(flavor, ok(PRICES_BODY, ETag='"abc"'), reply(304), cache=make_cache(flavor))

    rig.prices(conditional=True)
    rig.prices(conditional=True)

    assert rig.requests[1].headers["if-none-match"] == '"abc"'
    assert "if-modified-since" not in rig.requests[1].headers


@each_flavor
def test_a_later_200_without_validators_forgets_the_old_ones(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    rig = rigs(
        flavor,
        ok(PRICES_BODY, ETag='"abc"'),
        ok(PRICES_BODY),
        ok(PRICES_BODY),
        cache=make_cache(flavor),
    )

    rig.prices(conditional=True)
    rig.prices(conditional=True)  # sends "abc"; the 200 answer carries no validator
    rig.prices(conditional=True)

    assert rig.requests[1].headers["if-none-match"] == '"abc"'
    assert "if-none-match" not in rig.requests[2].headers


@each_flavor
def test_a_304_without_validators_sent_is_an_http_error(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    rig = rigs(flavor, reply(304), cache=make_cache(flavor))

    with pytest.raises(HttpError) as caught:
        rig.prices(conditional=True)

    assert caught.value.status == 304


@each_flavor
def test_validators_of_a_body_that_failed_to_parse_are_not_stored(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    cache = make_cache(flavor)
    rig = rigs(flavor, ok(b"not json", ETag='"bad"'), ok(PRICES_BODY), cache=cache)

    with pytest.raises(DecodeError, match="prices"):
        rig.prices(conditional=True)
    again = rig.prices(conditional=True)

    assert len(again) == 1  # not NotModified
    assert "if-none-match" not in rig.requests[1].headers
    assert rig.run(cache.get(PRICES_URL)) is None


@each_flavor
def test_a_plain_call_never_touches_the_cache(flavor: Flavor, rigs: Any, make_cache: Any) -> None:
    cache = make_cache(flavor)
    rig = rigs(flavor, ok(PRICES_BODY, ETag='"abc"'), cache=cache)

    rig.prices()

    assert rig.run(cache.get(PRICES_URL)) is None


@each_flavor
def test_a_body_without_validators_stores_nothing(
    flavor: Flavor, rigs: Any, make_cache: Any
) -> None:
    cache = make_cache(flavor)
    rig = rigs(flavor, ok(PRICES_BODY), cache=cache)

    rig.prices(conditional=True)

    assert rig.run(cache.get(PRICES_URL)) is None


WRONG_TYPES: dict[str, Any] = {"etag": 5, "last_modified": ["x"]}


@each_flavor
@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(ExportValidators(etag='"a"\r\nX-Injected: 1'), id="header injection"),
        pytest.param(ExportValidators(etag=" padded "), id="padded value"),
        pytest.param(ExportValidators(**WRONG_TYPES), id="wrong types"),
        pytest.param(ExportValidators(), id="empty"),
        pytest.param("a string", id="not validators"),
        pytest.param(None, id="nothing"),
    ],
)
def test_an_unusable_cache_entry_is_ignored(
    flavor: Flavor, rigs: Any, make_cache: Any, entry: Any
) -> None:
    cache = make_cache(flavor)
    rig = rigs(flavor, ok(PRICES_BODY), cache=cache)
    rig.run(cache.set(PRICES_URL, entry))

    assert len(rig.prices(conditional=True)) == 1
    assert "if-none-match" not in rig.requests[0].headers
    assert "x-injected" not in rig.requests[0].headers


class SyncBrokenCache:
    def get(self, url: str) -> Any:
        raise RuntimeError("cache down SECRET-IN-CACHE")

    def set(self, url: str, validators: Any) -> None:
        raise RuntimeError("cache down SECRET-IN-CACHE")


class AsyncBrokenCache:
    async def get(self, url: str) -> Any:
        raise RuntimeError("cache down SECRET-IN-CACHE")

    async def set(self, url: str, validators: Any) -> None:
        raise RuntimeError("cache down SECRET-IN-CACHE")


@each_flavor
def test_a_cache_that_fails_is_not_an_export_failure(
    flavor: Flavor, rigs: Any, caplog: pytest.LogCaptureFixture
) -> None:
    rig = rigs(
        flavor,
        ok(PRICES_BODY, ETag='"abc"'),
        cache=AsyncBrokenCache() if flavor.is_async else SyncBrokenCache(),
    )

    with caplog.at_level("WARNING", logger="whitemarket"):
        assert len(rig.prices(conditional=True)) == 1

    assert "SECRET-IN-CACHE" not in caplog.text
    assert "cache read failed" in caplog.text
    assert "cache write failed" in caplog.text
