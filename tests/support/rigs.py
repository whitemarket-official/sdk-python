"""A full auth stack (transport, executor, credentials, provider) on a scripted HTTP client."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from support.flavors import Flavor, jwt
from support.http import Script, data, json_response
from whitemarket import RetryPolicy, Secret
from whitemarket._runtime.transport_config import TransportConfig

URL = "https://api.test/graphql/partner"
PARTNER = "PARTNER-TOKEN-VALUE"
T0 = datetime(2026, 11, 6, 7, 28, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def token_answer(token: str) -> Any:
    return data(auth_token={"accessToken": token, "isNewPerson": False})


def fresh_token(
    lifetime: int = 3600, clock: Callable[[], datetime] = lambda: T0
) -> Callable[[], str]:
    """A source of distinct synthetic JWTs expiring `lifetime` seconds after the clock."""
    counter = iter(range(1, 10_000))

    def make() -> str:
        return jwt(exp=int(clock().timestamp()) + lifetime, jti=next(counter))

    return make


class SlowAsyncTransport(httpx.AsyncBaseTransport):
    """Answers after a pause, so concurrent callers really overlap."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response], pause: float) -> None:
        self._handler = handler
        self._pause = pause

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self._pause)
        return self._handler(request)


def is_auth_request(request: httpx.Request) -> bool:
    return "X-partner-token" in request.headers and "authorization" not in request.headers


def body_of(request: httpx.Request) -> Any:
    return json.loads(request.content)


class Stack:
    """The pieces of one client wired by hand, for the tests that need a clock or a store."""

    def __init__(
        self,
        flavor: Flavor,
        handler: Callable[[httpx.Request], httpx.Response] | Script,
        *,
        credential: str = "partner",
        token: str | None = None,
        provider: Any = None,
        store: Any = None,
        clock: Clock | None = None,
        http: Any = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.flavor = flavor
        self.clock = clock or Clock()
        self.handler = handler
        self.http = http or flavor.mock_http(handler)
        clients = flavor.cls("transport", "HttpClients")(self.http, self.http, owned=False)
        config = TransportConfig(graphql_url=URL, retry=retry or RetryPolicy(base_delay=0))
        self.transport = flavor.cls("transport", "GraphQLTransport")(
            clients, config, clock=self.clock, sleeper=flavor.sleeper([]), random=lambda: 0.0
        )
        executor_cls = flavor.cls("graphql", "GraphQLExecutor")
        creds = flavor.cls("credentials", "PartnerTokenCredentials")(Secret(PARTNER))
        auth_executor = executor_cls(self.transport, creds)
        self.store = store or flavor.cls("tokens", "InMemoryTokenStore")()
        self.partner = flavor.cls("partner_token", "PartnerTokenProvider")(
            auth_executor, store=self.store, clock=self.clock
        )
        if credential == "static":
            self.provider = flavor.cls("tokens", "StaticAccessToken")(Secret(token or ""))
        elif credential == "custom":
            self.provider = provider
        else:
            self.provider = self.partner
        bearer = flavor.cls("credentials", "BearerCredentials")(self.provider)
        self.executor = executor_cls(self.transport, bearer)

    def run(self, result: Any) -> Any:
        return self.flavor.run(result)

    def query(self, kind: str = "query") -> Any:
        return self.run(self.executor.execute("query Q { test_ping }", "Q", {}, kind))

    def close(self) -> None:
        self.flavor.close(self.http)


def api_ok() -> Any:
    return json_response({"data": {"test_ping": "pong"}})
