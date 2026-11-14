"""Real sockets: redirects that must not leave the origin, idle timeout without a total one, and a
stopped stream closing its connection (SDK_SPEC 3.10 rules 1, 2, 9).

Plain-HTTP loopback servers stand in for `export.white.market`: the origin check is relaxed for the
test only (`_ORIGIN_SCHEMES`, the SDK has no such switch), so a redirect to another port of the
same host is the "other origin" case, and the same-origin rule is exercised over real HTTP.
"""

import asyncio
import json
import socket
import threading
import time
from typing import Any

import pytest

from support.export_rig import gz
from support.exports import PRICE_ROW, PRICES_BODY, PRODUCT_ROW, json_body
from support.flavors import Flavor, each_flavor
from support.loopback import HttpServer, RawServer, Seen, send
from whitemarket import RetryPolicy
from whitemarket._runtime import endpoints
from whitemarket.errors import HttpError, TransportError
from whitemarket.exports import ExportOptions


@pytest.fixture(autouse=True)
def plain_http_for_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(endpoints, "_ORIGIN_SCHEMES", ("https", "http"))


class Session:
    """An export client created by the SDK itself (its own httpx client) on a loopback base URL."""

    def __init__(self, flavor: Flavor, base_url: str, **options: Any) -> None:
        self.flavor = flavor
        self.runner = asyncio.Runner() if flavor.is_async else None
        options.setdefault("retry", RetryPolicy.none())
        self.client = flavor.cls("exports", "ExportClient")(
            options=ExportOptions(base_url=base_url, **options)
        )

    def run(self, result: Any) -> Any:
        return self.runner.run(result) if self.runner else result

    def prices(self) -> Any:
        return self.run(self.client.prices())

    def close(self) -> None:
        if self.runner:
            self.runner.run(self.client.aclose())
            self.runner.close()
        else:
            self.client.close()


@pytest.fixture
def session() -> Any:
    made: list[Session] = []

    def make(flavor: Flavor, base_url: str, **options: Any) -> Session:
        made.append(Session(flavor, base_url, **options))
        return made[-1]

    yield make
    for item in made:
        item.close()


# --- redirects -------------------------------------------------------------------------------


@each_flavor
def test_a_redirect_to_another_port_is_refused_and_that_server_receives_nothing(
    flavor: Flavor, session: Any
) -> None:
    with (
        HttpServer(lambda handler, seen: send(handler, 200, PRICES_BODY)) as other,
        HttpServer(
            lambda handler, seen: send(handler, 302, Location=f"{other.url}/v1/prices/730.json")
        ) as origin,
    ):
        client = session(flavor, origin.url)

        with pytest.raises(TransportError, match="another host") as caught:
            client.prices()

        assert caught.value.__cause__ is None
        assert len(origin.record.requests) == 1
        assert other.record.requests == []
        assert other.record.connections == 0


@each_flavor
def test_a_same_origin_redirect_is_followed_over_a_real_connection(
    flavor: Flavor, session: Any
) -> None:
    def answer(handler: Any, seen: Seen) -> None:
        if seen.path == "/v1/prices/730.json":
            send(handler, 301, Location="/v1/moved/730.json")
        else:
            send(handler, 200, PRICES_BODY)

    with HttpServer(answer) as origin:
        client = session(flavor, origin.url)

        assert len(client.prices()) == 1
        assert [r.path for r in origin.record.requests] == [
            "/v1/prices/730.json",
            "/v1/moved/730.json",
        ]


@each_flavor
def test_a_redirect_loop_stops_after_three_redirects(flavor: Flavor, session: Any) -> None:
    with HttpServer(lambda handler, seen: send(handler, 302, Location="/again")) as origin:
        client = session(flavor, origin.url)

        with pytest.raises(TransportError, match="more than 3 times"):
            client.prices()

        assert len(origin.record.requests) == 4


@each_flavor
def test_the_request_on_the_wire_carries_gzip_and_no_credential(
    flavor: Flavor, session: Any
) -> None:
    with HttpServer(lambda handler, seen: send(handler, 200, PRICES_BODY)) as origin:
        session(flavor, origin.url).prices()

        headers = origin.record.requests[0].headers
        assert headers["accept-encoding"] == "gzip"
        assert not {"authorization", "x-partner-token", "cookie"} & headers.keys()


# --- timeouts --------------------------------------------------------------------------------


def stall_after_headers(conn: socket.socket, request: bytes) -> None:
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n[")
    time.sleep(3)


@each_flavor
def test_a_connection_silent_for_the_idle_timeout_is_a_transport_error(
    flavor: Flavor, session: Any
) -> None:
    with RawServer(stall_after_headers) as server:
        client = session(flavor, server.url, idle_timeout=0.3)
        started = time.monotonic()

        with pytest.raises(TransportError, match="Timeout") as caught:
            client.prices()

        assert time.monotonic() - started < 2.5
        assert caught.value.__cause__ is None


@each_flavor
def test_there_is_no_total_timeout_while_bytes_keep_arriving(flavor: Flavor, session: Any) -> None:
    # 1477-byte-class body in 100-byte pieces 0.25 s apart: longer than the idle timeout in all.
    rows = json_body([PRICE_ROW] * 3)
    pieces = -(-len(rows) // 100)

    def slow(conn: socket.socket, request: bytes) -> None:
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(rows)}\r\n\r\n"
        conn.sendall(head.encode())
        for index in range(0, len(rows), 100):
            conn.sendall(rows[index : index + 100])
            time.sleep(0.25)

    with RawServer(slow) as server:
        client = session(flavor, server.url, idle_timeout=0.8)
        started = time.monotonic()

        assert len(client.prices()) == 3
        assert time.monotonic() - started > 0.8  # the whole download outlasted the idle timeout
        assert pieces >= 5


# --- a stopped stream ------------------------------------------------------------------------


def endless_products(closed: threading.Event) -> Any:
    row = json.dumps(PRODUCT_ROW).encode()

    def behave(conn: socket.socket, request: bytes) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n[")
        try:
            while True:
                conn.sendall(row + b",\n" + b" " * 60_000)
                time.sleep(0.001)
        except OSError:
            closed.set()

    return behave


@each_flavor
def test_stopping_stream_products_closes_the_connection(flavor: Flavor, session: Any) -> None:
    closed = threading.Event()
    with RawServer(endless_products(closed)) as server:
        client = session(flavor, server.url)

        def take(count: int) -> list[Any]:
            stream = (
                client.run(client.client.stream_products())
                if client.runner
                else (client.client.stream_products())
            )
            rows: list[Any] = []
            if client.runner:

                async def go() -> None:
                    try:
                        async for row in stream:
                            rows.append(row)
                            if len(rows) == count:
                                break
                    finally:
                        await stream.aclose()

                client.run(go())
            else:
                try:
                    for row in stream:
                        rows.append(row)
                        if len(rows) == count:
                            break
                finally:
                    stream.close()
            return rows

        assert len(take(3)) == 3
        assert closed.wait(timeout=5), "the server never saw the connection close"


@each_flavor
def test_a_status_other_than_200_fails_at_the_call_on_a_real_connection(
    flavor: Flavor, session: Any
) -> None:
    with HttpServer(lambda handler, seen: send(handler, 404, b"nope")) as origin:
        client = session(flavor, origin.url)

        with pytest.raises(HttpError) as caught:
            client.run(client.client.stream_products())

        assert caught.value.status == 404


@each_flavor
def test_a_gzip_body_over_a_real_connection(flavor: Flavor, session: Any) -> None:
    with HttpServer(
        lambda handler, seen: send(handler, 200, gz(PRICES_BODY), Content_Encoding="gzip")
    ) as origin:
        assert len(session(flavor, origin.url).prices()) == 1
