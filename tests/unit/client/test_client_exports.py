"""`client.exports`: the public export client inside the SDK client shares nothing secret."""

from typing import Any

import httpx
import pytest
import respx

from support.exports import PRICES_BODY
from support.flavors import Flavor, each_flavor, jwt
from support.http import Script, data
from support.rigs import PARTNER, T0, token_answer
from whitemarket import (
    AsyncExportClient,
    AsyncWhiteMarketClient,
    ExportClient,
    RetryPolicy,
    WhiteMarketClient,
)
from whitemarket.errors import TransportError

ACCESS = jwt(exp=int(T0.timestamp()) + 3600, jti="exports")
EXPORT_URL = "https://export.white.market/v1/prices/730.json"


def close(flavor: Flavor, client: Any) -> None:
    flavor.run(client.aclose() if flavor.is_async else client.close())


@each_flavor
def test_export_requests_carry_no_credential_even_after_an_authenticated_call(
    flavor: Flavor,
) -> None:
    graphql = Script(token_answer(ACCESS), data(test_ping="pong"))
    http = flavor.mock_http(graphql)
    client = flavor.cls("client", "WhiteMarketClient")(partner_token=PARTNER, http_client=http)
    with respx.mock(assert_all_called=False) as router:
        route = router.get(EXPORT_URL).respond(200, content=PRICES_BODY)

        assert flavor.run(client.auth.ping()) == "pong"
        prices = flavor.run(client.exports.prices())

    assert len(prices) == 1
    assert graphql.count == 2  # the injected client served the GraphQL calls only
    seen: httpx.Request = route.calls.last.request
    text = " ".join(f"{name}={value}" for name, value in seen.headers.items())
    assert "authorization" not in seen.headers
    assert "x-partner-token" not in seen.headers
    assert PARTNER not in text
    assert ACCESS not in text
    close(flavor, client)
    flavor.close(http)


@each_flavor
def test_the_export_client_uses_the_export_base_url_and_the_clients_settings(
    flavor: Flavor,
) -> None:
    client = flavor.cls("client", "WhiteMarketClient")(
        access_token=ACCESS,
        export_base_url="https://export.example.test",
        retry=RetryPolicy.none(),
        user_agent_suffix="shop/2",
    )
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://export.example.test/v1/prices/730.json").respond(503)

        with pytest.raises(Exception, match="503"):
            flavor.run(client.exports.prices())

    assert route.call_count == 1  # RetryPolicy.none(): one attempt
    assert route.calls.last.request.headers["user-agent"].endswith(" shop/2")
    close(flavor, client)


@each_flavor
def test_closing_the_client_closes_the_export_client(flavor: Flavor) -> None:
    client = flavor.cls("client", "WhiteMarketClient")(access_token=ACCESS)
    with respx.mock(assert_all_called=False) as router:
        router.get(EXPORT_URL).respond(200, content=PRICES_BODY)
        close(flavor, client)

        with pytest.raises(TransportError):
            flavor.run(client.exports.prices())


def test_the_exports_attribute_is_the_public_export_client() -> None:
    assert isinstance(WhiteMarketClient(access_token=ACCESS).exports, ExportClient)
    assert isinstance(AsyncWhiteMarketClient(access_token=ACCESS).exports, AsyncExportClient)
