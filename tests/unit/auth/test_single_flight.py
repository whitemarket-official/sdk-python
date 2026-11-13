"""Single-flight refresh: N concurrent callers cause exactly one `auth_token` call."""

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest

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
from whitemarket import RetryPolicy, Secret
from whitemarket.errors import ServerError

CALLERS = 20
STALE = jwt(exp=int(T0.timestamp()) + 3600, jti="stale")


class Counting:
    """The server side: counts `auth_token` calls; rejects every token but the newest one."""

    def __init__(self, auth_status: int = 200) -> None:
        self.make = fresh_token()
        self.auth_status = auth_status
        self.auth_calls = 0
        self.newest = ""
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if is_auth_request(request):
            with self._lock:
                self.auth_calls += 1
                if self.auth_status != 200:
                    return reply(self.auth_status).build()
                self.newest = self.make()
                return token_answer(self.newest).build()
        if self.newest and request.headers["authorization"] == f"Bearer {self.newest}":
            return api_ok().build()
        return reply(401, b'{"error":{"code":401}}').build()


def async_stack(server: Counting, **options: Any) -> Stack:
    http = httpx.AsyncClient(transport=SlowAsyncTransport(server, 0.02))
    return Stack(ASYNC, server, http=http, **options)


def sync_stack(server: Counting, **options: Any) -> Stack:
    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.02)
        return server(request)

    return Stack(SYNC, slow, **options)


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


NO_RETRY = RetryPolicy.none()
FAILING = [
    pytest.param(lambda stack: stack.partner.access_token(), False, id="access_token"),
    pytest.param(lambda stack: stack.partner.refresh(), False, id="refresh"),
    pytest.param(
        lambda stack: stack.executor.execute("query Q { a }", "Q", {}, "query"),
        True,  # a cached, stale token: only a 401 makes the callers refresh
        id="rejected request",
    ),
]


@pytest.mark.parametrize(("call", "cached"), FAILING)
async def test_async_waiters_behind_a_failed_exchange_share_its_failure(
    call: Any, cached: bool
) -> None:
    server = Counting(auth_status=500)
    stack = async_stack(server, retry=NO_RETRY)
    if cached:
        await stack.store.set(Secret(STALE), T0.replace(year=2027))

    outcomes = await asyncio.gather(*(call(stack) for _ in range(CALLERS)), return_exceptions=True)
    await stack.http.aclose()

    assert server.auth_calls == 1, "one failed exchange, not one per waiter"
    assert [type(o) for o in outcomes] == [ServerError] * CALLERS


@pytest.mark.parametrize(("call", "cached"), FAILING)
def test_threads_behind_a_failed_exchange_share_its_failure(call: Any, cached: bool) -> None:
    server = Counting(auth_status=500)
    stack = sync_stack(server, retry=NO_RETRY)
    if cached:
        stack.store.set(Secret(STALE), T0.replace(year=2027))

    def attempt() -> Any:
        try:
            return call(stack)
        except Exception as error:
            return error

    outcomes = in_threads(attempt)
    stack.close()

    assert server.auth_calls == 1
    assert [type(o) for o in outcomes] == [ServerError] * CALLERS


async def test_a_caller_after_a_failed_exchange_exchanges_by_itself() -> None:
    server = Counting(auth_status=500)
    stack = async_stack(server, retry=NO_RETRY)

    with pytest.raises(ServerError):
        await stack.partner.access_token()
    server.auth_status = 200
    token = await stack.partner.access_token()
    await stack.http.aclose()

    assert server.auth_calls == 2
    assert isinstance(token, Secret)
