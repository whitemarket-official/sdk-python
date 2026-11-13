"""Real sockets: redirects, connection reuse, no resend, total timeout (ADR 0002).

Plain-HTTP loopback servers stand in for the API: the endpoint check is relaxed for the test only
(`_ORIGIN_SCHEMES`); the SDK has no such switch.
"""

import asyncio
import json
import socket
import time
from contextlib import nullcontext
from typing import Any

import httpx
import pytest

from support.flavors import FLAVORS, Flavor
from support.loopback import HttpServer, RawServer, Seen, send
from whitemarket import RetryPolicy, Timeouts
from whitemarket._runtime import endpoints
from whitemarket.errors import HttpError, TransportError

PARTNER = "LOOPBACK-PARTNER-TOKEN"
ACCESS = "loopback.access.token"
PING = json.dumps({"data": {"test_ping": "pong"}}).encode()
LIFETIME = json.dumps({"data": {"market_lifetime_all": True}}).encode()
EXCHANGE = json.dumps(
    {"data": {"auth_token": {"accessToken": ACCESS, "isNewPerson": False}}}
).encode()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames:
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)


@pytest.fixture(autouse=True)
def plain_http_for_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(endpoints, "_ORIGIN_SCHEMES", ("https", "http"))


def answer(handler: Any, seen: Seen) -> None:
    text = seen.body.decode()
    if "auth_token" in text:
        send(handler, 200, EXCHANGE, Content_Type="application/json")
    elif "market_lifetime_all" in text:
        send(handler, 200, LIFETIME, Content_Type="application/json")
    else:
        send(handler, 200, PING, Content_Type="application/json")


class Session:
    """A client created by the SDK itself (default httpx clients) on a loopback base URL."""

    def __init__(self, flavor: Flavor, base_url: str, **options: Any) -> None:
        self.flavor = flavor
        # One event loop per session: an async httpx client lives in the loop it started in.
        self.runner = asyncio.Runner() if flavor.is_async else None
        if "partner_token" not in options:
            options.setdefault("access_token", ACCESS)
        self.client = flavor.cls("client", "WhiteMarketClient")(base_url=base_url, **options)

    def run(self, result: Any) -> Any:
        return self.runner.run(result) if self.runner else result

    def query(self) -> Any:
        return self.run(self.client.generated.test_ping())

    def mutation(self) -> Any:
        return self.run(self.client.generated.market_lifetime_all(value=600))

    def exchange(self) -> Any:
        return self.run(self.client.auth.access_token())

    def close(self) -> None:
        if self.runner:
            self.runner.run(self.client.aclose())
            self.runner.close()
        else:
            self.client.close()


@pytest.fixture
def session(flavor: Flavor) -> Any:
    sessions: list[Session] = []

    def make(base_url: str, **options: Any) -> Session:
        sessions.append(Session(flavor, base_url, **options))
        return sessions[-1]

    yield make
    for s in sessions:
        s.close()


# ---- redirects -----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("operation", ["query", "mutation", "auth_token"])
def test_the_default_client_never_follows_a_redirect(
    session: Any, status: int, operation: str
) -> None:
    with HttpServer(answer) as target:
        with HttpServer(
            lambda h, _: send(h, status, b"", Location=f"{target.url}/graphql/partner")
        ) as origin:
            options = {"partner_token": PARTNER} if operation == "auth_token" else {}
            s = session(origin.url, **options)

            with pytest.raises(HttpError) as caught:
                getattr(s, "exchange" if operation == "auth_token" else operation)()

            assert type(caught.value) is HttpError
            assert caught.value.status == status
            assert len(origin.record.requests) == 1, "not retried"
        assert target.record.requests == [], "the second host received nothing"
        assert target.record.connections == 0


@pytest.mark.parametrize("operation", ["query", "mutation", "auth_token"])
def test_control_a_client_that_follows_redirects_does_reach_the_other_host_with_the_partner_token(
    flavor: Flavor, operation: str
) -> None:
    """Proves the test above can see a leak: with `follow_redirects=True` the header travels."""
    with HttpServer(answer) as target:
        with HttpServer(
            lambda h, _: send(h, 307, b"", Location=f"{target.url}/graphql/partner")
        ) as origin:
            http = flavor.http_client_class(follow_redirects=True)
            options: dict[str, Any] = (
                {"partner_token": PARTNER}
                if operation == "auth_token"
                else {"access_token": ACCESS}
            )
            client = flavor.cls("client", "WhiteMarketClient")(
                base_url=origin.url, http_client=http, **options
            )
            with asyncio.Runner() if flavor.is_async else nullcontext() as runner:

                def run(result: Any, runner: Any = runner) -> Any:
                    return runner.run(result) if runner else result

                if operation == "auth_token":
                    run(client.auth.access_token())
                elif operation == "query":
                    run(client.generated.test_ping())
                else:
                    run(client.generated.market_lifetime_all(value=600))
                run(http.aclose()) if runner else http.close()

        (leaked,) = target.record.requests
        if operation == "auth_token":
            assert leaked.headers["x-partner-token"] == PARTNER
        else:
            # httpx drops `Authorization` across origins; the request itself arrived.
            assert b"test_ping" in leaked.body or b"market_lifetime_all" in leaked.body


# ---- connections and resends ---------------------------------------------------------------------


def test_queries_reuse_a_connection_and_every_mutation_gets_a_fresh_one(session: Any) -> None:
    with HttpServer(answer) as server:
        s = session(server.url)

        s.query()
        s.query()
        assert server.record.connections == 1, "control: a query keeps its connection alive"

        s.mutation()
        s.mutation()
        s.mutation()

    assert server.record.connections == 1 + 3
    assert [r.headers.get("connection") for r in server.record.requests[2:]] == ["close"] * 3


def test_a_mutation_never_rides_a_connection_the_server_closed_while_idle(session: Any) -> None:
    def close_after_answer(handler: Any, seen: Seen) -> None:
        answer(handler, seen)
        handler.close_connection = True  # an idle keep-alive connection that dies after the answer

    with HttpServer(close_after_answer) as server:
        s = session(server.url)
        s.query()
        time.sleep(0.05)

        s.mutation()
        s.mutation()

    assert len(server.record.requests) == 3


def _read_and_drop(conn: socket.socket, request: bytes) -> None:
    """Take the whole request and close without a response: the dead-connection worst case."""


def _status_line_only(conn: socket.socket, request: bytes) -> None:
    conn.sendall(b"HTTP/1.1 200 OK\r\n")


@pytest.mark.parametrize(
    "behaviour", [_read_and_drop, _status_line_only], ids=["no answer", "status line only"]
)
def test_a_mutation_whose_connection_dies_after_the_send_is_sent_exactly_once(
    session: Any, behaviour: Any
) -> None:
    with RawServer(behaviour) as server:
        s = session(server.url, retry=RetryPolicy(base_delay=0))

        with pytest.raises(TransportError):
            s.mutation()

    assert len(server.record.requests) == 1, "httpx/httpcore did not resend the mutation"
    assert server.record.connections == 1


@pytest.mark.parametrize(
    "behaviour", [_read_and_drop, _status_line_only], ids=["no answer", "status line only"]
)
def test_a_query_is_sent_once_per_sdk_attempt_and_the_library_adds_none(
    session: Any, behaviour: Any
) -> None:
    with RawServer(behaviour) as server:
        s = session(server.url, retry=RetryPolicy(max_attempts=3, base_delay=0))

        with pytest.raises(TransportError):
            s.query()

    assert len(server.record.requests) == 3, "exactly the 3 attempts of the retry policy"


# ---- total timeout -------------------------------------------------------------------------------


def _stall(conn: socket.socket, request: bytes) -> None:
    time.sleep(5)


def _drip(conn: socket.socket, request: bytes) -> None:
    conn.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nContent-Type: application/json\r\n\r\n"
    )
    for _ in range(100):
        conn.sendall(b" ")
        time.sleep(0.1)


def test_a_server_that_never_answers_ends_with_a_transport_error(session: Any) -> None:
    with RawServer(_stall) as server:
        s = session(server.url, timeouts=Timeouts(connect=1, request=0.3))
        started = time.monotonic()

        with pytest.raises(TransportError) as caught:
            s.mutation()

    assert time.monotonic() - started < 2.5
    assert caught.value.__context__ is None
    assert len(server.record.requests) == 1


def test_a_server_that_drips_the_body_cannot_hold_the_request_open(session: Any) -> None:
    """Each byte arrives inside the per-read timeout; only a total limit ends this request."""
    with RawServer(_drip) as server:
        s = session(server.url, timeouts=Timeouts(connect=1, request=0.6))
        started = time.monotonic()

        with pytest.raises(TransportError, match="could not read the response"):
            s.mutation()

    assert time.monotonic() - started < 3
    assert len(server.record.requests) == 1, "a body failure after the answer is never retried"


def test_the_total_time_of_a_request_is_not_bounded_for_an_injected_client(flavor: Flavor) -> None:
    http = flavor.http_client_class(timeout=httpx.Timeout(None))
    client = flavor.cls("client", "WhiteMarketClient")(access_token=ACCESS, http_client=http)

    assert client._clients.owned is False
    flavor.close(http)
