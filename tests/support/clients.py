"""A client (async or sync) on a scripted httpx client, driven the same way in both flavors."""

import asyncio
from typing import Any

from support.flavors import Flavor, jwt
from support.http import Script
from support.rigs import T0

ACCESS = jwt(exp=int(T0.timestamp()) + 3600, jti="rig")


class ClientRig:
    """One client with a static access token (no token exchange request) and a `Script`.

    `call` runs an awaitable (async flavor) or passes a result through (sync); `step` advances an
    iterator by one item on the same event loop, so a lazy iteration can be watched request by
    request. Use as a context manager (it closes the client and the loop) or call `close()`.
    `static_token=False` leaves the client without an access token, so it exchanges the
    `partner_token` given in the options.
    """

    def __init__(
        self, flavor: Flavor, *outcomes: Any, static_token: bool = True, **client_options: Any
    ) -> None:
        self.flavor = flavor
        self.script = Script(*outcomes)
        self.http = flavor.mock_http(self.script)
        self.client = flavor.cls("client", "WhiteMarketClient")(
            http_client=self.http,
            **({"access_token": ACCESS} if static_token else {}),
            **client_options,
        )
        self._runner = asyncio.Runner() if flavor.is_async else None

    def call(self, result: Any) -> Any:
        return self._runner.run(result) if self._runner else result

    def step(self, iterator: Any) -> Any:
        """The next item; raises `StopIteration` when the iterator is exhausted (both flavors)."""
        if self._runner is None:
            return next(iterator)
        try:
            return self._runner.run(iterator.__anext__())
        except StopAsyncIteration:
            raise StopIteration from None

    def drain(self, iterator: Any) -> list[Any]:
        items: list[Any] = []
        while True:
            try:
                items.append(self.step(iterator))
            except StopIteration:
                return items

    def bodies(self) -> list[dict[str, Any]]:
        return self.script.bodies()

    def variables(self) -> list[dict[str, Any]]:
        return [body.get("variables", {}) for body in self.bodies()]

    def close(self) -> None:
        if self._runner is None:
            self.flavor.close(self.http)
        else:
            self._runner.run(self.http.aclose())
            self._runner.close()

    def __enter__(self) -> "ClientRig":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


Rig = ClientRig  # the name the buying and deals tests import; to be renamed there
