"""Single-flight refresh: N concurrent callers cause exactly one `auth_token` call."""

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from support.flavors import ASYNC, SYNC, jwt
from support.http import reply
from support.rigs import (
    T0,
    SlowAsyncTransport,
    Stack,
    api_ok,
    fresh_token,
    is_auth_request,
    token_answer,
)
from whitemarket import Secret

CALLERS = 20
STALE = jwt(exp=int(T0.timestamp()) + 3600, jti="stale")


class Counting:
    """The server side: counts `auth_token` calls; rejects every token but the newest one."""

    def __init__(self) -> None:
        self.make = fresh_token()
        self.auth_calls = 0
        self.newest = ""
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if is_auth_request(request):
            with self._lock:
                self.auth_calls += 1
                self.newest = self.make()
                return token_answer(self.newest).build()
        if self.newest and request.headers["authorization"] == f"Bearer {self.newest}":
            return api_ok().build()
        return reply(401, b'{"error":{"code":401}}').build()


def async_stack(server: Counting) -> Stack:
    return Stack(ASYNC, server, http=httpx.AsyncClient(transport=SlowAsyncTransport(server, 0.02)))


def sync_stack(server: Counting) -> Stack:
    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02)
        return server(request)

    return Stack(SYNC, slow)


def in_threads(call: Callable[[], Any]) -> list[Any]:
    barrier = threading.Barrier(CALLERS)

    def run() -> Any:
        barrier.wait()
        return call()

    with ThreadPoolExecutor(CALLERS) as pool:
        return [f.result() for f in [pool.submit(run) for _ in range(CALLERS)]]


async def test_concurrent_async_callers_share_one_exchange() -> None:
    server = Counting()
    stack = async_stack(server)

    tokens = await asyncio.gather(*(stack.partner.access_token() for _ in range(CALLERS)))
    await stack.http.aclose()

    assert server.auth_calls == 1
    assert len(set(tokens)) == 1


def test_concurrent_threads_share_one_exchange() -> None:
    server = Counting()
    stack = sync_stack(server)

    tokens = in_threads(stack.partner.access_token)
    stack.close()

    assert server.auth_calls == 1
    assert len(set(tokens)) == 1


async def test_concurrent_async_requests_rejected_with_the_same_token_cause_one_refresh() -> None:
    server = Counting()
    stack = async_stack(server)
    await stack.store.set(Secret(STALE), T0.replace(year=2027))  # cached and stale

    results = await asyncio.gather(
        *(stack.executor.execute("query Q { a }", "Q", {}, "query") for _ in range(CALLERS))
    )
    await stack.http.aclose()

    assert results == [{"test_ping": "pong"}] * CALLERS
    assert server.auth_calls == 1, "one refresh for all rejected requests"


def test_concurrent_threads_rejected_with_the_same_token_cause_one_refresh() -> None:
    server = Counting()
    stack = sync_stack(server)
    stack.store.set(Secret(STALE), T0.replace(year=2027))

    results = in_threads(lambda: stack.executor.execute("query Q { a }", "Q", {}, "mutation"))
    stack.close()

    assert results == [{"test_ping": "pong"}] * CALLERS
    assert server.auth_calls == 1


async def test_concurrent_async_forced_refreshes_are_coalesced() -> None:
    server = Counting()
    stack = async_stack(server)

    await asyncio.gather(*(stack.partner.refresh() for _ in range(CALLERS)))
    await stack.http.aclose()

    assert server.auth_calls == 1


def test_a_refresh_after_a_finished_one_exchanges_again() -> None:
    server = Counting()
    stack = sync_stack(server)

    stack.partner.refresh()
    stack.partner.refresh()
    stack.close()

    assert server.auth_calls == 2, "coalescing is for overlapping callers only"


async def test_a_failed_exchange_does_not_poison_the_waiters() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return reply(503).build()
        return token_answer(fresh_token()()).build()

    stack = Stack(
        ASYNC, handler, http=httpx.AsyncClient(transport=SlowAsyncTransport(handler, 0.02))
    )

    outcomes = await asyncio.gather(
        *(stack.partner.access_token() for _ in range(3)), return_exceptions=True
    )
    await stack.http.aclose()

    assert isinstance(outcomes[0], Exception)
    assert all(isinstance(o, Secret) for o in outcomes[1:]), "the next caller exchanges by itself"
    assert calls == 2
