"""PartnerTokenProvider and the 401 replay, sync and async twins (SDK_SPEC 2, 3.1; PHP ADR 0003)."""

from typing import Any

import httpx
import pytest

from support.flavors import Flavor, jwt
from support.http import Script, reply
from support.rigs import (
    PARTNER,
    T0,
    Stack,
    api_ok,
    body_of,
    fresh_token,
    is_auth_request,
    token_answer,
)
from whitemarket import RetryPolicy, Secret, StoredToken
from whitemarket.errors import AuthenticationError, DecodeError, ServiceUnavailableError

AUTH_ENDPOINT_QUERY = "auth_token"
HTTP_OK = 200


@pytest.fixture
def stacks() -> Any:
    made: list[Stack] = []
    yield made
    for stack in made:
        stack.close()


def build(stacks: list[Stack], flavor: Flavor, handler: Any, **kwargs: Any) -> Stack:
    stack = Stack(flavor, handler, **kwargs)
    stacks.append(stack)
    return stack


def test_the_partner_token_is_exchanged_with_auth_token_and_no_authorization(
    flavor: Flavor, stacks: list[Stack]
) -> None:
    token = fresh_token()()
    script = Script(token_answer(token))
    stack = build(stacks, flavor, script)

    result = stack.run(stack.partner.access_token())

    (request,) = script.requests
    assert result == Secret(token)
    assert request.headers["x-partner-token"] == PARTNER
    assert "authorization" not in request.headers
    assert AUTH_ENDPOINT_QUERY in body_of(request)["query"]
    assert body_of(request)["operationName"] == "AuthToken"
    assert str(result) == "***"
    assert PARTNER not in repr(stack.partner.__dict__)


def test_the_token_is_stored_until_its_expiry_and_reused(
    flavor: Flavor, stacks: list[Stack]
) -> None:
    token = fresh_token(lifetime=3600)()
    script = Script(token_answer(token))
    stack = build(stacks, flavor, script)

    first = stack.run(stack.partner.access_token())
    second = stack.run(stack.partner.access_token())
    stored = stack.run(stack.store.get())

    assert first == second
    assert script.count == 1
    assert isinstance(stored, StoredToken)
    assert stored.token == Secret(token)
    assert (stored.expires_at - T0).total_seconds() == 3600


@pytest.mark.parametrize(
    ("seconds_before_expiry", "exchanged"),
    [
        pytest.param(301, False, id="5 min 1 s before expiry: still cached"),
        pytest.param(300, True, id="exactly the margin: refreshed"),
        pytest.param(299, True, id="inside the margin: refreshed"),
        pytest.param(-10, True, id="after expiry: refreshed"),
    ],
)
def test_the_margin_boundary(
    flavor: Flavor, stacks: list[Stack], seconds_before_expiry: int, exchanged: bool
) -> None:
    stack = build(stacks, flavor, Script())
    stack.handler.outcomes[:] = [
        token_answer(fresh_token(3600, stack.clock)()),
        token_answer(fresh_token(3600, stack.clock)()),
    ]
    stack.run(stack.partner.access_token())
    stack.clock.now = T0.replace() + (stack.run(stack.store.get()).expires_at - T0)
    stack.clock.advance(seconds=-seconds_before_expiry)

    stack.run(stack.partner.access_token())

    assert (stack.handler.count == 2) is exchanged


@pytest.mark.parametrize(
    ("exp_offset", "exchanged_again"),
    [
        pytest.param(-10, True, id="exp in the past: exchanged before the next request"),
        pytest.param(0, True, id="exp is now: exchanged before the next request"),
        pytest.param(60, True, id="exp within the margin: exchanged before the next request"),
        pytest.param(300, True, id="exp exactly at the margin: exchanged before the next request"),
        pytest.param(301, False, id="exp 1 s past the margin: served from the store"),
    ],
)
def test_a_received_token_serves_its_request_and_an_expired_one_is_not_served_again(
    flavor: Flavor, stacks: list[Stack], exp_offset: int, exchanged_again: bool
) -> None:
    received = jwt(exp=int(T0.timestamp()) + exp_offset, jti=1)
    later = jwt(exp=int(T0.timestamp()) + 3600, jti=2)
    stack = build(stacks, flavor, Script(token_answer(received), token_answer(later)))

    first = stack.run(stack.partner.access_token())
    second = stack.run(stack.partner.access_token())

    assert first == Secret(received), "a token just received serves the request that asked"
    assert second == Secret(later if exchanged_again else received)
    assert stack.handler.count == (2 if exchanged_again else 1)


def test_an_expired_token_is_exchanged_before_the_next_request_without_a_401(
    flavor: Flavor, stacks: list[Stack]
) -> None:
    expired = jwt(exp=int(T0.timestamp()) - 10, jti=1)
    valid = jwt(exp=int(T0.timestamp()) + 3600, jti=2)
    script = Script(token_answer(expired), api_ok(), token_answer(valid), api_ok())
    stack = build(stacks, flavor, script)

    stack.query()
    stack.query()

    api = [r for r in script.requests if not is_auth_request(r)]
    assert [r.headers["authorization"] for r in api] == [f"Bearer {expired}", f"Bearer {valid}"]
    assert len(script.requests) == 4, "two exchanges, two requests, no 401 round trip"


def test_an_unreadable_exp_falls_back_to_24_hours(flavor: Flavor, stacks: list[Stack]) -> None:
    stack = build(stacks, flavor, Script(token_answer(jwt(raw_payload="garbage"))))

    stack.run(stack.partner.access_token())

    assert (stack.run(stack.store.get()).expires_at - T0).total_seconds() == 24 * 3600


def test_refresh_exchanges_even_with_a_valid_token(flavor: Flavor, stacks: list[Stack]) -> None:
    make = fresh_token()
    stack = build(stacks, flavor, Script(token_answer(make()), token_answer(make())))
    first = stack.run(stack.partner.access_token())

    second = stack.run(stack.partner.refresh())

    assert first != second
    assert stack.handler.count == 2
    assert stack.run(stack.partner.access_token()) == second


def test_a_token_another_worker_stored_is_reused(flavor: Flavor, stacks: list[Stack]) -> None:
    stack = build(stacks, flavor, Script())
    shared = stack.store
    stack.run(shared.set(Secret(fresh_token()()), T0.replace(year=2027)))
    other = build(stacks, flavor, Script(), store=shared)

    token = other.run(other.partner.access_token())

    assert token == stack.run(shared.get()).token
    assert other.handler.count == 0


@pytest.mark.parametrize("poisoned", ["has space", "new\nline", "", "café", "a;b"])
def test_a_stored_token_that_is_not_a_valid_bearer_token_is_never_sent_and_is_replaced(
    flavor: Flavor, stacks: list[Stack], poisoned: str
) -> None:
    fresh = fresh_token()()
    stack = build(stacks, flavor, Script(token_answer(fresh)))
    stack.run(stack.store.set(Secret(poisoned), T0.replace(year=2027)))

    token = stack.run(stack.partner.access_token())

    assert token == Secret(fresh)
    assert stack.handler.count == 1


@pytest.mark.parametrize("bad", ["has space", "new\nline", "a;b", ""])
def test_an_access_token_from_the_server_that_is_not_a_bearer_token_is_refused_and_not_stored(
    flavor: Flavor, stacks: list[Stack], bad: str
) -> None:
    stack = build(stacks, flavor, Script(token_answer(bad)))

    with pytest.raises(DecodeError) as caught:
        stack.run(stack.partner.access_token())

    assert bad.strip() == "" or bad not in str(caught.value)
    assert stack.run(stack.store.get()) is None


def test_the_store_refuses_a_naive_datetime(flavor: Flavor) -> None:
    store = flavor.cls("tokens", "InMemoryTokenStore")()

    with pytest.raises(ValueError, match="timezone-aware"):
        flavor.run(store.set(Secret("x"), T0.replace(tzinfo=None)))


def test_the_store_clear_and_get(flavor: Flavor) -> None:
    store = flavor.cls("tokens", "InMemoryTokenStore")()
    assert flavor.run(store.get()) is None
    flavor.run(store.set(Secret("abc"), T0))
    token, expires = flavor.run(store.get())
    assert (token, expires) == (Secret("abc"), T0)
    flavor.run(store.clear())
    assert flavor.run(store.get()) is None


def test_a_rejected_partner_token_is_not_replayed(flavor: Flavor, stacks: list[Stack]) -> None:
    stack = build(stacks, flavor, Script(reply(401, b'{"error":{"code":401}}')))

    with pytest.raises(AuthenticationError):
        stack.run(stack.partner.access_token())

    assert stack.handler.count == 1


def test_auth_token_is_never_retried(flavor: Flavor, stacks: list[Stack]) -> None:
    stack = build(stacks, flavor, Script(reply(503)))

    with pytest.raises(ServiceUnavailableError):
        stack.run(stack.partner.access_token())

    assert stack.handler.count == 1


# ---- 401 on an API request: refresh once, replay once -------------------------------------------


@pytest.mark.parametrize("kind", ["query", "mutation"])
def test_a_401_refreshes_once_and_replays_once(
    flavor: Flavor, stacks: list[Stack], kind: str
) -> None:
    make = fresh_token()
    stale = make()
    accepted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if is_auth_request(request):
            accepted.append(make())
            return token_answer(accepted[-1]).build()
        if accepted and request.headers["authorization"] == f"Bearer {accepted[-1]}":
            return api_ok().build()
        return reply(401, b'{"error":{"code":401,"message":"Expired JWT Token"}}').build()

    script = Script(handler)
    stack = build(stacks, flavor, script)
    stack.run(stack.store.set(Secret(stale), T0.replace(year=2027)))  # cached but rejected

    result = stack.query(kind)

    assert result == {"test_ping": "pong"}
    api = [r for r in script.requests if not is_auth_request(r)]
    auth = [r for r in script.requests if is_auth_request(r)]
    assert len(api) == 2, "one rejected request and one replay"
    assert len(auth) == 1, "one refresh"
    assert api[0].content == api[1].content, "the replay carries the same body"
    assert api[0].headers["authorization"] == f"Bearer {stale}"
    assert api[1].headers["authorization"] == f"Bearer {accepted[0]}"


@pytest.mark.parametrize("kind", ["query", "mutation"])
def test_a_second_401_is_an_authentication_error_and_there_is_no_third_try(
    flavor: Flavor, stacks: list[Stack], kind: str
) -> None:
    make = fresh_token()

    def handler(request: httpx.Request) -> httpx.Response:
        if is_auth_request(request):
            return token_answer(make()).build()
        return reply(401, b'{"error":{"code":401}}').build()

    script = Script(handler)
    stack = build(stacks, flavor, script)

    with pytest.raises(AuthenticationError) as caught:
        stack.query(kind)

    api = [r for r in script.requests if not is_auth_request(r)]
    assert len(api) == 2
    assert len([r for r in script.requests if is_auth_request(r)]) == 2, (
        "initial token + one refresh"
    )
    assert caught.value.status == 401


@pytest.mark.parametrize("kind", ["query", "mutation"])
def test_a_fixed_access_token_is_never_replayed(
    flavor: Flavor, stacks: list[Stack], kind: str
) -> None:
    script = Script(reply(401))
    stack = build(stacks, flavor, script, credential="static", token=fresh_token()())

    with pytest.raises(AuthenticationError):
        stack.query(kind)

    assert script.count == 1


def test_the_replay_uses_a_token_another_worker_stored_without_calling_auth_token(
    flavor: Flavor, stacks: list[Stack]
) -> None:
    make = fresh_token()
    stale, current = make(), make()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", "-"))
        if request.headers.get("authorization") == f"Bearer {current}":
            return api_ok().build()
        # Another worker renewed the shared token while this request was in flight.
        stack.store._stored = StoredToken(Secret(current), T0.replace(year=2027))
        return reply(401).build()

    script = Script(handler)
    stack = build(stacks, flavor, script)
    stack.run(stack.store.set(Secret(stale), T0.replace(year=2027)))

    assert stack.query() == {"test_ping": "pong"}
    assert seen == [f"Bearer {stale}", f"Bearer {current}"]
    assert not any(is_auth_request(r) for r in script.requests)


class _Provider:
    def __init__(self, flavor: Flavor, first: str, second: str) -> None:
        self.tokens = [first, second]
        self.refreshed = 0
        self.is_async = flavor.is_async

        if flavor.is_async:

            async def access_token() -> Secret:
                return Secret(self.tokens[self.refreshed])

            async def refresh() -> Secret:
                self.refreshed += 1
                return Secret(self.tokens[self.refreshed])
        else:

            def access_token() -> Secret:
                return Secret(self.tokens[self.refreshed])

            def refresh() -> Secret:
                self.refreshed += 1
                return Secret(self.tokens[self.refreshed])

        self.access_token = access_token
        self.refresh = refresh


def test_a_custom_provider_is_asked_for_one_refresh_and_its_token_is_sent(
    flavor: Flavor, stacks: list[Stack]
) -> None:
    provider = _Provider(flavor, "first-token", "second-token")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] == "Bearer second-token":
            return api_ok().build()
        return reply(401).build()

    stack = build(stacks, flavor, Script(handler), credential="custom", provider=provider)

    assert stack.query("mutation") == {"test_ping": "pong"}
    assert provider.refreshed == 1


@pytest.mark.parametrize("bad", ["has space", "new\nline", "a;b", ""])
def test_a_custom_provider_value_that_is_not_a_bearer_token_is_refused_and_nothing_is_sent(
    flavor: Flavor, stacks: list[Stack], bad: str
) -> None:
    provider = _Provider(flavor, bad, bad)
    script = Script(api_ok())
    stack = build(stacks, flavor, script, credential="custom", provider=provider)

    with pytest.raises(ValueError, match="not a valid bearer token") as caught:
        stack.query()

    assert script.count == 0
    assert bad.strip() == "" or bad not in str(caught.value)


@pytest.mark.parametrize(
    ("kind", "statuses"),
    [
        pytest.param("query", [503, 503, 401, 503], id="401 last: one replay, no retry"),
        pytest.param("query", [503, 503, 401, 200], id="401 last: the replay succeeds"),
        pytest.param("query", [401, 503, 503], id="401 first: the replay uses attempts 2-3"),
        pytest.param("query", [503, 401, 503], id="401 second: the replay is attempt 3"),
        pytest.param("query", [503, 401, 200], id="401 second: the replay succeeds"),
        pytest.param("mutation", [401, 503], id="mutation: sent at most twice"),
    ],
)
def test_the_401_replay_shares_the_attempt_budget_of_the_call(
    flavor: Flavor, stacks: list[Stack], kind: str, statuses: list[int]
) -> None:
    """SDK_SPEC 1.4: a query sends at most `max_attempts` requests plus the token exchange; a 401
    on the last attempt is still replayed once and that replay is not retried. `statuses` is the
    whole expected sequence of sends: one send more fails the handler with an IndexError."""
    sent: list[int] = []
    exchanges: list[int] = []
    make_token = fresh_token()

    def handler(request: httpx.Request) -> httpx.Response:
        if is_auth_request(request):
            exchanges.append(1)
            return token_answer(make_token()).build()
        status = statuses[len(sent)]
        sent.append(status)
        return (api_ok() if status == HTTP_OK else reply(status)).build()

    stack = build(stacks, flavor, handler, retry=RetryPolicy(max_attempts=3, base_delay=0))

    if statuses[-1] == HTTP_OK:
        assert stack.query(kind) == {"test_ping": "pong"}
    else:
        with pytest.raises(ServiceUnavailableError):
            stack.query(kind)

    assert sent == statuses
    assert len(exchanges) == 2, "the first token and the one refresh after the 401"
