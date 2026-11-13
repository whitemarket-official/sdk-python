"""The GraphQL transport, sync and async twins: statuses, retries, limits, logging.

Port of the PHP HttpTransportTest cases. Every test runs for both flavors.
"""

import gzip
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from support.flavors import FLAVORS, Flavor
from support.http import Chunks, Script, data, reply
from whitemarket import RetryPolicy, Secret, Timeouts
from whitemarket._runtime.transport_config import TransportConfig
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)

URL = "https://api.test/graphql/partner"
NOW = datetime(2026, 11, 6, 7, 28, 0, tzinfo=UTC)
AUTH = {"Authorization": Secret("Bearer SECRET-ACCESS-TOKEN")}

each_flavor = pytest.mark.parametrize("flavor", FLAVORS, ids=lambda f: f.name)


class Rig:
    """A transport on a scripted httpx client, with injected clock, sleeper and random source."""

    def __init__(
        self,
        flavor: Flavor,
        *outcomes: Any,
        retry: RetryPolicy | None = None,
        owned: bool = False,
        jitter: float = 1.0,
        max_response_bytes: int = 1000,
        logger: logging.Logger | None = None,
        timeouts: Timeouts | None = None,
    ) -> None:
        self.flavor = flavor
        self.script = Script(*outcomes)
        self.sleeps: list[float] = []
        self.http = flavor.mock_http(self.script)
        clients = flavor.cls("transport", "HttpClients")(self.http, self.http, owned=owned)
        config = TransportConfig(
            graphql_url=URL,
            retry=retry or RetryPolicy(),
            max_response_bytes=max_response_bytes,
            timeouts=timeouts or Timeouts(),
        )
        self.transport = flavor.cls("transport", "GraphQLTransport")(
            clients,
            config,
            logger=logger,
            seams=flavor.cls("transport", "TransportSeams")(
                clock=lambda: NOW, sleeper=flavor.sleeper(self.sleeps), random=lambda: jitter
            ),
        )

    def post(self, kind: str = "query", headers: Any = AUTH, body: bytes = b'{"query":"q"}') -> Any:
        result = self.transport.post("Op", kind, body, headers)
        return self.flavor.run(result)

    def close(self) -> None:
        self.flavor.close(self.http)


@pytest.fixture
def rig(flavor: Flavor) -> Any:
    rigs: list[Rig] = []

    def make(*outcomes: Any, **kwargs: Any) -> Rig:
        made = Rig(flavor, *outcomes, **kwargs)
        rigs.append(made)
        return made

    yield make
    for made in rigs:
        made.close()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames:
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param(400, BadRequestError, id="400 bad request"),
        pytest.param(401, AuthenticationError, id="401 authentication"),
        pytest.param(403, HttpError, id="403 other 4xx"),
        pytest.param(404, HttpError, id="404 other 4xx"),
        pytest.param(429, RateLimitError, id="429 rate limit"),
        pytest.param(500, ServerError, id="500 server"),
        pytest.param(501, ServerError, id="501 other 5xx"),
        pytest.param(502, ServerError, id="502 server"),
        pytest.param(503, ServiceUnavailableError, id="503 unavailable"),
        pytest.param(504, ServerError, id="504 server"),
        pytest.param(599, ServerError, id="599 server"),
        pytest.param(301, HttpError, id="301 redirect is an error"),
        pytest.param(302, HttpError, id="302 redirect is an error"),
        pytest.param(307, HttpError, id="307 redirect is an error"),
        pytest.param(308, HttpError, id="308 redirect is an error"),
        pytest.param(304, HttpError, id="304 is an error for a POST"),
    ],
)
def test_the_status_table(rig: Any, status: int, expected: type[HttpError]) -> None:
    r = rig(
        reply(status, b'{"error":"x"}', headers={"Location": "https://evil/"}),
        retry=RetryPolicy.none(),
    )

    with pytest.raises(HttpError) as caught:
        r.post()

    assert type(caught.value) is expected
    assert caught.value.status == status
    assert r.script.count == 1


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_any_2xx_returns_the_body(rig: Any, status: int) -> None:
    r = rig(reply(status, b'{"data":{}}'))

    assert r.post() == b'{"data":{}}'


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_query_is_repeated_on_a_transient_status_with_backoff(rig: Any, status: int) -> None:
    r = rig(reply(status), data(ok=1), jitter=0.5)

    assert r.post() == b'{"data": {"ok": 1}}'
    assert r.script.count == 2
    assert r.sleeps == [0.25]


def test_the_backoff_grows_with_each_attempt_and_stops_at_the_last(rig: Any) -> None:
    r = rig(reply(503), retry=RetryPolicy(max_attempts=4, max_delay=1.5), jitter=1.0)

    with pytest.raises(ServiceUnavailableError) as caught:
        r.post()

    assert r.script.count == 4
    assert r.sleeps == [0.5, 1.0, 1.5], "doubling, then the cap; no sleep after the last attempt"
    assert caught.value.retry_after is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 501, 505, 301])
def test_other_statuses_are_not_repeated(rig: Any, status: int) -> None:
    r = rig(reply(status))

    with pytest.raises(HttpError):
        r.post()

    assert r.script.count == 1
    assert r.sleeps == []


def test_a_network_error_before_a_response_is_repeated_for_a_query(rig: Any) -> None:
    r = rig(httpx.ConnectError("boom"), httpx.ReadTimeout("slow"), data(ok=1))

    assert r.post() == b'{"data": {"ok": 1}}'
    assert r.script.count == 3


def test_the_last_network_error_is_a_transport_error_without_the_request(rig: Any) -> None:
    r = rig(httpx.ConnectError("connect failed to host with SECRET-ACCESS-TOKEN"))

    with pytest.raises(TransportError) as caught:
        r.post()

    error = caught.value
    assert r.script.count == 3
    assert "SECRET-ACCESS-TOKEN" not in str(error)
    assert error.__context__ is None
    assert error.__cause__ is None
    assert "ConnectError" in str(error)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(reply(503), id="503"),
        pytest.param(reply(429), id="429"),
        pytest.param(reply(500), id="500"),
        pytest.param(httpx.ConnectError("x"), id="network error"),
        pytest.param(httpx.ReadTimeout("x"), id="timeout"),
    ],
)
def test_a_mutation_is_sent_exactly_once(rig: Any, failure: Any) -> None:
    r = rig(failure)

    with pytest.raises((HttpError, TransportError)):
        r.post("mutation")

    assert r.script.count == 1
    assert r.sleeps == []


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        pytest.param("7", 7, id="seconds"),
        pytest.param("0", 0, id="zero seconds"),
        pytest.param("Fri, 06 Nov 2026 07:28:45 GMT", 45, id="http date"),
        pytest.param("Fri, 06 Nov 2026 07:00:00 GMT", 0, id="date in the past"),
    ],
)
def test_retry_after_on_429_and_503_stops_the_query_at_once(
    rig: Any, status: int, header: str, seconds: int
) -> None:
    r = rig(reply(status, headers={"Retry-After": header}))

    with pytest.raises((RateLimitError, ServiceUnavailableError)) as caught:
        r.post()

    assert r.script.count == 1
    assert r.sleeps == [], "the SDK never waits for a server-chosen time"
    assert caught.value.retry_after == seconds
    assert type(caught.value) is (RateLimitError if status == 429 else ServiceUnavailableError)


@pytest.mark.parametrize("status", [429, 503])
def test_an_unparsable_retry_after_is_as_good_as_none(rig: Any, status: int) -> None:
    r = rig(reply(status, headers={"Retry-After": "soon"}), data(ok=1))

    assert r.post()
    assert r.script.count == 2


@pytest.mark.parametrize("status", [500, 502, 504])
def test_other_statuses_ignore_retry_after(rig: Any, status: int) -> None:
    r = rig(reply(status, headers={"Retry-After": "7"}), data(ok=1))

    assert r.post()
    assert r.script.count == 2
    assert r.sleeps == [0.5]


def test_a_400_carries_no_retry_after(rig: Any) -> None:
    r = rig(reply(400, headers={"Retry-After": "7"}))

    with pytest.raises(BadRequestError) as caught:
        r.post()

    assert not hasattr(caught.value, "retry_after")


def test_the_request_carries_the_sdk_headers_and_the_credential(rig: Any) -> None:
    r = rig(data(ok=1))

    r.post(headers={"X-partner-token": Secret("PARTNER-VALUE")}, body=b'{"query":"q"}')

    (request,) = r.script.requests
    assert (request.method, str(request.url)) == ("POST", URL)
    assert request.content == b'{"query":"q"}'
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept"] == "application/json"
    assert request.headers["accept-encoding"] == "gzip"
    assert request.headers["x-partner-token"] == "PARTNER-VALUE"
    assert "authorization" not in request.headers
    assert re.fullmatch(
        r"whitemarket-sdk-python/\S+ \((CPython|PyPy)/\d+\.\d+\.\d+\)",
        request.headers["user-agent"],
    )


def test_the_body_limit_boundary_and_it_holds_while_streaming(rig: Any) -> None:
    exact = b"x" * 1000
    assert rig(reply(200, content=exact)).post() == exact

    stream = Chunks([b"x" * 400] * 50)
    r = rig(lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(TransportError, match="longer than 1000"):
        r.post()
    assert stream.served <= 1200, "reading stopped near the limit, not after the whole body"
    assert r.script.count == 1, "a body over the limit is not retried"


def test_a_gzip_body_is_decoded_and_the_limit_counts_decompressed_bytes(rig: Any) -> None:
    packed = gzip.compress(b'{"data":{"k":1}}')
    headers = {"Content-Encoding": "gzip"}
    assert rig(reply(200, content=packed, headers=headers)).post() == b'{"data":{"k":1}}'

    bomb = gzip.compress(b"\0" * 100_000)
    assert len(bomb) < 1000
    with pytest.raises(TransportError, match="longer than 1000"):
        rig(reply(200, content=bomb, headers=headers)).post()


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            reply(200, content=b"nope", headers={"Content-Encoding": "gzip"}),
            id="corrupt gzip",
        ),
        pytest.param(
            reply(200, content=b"x", headers={"Content-Encoding": "br"}),
            id="unsupported encoding",
        ),
    ],
)
def test_an_undecodable_body_is_a_transport_error_not_a_retry(rig: Any, response: Any) -> None:
    r = rig(response)

    with pytest.raises(TransportError):
        r.post()

    assert r.script.count == 1


def test_an_error_body_is_bounded_and_an_unreadable_one_still_maps_the_status(rig: Any) -> None:
    huge = reply(400, content=b"x" * 3_000_000)
    with pytest.raises(BadRequestError) as caught:
        rig(huge, retry=RetryPolicy.none()).post()
    assert len(caught.value.body_excerpt.encode()) <= 512

    broken = reply(502, content=b"nope", headers={"Content-Encoding": "gzip"})
    with pytest.raises(ServerError) as server:
        rig(broken, retry=RetryPolicy.none()).post()
    assert server.value.status == 502


def test_an_error_excerpt_hides_credentials(rig: Any) -> None:
    body = b'{"error":{"code":401,"message":"Expired JWT Token","token":"LEAKED-VALUE"}}'

    with pytest.raises(BadRequestError) as caught:
        rig(reply(400, content=body)).post()

    assert "LEAKED-VALUE" not in caught.value.body_excerpt
    assert "LEAKED-VALUE" not in str(caught.value)
    assert caught.value.body_excerpt != ""


def test_the_debug_log_never_holds_a_credential_but_does_hold_the_attempt(
    rig: Any, caplog: pytest.LogCaptureFixture
) -> None:
    secrets = {
        "Authorization": Secret("Bearer SECRET-ACCESS-TOKEN"),
        "X-partner-token": Secret("PARTNER-SECRET-VALUE"),
    }
    r = rig(reply(503), data(ok=1))

    with caplog.at_level(logging.DEBUG, logger="whitemarket"):
        r.post(headers=secrets, body=b'{"query":"auth_token SECRET-IN-BODY"}')

    text = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "operation=Op" in text
    assert "status=503" in text
    assert "status=200" in text
    for secret in ("SECRET-ACCESS-TOKEN", "PARTNER-SECRET-VALUE", "SECRET-IN-BODY"):
        assert secret not in text


def test_a_logger_that_raises_never_changes_the_outcome(rig: Any) -> None:
    class Broken(logging.Logger):
        def debug(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("logger down")

        def info(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("logger down")

    r = rig(reply(503), data(ok=1), logger=Broken("broken"))

    assert r.post()


def test_an_injected_client_gets_one_notice_and_an_owned_one_none(
    flavor: Flavor, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="whitemarket"):
        injected = Rig(flavor, data(ok=1), owned=False)
        injected.post()
        injected.post()
        owned = Rig(flavor, data(ok=1), owned=True)
        owned.post()
    notices = [r for r in caplog.records if "injected HTTP client" in r.getMessage()]
    injected.close()
    owned.close()

    assert len(notices) == 1
    assert notices[0].levelno == logging.INFO


def test_a_mutation_on_an_owned_client_goes_through_the_mutation_client_and_closes_the_connection(
    flavor: Flavor,
) -> None:
    query_script, mutation_script = Script(data(ok=1)), Script(data(ok=1))
    query_http, mutation_http = flavor.mock_http(query_script), flavor.mock_http(mutation_script)
    clients = flavor.cls("transport", "HttpClients")(query_http, mutation_http, owned=True)
    transport = flavor.cls("transport", "GraphQLTransport")(
        clients, TransportConfig(graphql_url=URL)
    )

    flavor.run(transport.post("Op", "query", b"{}", AUTH))
    flavor.run(transport.post("Op", "mutation", b"{}", AUTH))
    flavor.close(query_http)
    flavor.close(mutation_http)

    assert (query_script.count, mutation_script.count) == (1, 1)
    assert query_script.requests[0].headers["connection"] == "keep-alive"
    assert mutation_script.requests[0].headers["connection"] == "close"


def test_an_injected_client_is_not_changed_and_not_closed(flavor: Flavor) -> None:
    r = Rig(flavor, data(ok=1))
    clients = flavor.cls("transport", "HttpClients")(r.http, r.http, owned=False)

    flavor.run(clients.aclose() if flavor.is_async else clients.close())

    assert not r.http.is_closed
    r.post("mutation")
    assert r.script.requests[-1].headers["connection"] == "keep-alive", "used as is"
    r.close()
