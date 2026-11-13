"""One test body for the async and the sync twin of the transport and the client."""

import asyncio
import base64
import importlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

TOKEN_JWT_BODY = {"data": {"auth_token": {"accessToken": "", "isNewPerson": False}}}


def jwt(
    exp: object = None, iat: object = None, raw_payload: str | None = None, **extra: object
) -> str:
    """A syntactically valid, unsigned test JWT (synthetic, not a real credential)."""
    claims: dict[str, object] = dict(extra)
    if exp is not None:
        claims["exp"] = exp
    if iat is not None:
        claims["iat"] = iat
    payload = raw_payload if raw_payload is not None else json.dumps(claims)
    segment = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{segment}.c2ln"


@dataclass(frozen=True)
class Flavor:
    name: str
    package: str  # "_async" or "_sync"

    @property
    def is_async(self) -> bool:
        return self.name == "async"

    def cls(self, module: str, name: str) -> Any:
        """`name` of `whitemarket.<package>.<module>`; `Async` is prefixed in the async flavor."""
        mod = importlib.import_module(f"whitemarket.{self.package}.{module}")
        return getattr(mod, f"Async{name}" if self.is_async else name)

    def attr(self, module: str, name: str) -> Any:
        """`name` of `whitemarket.<package>.<module>` as it is spelled in both flavors."""
        return getattr(importlib.import_module(f"whitemarket.{self.package}.{module}"), name)

    @property
    def http_client_class(self) -> Any:
        return httpx.AsyncClient if self.is_async else httpx.Client

    def run(self, result: Any) -> Any:
        """Await `result` in the async flavor, return it as is in the sync one."""
        return asyncio.run(result) if self.is_async else result

    def sleeper(self, sink: list[float]) -> Callable[[float], Any]:
        if self.is_async:

            async def async_record(seconds: float) -> None:
                sink.append(seconds)

            return async_record

        def record(seconds: float) -> None:
            sink.append(seconds)

        return record

    def mock_http(self, handler: Callable[[httpx.Request], httpx.Response]) -> Any:
        return self.http_client_class(transport=httpx.MockTransport(handler))

    def close(self, http: Any) -> None:
        self.run(http.aclose()) if self.is_async else http.close()


ASYNC = Flavor("async", "_async")
SYNC = Flavor("sync", "_sync")
FLAVORS = [ASYNC, SYNC]
