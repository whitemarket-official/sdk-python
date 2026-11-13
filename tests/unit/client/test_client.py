"""Client configuration, auth API and the generated layer (SDK_SPEC 2, 3.1)."""

import asyncio
import inspect
from typing import Any

import httpx
import pytest

from support.flavors import FLAVORS, Flavor, jwt
from support.http import Script, data, reply
from support.rigs import PARTNER, T0, body_of, fresh_token, token_answer
from whitemarket import (
    AsyncInMemoryTokenStore,
    BuyReconciliation,
    InMemoryTokenStore,
    RetryPolicy,
    Secret,
    Timeouts,
)
from whitemarket.errors import AuthenticationError, ServiceUnavailableError

P = "p"
OTHER = "OTHER-PARTNER"
ACCESS = jwt(exp=int(T0.timestamp()) + 3600, jti="given")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames:
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)


class Made:
    """A client under test and the scripted httpx client it runs on."""

    def __init__(self, flavor: Flavor, *outcomes: Any, **options: Any) -> None:
        self.flavor = flavor
        self.script = Script(*outcomes)
        self.http = flavor.mock_http(self.script)
        self.client = flavor.cls("client", "WhiteMarketClient")(http_client=self.http, **options)

    def call(self, result: Any) -> Any:
        return self.flavor.run(result)

    def close(self) -> None:
        self.flavor.close(self.http)


@pytest.fixture
def make(flavor: Flavor) -> Any:
    made: list[Made] = []

    def build(*outcomes: Any, **options: Any) -> Made:
        item = Made(flavor, *outcomes, **options)
        made.append(item)
        return item

    yield build
    for item in made:
        item.close()


def test_the_partner_token_is_exchanged_then_the_access_token_is_used(make: Any) -> None:
    token = fresh_token()()
    m = make(token_answer(token), data(test_ping="pong"), partner_token=PARTNER)

    assert m.call(m.client.auth.ping()) == "pong"

    exchange, ping = m.script.requests
    assert exchange.headers["x-partner-token"] == PARTNER
    assert "authorization" not in exchange.headers
    assert ping.headers["authorization"] == f"Bearer {token}"
    assert "x-partner-token" not in ping.headers
    assert body_of(ping)["operationName"] == "TestPing"


def test_a_secret_works_as_a_partner_token(make: Any) -> None:
    m = make(token_answer(fresh_token()()), partner_token=Secret(PARTNER))

    assert m.call(m.client.auth.access_token())
    assert m.script.requests[0].headers["x-partner-token"] == PARTNER


def test_auth_access_token_is_cached_and_refresh_forces_an_exchange(make: Any) -> None:
    mk = fresh_token()
    m = make(token_answer(mk()), token_answer(mk()), partner_token=PARTNER)

    first = m.call(m.client.auth.access_token())
    again = m.call(m.client.auth.access_token())
    forced = m.call(m.client.auth.refresh())

    assert isinstance(first, Secret)
    assert first == again
    assert forced != first
    assert m.script.count == 2
    assert str(forced) == repr(forced) == "***"


def test_the_generated_layer_shares_the_clients_token_and_transport(make: Any) -> None:
    token = fresh_token()()
    m = make(
        token_answer(token), data(test_ping="pong"), data(test_ping="again"), partner_token=PARTNER
    )

    token_seen = m.call(m.client.auth.access_token())
    generated = m.call(m.client.generated.test_ping())
    raw = m.call(m.client.generated.execute("query Q { test_ping }", {}, "Q"))

    assert generated.test_ping == "pong"
    assert raw == {"test_ping": "again"}
    assert m.script.count == 3, "one exchange only: the generated layer reuses the cached token"
    assert m.script.requests[1].headers["authorization"] == f"Bearer {token_seen.reveal()}"
    assert m.script.requests[2].headers["authorization"] == f"Bearer {token}"


def test_the_raw_execute_infers_the_type_so_a_mutation_is_never_retried(make: Any) -> None:
    m = make(reply(503), access_token=ACCESS)
    with pytest.raises(ServiceUnavailableError):
        m.call(m.client.generated.execute("mutation M { market_lifetime_all(value: 600) }"))
    assert m.script.count == 1

    q = make(reply(503), data(test_ping="p"), access_token=ACCESS)
    assert q.call(q.client.generated.execute("query { test_ping }")) == {"test_ping": "p"}
    assert q.script.count == 2, "a clear query is retried"


def test_a_mutation_document_labelled_a_query_is_still_sent_once(make: Any) -> None:
    """Rule 2: no caller can make a mutation retryable by declaring it a query."""
    m = make(reply(503), data(market_lifetime_all=True), access_token=ACCESS)

    with pytest.raises(ServiceUnavailableError):
        m.call(
            m.client.generated.execute(
                "mutation M { market_lifetime_all(value: 600) }", operation_type="query"
            )
        )

    assert m.script.count == 1


def test_a_fixed_access_token_needs_no_exchange_and_is_not_refreshed(make: Any) -> None:
    m = make(data(test_ping="pong"), reply(401), access_token=ACCESS)

    assert m.call(m.client.auth.ping()) == "pong"
    assert m.call(m.client.auth.access_token()) == Secret(ACCESS)
    assert m.call(m.client.auth.refresh()) == Secret(ACCESS)
    with pytest.raises(AuthenticationError):
        m.call(m.client.auth.ping())

    assert m.script.count == 2
    assert all("x-partner-token" not in r.headers for r in m.script.requests)


def test_a_custom_token_provider_is_used(make: Any, flavor: Flavor) -> None:
    class Provider:
        if flavor.is_async:

            async def access_token(self) -> Secret:
                return Secret("custom.provider.token")

            async def refresh(self) -> Secret:
                return Secret("custom.provider.token")
        else:

            def access_token(self) -> Secret:
                return Secret("custom.provider.token")

            def refresh(self) -> Secret:
                return Secret("custom.provider.token")

    m = make(data(test_ping="pong"), token_provider=Provider())

    assert m.call(m.client.auth.ping()) == "pong"
    assert m.script.requests[0].headers["authorization"] == "Bearer custom.provider.token"


def test_a_token_store_is_used_for_the_exchanged_token(make: Any, flavor: Flavor) -> None:
    store = flavor.cls("tokens", "InMemoryTokenStore")()
    token = fresh_token()()
    m = make(token_answer(token), partner_token=PARTNER, token_store=store)
    m.call(m.client.auth.access_token())

    stored = flavor.run(store.get())
    assert stored.token == Secret(token)

    other = make(partner_token=OTHER, token_store=store)
    assert other.call(other.client.auth.access_token()) == Secret(token)
    assert other.script.count == 0, "a shared store spares the exchange"


def test_the_public_store_classes_are_the_default_stores() -> None:
    assert asyncio.run(AsyncInMemoryTokenStore().get()) is None
    assert InMemoryTokenStore().get() is None


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param({}, "exactly one", id="no credential"),
        pytest.param(
            {"partner_token": "p", "access_token": "a.b"}, "exactly one", id="partner + access"
        ),
        pytest.param(
            {"partner_token": "p", "token_provider": object()},
            "exactly one",
            id="partner + provider",
        ),
        pytest.param(
            {"access_token": "a", "token_provider": object()}, "exactly one", id="access + provider"
        ),
        pytest.param(
            {"partner_token": "p", "access_token": "a", "token_provider": object()},
            "exactly one",
            id="all three",
        ),
        pytest.param(
            {"access_token": "a.b", "token_store": object()},
            "with that only",
            id="store with access",
        ),
        pytest.param(
            {"token_provider": object(), "token_store": object()},
            "with that only",
            id="store with provider",
        ),
        pytest.param({"partner_token": ""}, "must not be empty", id="empty partner"),
        pytest.param(
            {"partner_token": "new\nline"}, "not a valid credential", id="partner with newline"
        ),
        pytest.param(
            {"partner_token": "p\n"}, "not a valid credential", id="partner trailing newline"
        ),
        pytest.param({"partner_token": " p"}, "not a valid credential", id="partner leading space"),
        pytest.param({"partner_token": "café"}, "not a valid credential", id="partner non-ascii"),
        pytest.param(
            {"access_token": "with space"}, "not a valid credential", id="access with space"
        ),
        pytest.param({"access_token": ""}, "must not be empty", id="empty access"),
        pytest.param(
            {"partner_token": "p", "base_url": "http://api.test"}, "https", id="plain http"
        ),
        pytest.param(
            {"partner_token": "p", "base_url": "https://u:p@api.test"},
            "credentials",
            id="creds in url",
        ),
        pytest.param({"partner_token": "p", "graphql_path": "nope"}, "graphql_path", id="path"),
        pytest.param(
            {"partner_token": "p", "export_base_url": "http://x"},
            "export_base_url",
            id="export http",
        ),
        pytest.param({"partner_token": "p", "sse_url": "http://x/sse"}, "sse_url", id="sse http"),
        pytest.param({"partner_token": "p", "ws_url": "ws://x/ws"}, "ws_url", id="ws plain"),
        pytest.param(
            {"partner_token": "p", "user_agent_suffix": "bad\n"}, "user_agent_suffix", id="suffix"
        ),
        pytest.param(
            {"partner_token": "p", "max_response_bytes": 0}, "max_response_bytes", id="zero limit"
        ),
    ],
)
def test_invalid_configuration_is_a_value_error_that_never_echoes_a_credential(
    flavor: Flavor, options: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message) as caught:
        flavor.cls("client", "WhiteMarketClient")(**options)

    for value in options.values():
        if isinstance(value, str) and len(value) > 1:
            assert value not in str(caught.value) or value.startswith("http")


@pytest.mark.parametrize("field", ["partner_token", "access_token"])
@pytest.mark.parametrize("value", [123, b"bytes", ["x"]])
def test_a_credential_of_the_wrong_type_is_a_type_error(
    flavor: Flavor, field: str, value: Any
) -> None:
    with pytest.raises(TypeError, match=field):
        flavor.cls("client", "WhiteMarketClient")(**{field: value})


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(lambda: Timeouts(connect=0), id="zero connect"),
        pytest.param(lambda: Timeouts(request=-1), id="negative request"),
        pytest.param(lambda: RetryPolicy(max_attempts=0), id="no attempts"),
        pytest.param(lambda: BuyReconciliation(delay=9.9), id="delay below 10"),
        pytest.param(lambda: BuyReconciliation(delay=20.1), id="delay above 20"),
        pytest.param(lambda: BuyReconciliation(attempts=0), id="no reconciliation attempts"),
        pytest.param(lambda: BuyReconciliation(interval=-1), id="negative interval"),
    ],
)
def test_option_objects_validate_themselves(factory: Any) -> None:
    with pytest.raises(ValueError, match=r"."):
        factory()


def test_the_smallest_valid_options_are_accepted(make: Any) -> None:
    m = make(
        partner_token=P,
        timeouts=Timeouts(connect=0.001, request=0.001),
        retry=RetryPolicy(max_attempts=1, base_delay=0, max_delay=0, factor=1),
        buy_reconciliation=BuyReconciliation(delay=10, attempts=1, interval=0),
        max_response_bytes=1,
    )

    assert m.client._buy_reconciliation.delay == 10
    assert BuyReconciliation(delay=20).delay == 20


def test_defaults(make: Any) -> None:
    m = make(partner_token=P)

    assert m.client._endpoints.graphql_url == "https://api.white.market/graphql/partner"
    assert m.client._buy_reconciliation == BuyReconciliation(delay=15, attempts=3, interval=5)
    assert Timeouts() == Timeouts(connect=10, request=30)
    assert RetryPolicy() == RetryPolicy(3, 0.5, 2.0, 30.0)


def test_requests_go_to_the_configured_endpoint_with_the_suffix(make: Any) -> None:
    m = make(
        data(test_ping="x"),
        access_token=ACCESS,
        base_url="https://staging.test:8443/",
        graphql_path="/gql",
        user_agent_suffix="my-app/2.0",
    )

    m.call(m.client.auth.ping())

    request = m.script.requests[0]
    assert str(request.url) == "https://staging.test:8443/gql"
    assert request.headers["user-agent"].endswith(" my-app/2.0")


def test_there_is_no_tls_switch_and_secrets_do_not_show_in_a_dump(
    make: Any, flavor: Flavor
) -> None:
    parameters = inspect.signature(flavor.cls("client", "WhiteMarketClient")).parameters
    assert not {
        p for p in parameters if "verify" in p or "ssl" in p or "tls" in p or "insecure" in p
    }

    m = make(partner_token=PARTNER)
    dump = repr(vars(m.client)) + repr(m.client) + repr(vars(m.client.auth))
    assert PARTNER not in dump


# ---- from_env ------------------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("WHITEMARKET_PARTNER_TOKEN", raising=False)
    monkeypatch.delenv("WHITEMARKET_BASE_URL", raising=False)
    return monkeypatch


def test_from_env_reads_the_partner_token(env: pytest.MonkeyPatch, flavor: Flavor) -> None:
    env.setenv("WHITEMARKET_PARTNER_TOKEN", "ENV-PARTNER")
    script = Script(token_answer(fresh_token()()))
    http = flavor.mock_http(script)

    client = flavor.cls("client", "WhiteMarketClient").from_env(http_client=http)
    flavor.run(client.auth.access_token())
    flavor.close(http)

    assert script.requests[0].headers["x-partner-token"] == "ENV-PARTNER"
    assert client._endpoints.base_url == "https://api.white.market"


def test_from_env_lets_the_base_url_replace_the_option_and_forwards_the_others(
    env: pytest.MonkeyPatch, flavor: Flavor
) -> None:
    env.setenv("WHITEMARKET_PARTNER_TOKEN", "ENV-PARTNER")
    env.setenv("WHITEMARKET_BASE_URL", "https://env.test")
    reconciliation = BuyReconciliation(delay=12)

    client = flavor.cls("client", "WhiteMarketClient").from_env(
        base_url="https://option.test", buy_reconciliation=reconciliation, graphql_path="/g"
    )

    assert client._endpoints.graphql_url == "https://env.test/g"
    assert client._buy_reconciliation is reconciliation


def test_an_empty_base_url_in_the_environment_is_ignored(
    env: pytest.MonkeyPatch, flavor: Flavor
) -> None:
    env.setenv("WHITEMARKET_PARTNER_TOKEN", "ENV-PARTNER")
    env.setenv("WHITEMARKET_BASE_URL", "")

    client = flavor.cls("client", "WhiteMarketClient").from_env(base_url="https://option.test")

    assert client._endpoints.base_url == "https://option.test"


@pytest.mark.parametrize(
    ("token", "message"),
    [
        pytest.param(None, "not set", id="unset"),
        pytest.param("", "not set", id="empty"),
        pytest.param("tok\n", "trailing newline", id="trailing newline"),
        pytest.param(" tok", "valid HTTP header value", id="leading space"),
    ],
)
def test_from_env_refuses_a_missing_or_malformed_token_without_echoing_it(
    env: pytest.MonkeyPatch, flavor: Flavor, token: str | None, message: str
) -> None:
    if token is not None:
        env.setenv("WHITEMARKET_PARTNER_TOKEN", token)

    with pytest.raises(ValueError, match=message) as caught:
        flavor.cls("client", "WhiteMarketClient").from_env()

    assert token is None or token.strip() == "" or token not in str(caught.value)


def test_from_env_validates_the_environment_base_url(
    env: pytest.MonkeyPatch, flavor: Flavor
) -> None:
    env.setenv("WHITEMARKET_PARTNER_TOKEN", "ENV-PARTNER")
    env.setenv("WHITEMARKET_BASE_URL", "http://insecure.test")

    with pytest.raises(ValueError, match="https"):
        flavor.cls("client", "WhiteMarketClient").from_env()


def test_from_env_takes_no_credential_options(env: pytest.MonkeyPatch, flavor: Flavor) -> None:
    env.setenv("WHITEMARKET_PARTNER_TOKEN", "ENV-PARTNER")

    with pytest.raises(TypeError):
        flavor.cls("client", "WhiteMarketClient").from_env(access_token=P)


# ---- closing -------------------------------------------------------------------------------------


def _enter_exit(flavor: Flavor, client: Any) -> None:
    if flavor.is_async:

        async def go() -> None:
            async with client:
                pass

        asyncio.run(go())
    else:
        with client:
            pass


def test_the_context_manager_closes_what_the_sdk_created(flavor: Flavor) -> None:
    client = flavor.cls("client", "WhiteMarketClient")(partner_token=P)
    clients = client._clients
    assert clients.owned
    assert not clients.query.is_closed

    _enter_exit(flavor, client)

    assert clients.query.is_closed
    assert clients.mutation.is_closed


def test_an_injected_client_is_not_closed_and_not_reconfigured(flavor: Flavor) -> None:
    http = flavor.http_client_class(follow_redirects=True)
    client = flavor.cls("client", "WhiteMarketClient")(partner_token=P, http_client=http)

    _enter_exit(flavor, client)

    assert not http.is_closed
    assert http.follow_redirects is True, "used as is: the caller owns its redirect policy"
    flavor.close(http)


def test_the_default_http_clients_never_follow_redirects_and_use_the_timeouts(
    flavor: Flavor,
) -> None:
    client = flavor.cls("client", "WhiteMarketClient")(
        partner_token=P, timeouts=Timeouts(connect=3, request=7)
    )
    try:
        for http in (client._clients.query, client._clients.mutation):
            assert http.follow_redirects is False
            assert http.timeout == httpx.Timeout(7, connect=3)
        assert client._clients.mutation is not client._clients.query
    finally:
        _enter_exit(flavor, client)


def test_from_env_options_are_every_constructor_option_but_the_credentials(flavor: Flavor) -> None:
    options = set(flavor.cls("client", "ClientOptions").__annotations__)
    constructor = inspect.signature(flavor.cls("client", "WhiteMarketClient").__init__).parameters
    credentials = {"partner_token", "access_token", "token_provider"}

    keywords = {name for name in constructor if name != "self"}

    assert options == keywords - credentials, "a new option must be forwarded by from_env too"
