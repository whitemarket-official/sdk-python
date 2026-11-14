"""An export client on a scripted or real HTTP client, for both flavors, with fixed seams."""

import asyncio
import gzip
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from support.flavors import Flavor
from support.http import Reply, Script, reply
from whitemarket import RetryPolicy
from whitemarket.exports import ExportKind, ExportOptions

BASE = "https://export.test"
NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
PRICES_URL = f"{BASE}/v1/prices/730.json"
META_URL = f"{PRICES_URL}.meta.json"
PRODUCTS_URL = f"{BASE}/v1/products/730.json"
META_BODY = json.dumps(
    {
        "file": "730.json",
        "data_as_of": "2026-11-06T11:50:00+00:00",
        "generated_at": "2026-11-06T11:51:00+00:00",
        "items": 4,
    }
).encode()
GZIP = {"Content-Encoding": "gzip"}

# 3 attempts, jitter fixed at 0.5: the waits are 0.25 and 0.5 (base 0.5 * factor 2 ** n * 0.5).
RETRY_WAITS = [0.25, 0.5]


def gz(data: bytes) -> bytes:
    return gzip.compress(data)


def ok(body: bytes, **headers: str) -> Reply:
    return reply(200, body, headers)


class Rig:
    """`flavor`'s export client; `outcomes` are the scripted answers (see `support.http.Script`).

    One event loop per rig: an async httpx client lives in the loop it started in.
    """

    def __init__(
        self,
        flavor: Flavor,
        *outcomes: Any,
        http: Any = None,
        retry: RetryPolicy | None = None,
        cache: Any = None,
        client_options: dict[str, Any] | None = None,
        **options: Any,
    ) -> None:
        self.flavor = flavor
        self.runner = asyncio.Runner() if flavor.is_async else None
        self.script = Script(*outcomes) if outcomes else None
        self.sleeps: list[float] = []
        self.http = http or flavor.mock_http(
            self.script or Script(reply(500)), **(client_options or {})
        )
        seams = flavor.cls("seams", "TransportSeams")(
            clock=lambda: NOW, sleeper=flavor.sleeper(self.sleeps), random=lambda: 0.5
        )
        options.setdefault("base_url", BASE)
        self.client = flavor.cls("exports", "ExportClient")(
            options=ExportOptions(retry=retry or RetryPolicy(), **options),
            cache=cache,
            http_client=self.http,
            seams=seams,
        )

    @property
    def requests(self) -> list[httpx.Request]:
        assert self.script is not None
        return self.script.requests

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def run(self, result: Any) -> Any:
        return self.runner.run(result) if self.runner else result

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return self.run(getattr(self.client, method)(*args, **kwargs))

    def prices(self, **kwargs: Any) -> Any:
        return self.call("prices", **kwargs)

    def meta(self, kind: ExportKind = ExportKind.PRICES, **kwargs: Any) -> Any:
        return self.call("meta", kind, **kwargs)

    def collect(self, stream: Any, limit: int | None = None) -> list[Any]:
        """The rows of a stream (at most `limit`); the stream is closed afterwards."""
        if self.runner is None:
            rows: list[Any] = []
            for row in stream:
                rows.append(row)
                if limit is not None and len(rows) >= limit:
                    break
            stream.close()
            return rows

        async def gather() -> list[Any]:
            found: list[Any] = []
            try:
                async for row in stream:
                    found.append(row)
                    if limit is not None and len(found) >= limit:
                        break
            finally:
                await stream.aclose()
            return found

        return self.run(gather())

    def drain(self, stream: Any, into: list[Any]) -> None:
        """Iterate `stream` to its end into `into` (rows before a failure stay in it)."""
        if self.runner is None:
            into.extend(stream)
            return

        async def go() -> None:
            async for row in stream:
                into.append(row)

        self.run(go())

    def close(self) -> None:
        if self.runner:
            self.runner.run(self.client.aclose())
            self.runner.run(self.http.aclose())
            self.runner.close()
        else:
            self.client.close()
            self.http.close()
