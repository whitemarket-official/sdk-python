"""The client: configuration, token wiring and the shared transport (SDK_SPEC 2, 3.1)."""

import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Self, TypedDict, Unpack, cast

import httpx

from whitemarket._async.buying import AsyncBuyingApi
from whitemarket._async.credentials import (
    AsyncBearerCredentials,
    AsyncPartnerTokenCredentials,
    AsyncTokenRenewer,
)
from whitemarket._async.deals import AsyncDealsApi
from whitemarket._async.exports import AsyncExportClient
from whitemarket._async.graphql import AsyncGraphQLExecutor
from whitemarket._async.inventory import AsyncInventoryApi
from whitemarket._async.market import AsyncMarketApi
from whitemarket._async.partner_token import AsyncPartnerTokenProvider
from whitemarket._async.profile import AsyncProfileApi
from whitemarket._async.selling import AsyncSellingApi
from whitemarket._async.store import AsyncStoreApi
from whitemarket._async.tokens import AsyncStaticAccessToken, AsyncTokenProvider, AsyncTokenStore
from whitemarket._async.transport import AsyncGraphQLTransport, AsyncHttpClients
from whitemarket._async.wallet import AsyncWalletApi
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._runtime.credential_format import is_valid_bearer_token, is_valid_header_value
from whitemarket._runtime.endpoints import Endpoints, require_user_agent_suffix
from whitemarket._runtime.secret import Secret
from whitemarket._runtime.transport_config import TransportConfig, build_user_agent
from whitemarket.config import DEFAULT_MAX_RESPONSE_BYTES, BuyReconciliation, Timeouts
from whitemarket.exports.options import ExportOptions
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.live.options import LiveOptions, LiveTransport
from whitemarket.retry import RetryPolicy
from whitemarket.selling.options import DEFAULT_BATCH_SIZE, check_batch_size

ENV_PARTNER = "WHITEMARKET_PARTNER_TOKEN"
ENV_BASE_URL = "WHITEMARKET_BASE_URL"
_CREDENTIAL_OPTIONS = ("partner_token", "access_token", "token_provider")


class AsyncAuthApi:
    """`client.auth` (SDK_SPEC 3.1)."""

    def __init__(self, provider: AsyncTokenProvider, generated: AsyncGeneratedClient) -> None:
        self._provider = provider
        self._generated = generated

    async def access_token(self) -> Secret:
        """A valid access token (JWT): cached, renewed 5 minutes before expiry, single-flight."""
        return await self._provider.access_token()

    async def refresh(self) -> Secret:
        """Force `auth_token` (a fixed token or a custom provider answers as it decides)."""
        return await self._provider.refresh()

    async def ping(self) -> str:
        """`test_ping`: a connectivity and credentials check."""
        return (await self._generated.test_ping()).test_ping


class AsyncClientOptions(TypedDict, total=False):
    """The options `from_env` forwards: everything except the credentials."""

    token_store: AsyncTokenStore | None
    base_url: str | None
    graphql_path: str | None
    export_base_url: str | None
    sse_url: str | None
    ws_url: str | None
    http_client: httpx.AsyncClient | None
    timeouts: Timeouts | None
    retry: RetryPolicy | None
    logger: logging.Logger | None
    user_agent_suffix: str | None
    buy_reconciliation: BuyReconciliation | None
    max_response_bytes: int
    selling_batch_size: int


class AsyncWhiteMarketClient:
    """Entry point of the SDK (async). Every client owns its transport and token.

    Give exactly one of `partner_token` (preferred: the SDK exchanges it for access tokens and
    renews them), `access_token` (a JWT the caller renews) or `token_provider`. `token_store` goes
    with `partner_token` only. An injected `http_client` serves queries and mutations: the SDK
    cannot set its timeouts (and trusts it not to resend a request whose connection failed) and
    does not close it, but sends every request with `follow_redirects=False` and `auth=None`, so
    the client's redirect policy and `auth` never apply. TLS verification is always on.

    Use it as `async with` or call `aclose()`: that closes the HTTP clients the SDK created.
    `exports` is the public export-file client (no authentication, its own HTTP client).
    `selling_batch_size` is the items per request of the `*_many` methods of `selling` (default 100,
    at least 1; the backend's maximum is unconfirmed, so a larger value may make the server reject).

    Raises `ValueError` for an invalid combination or value and `TypeError` for a wrong type.
    """

    def __init__(
        self,
        *,
        partner_token: str | Secret | None = None,
        access_token: str | Secret | None = None,
        token_provider: AsyncTokenProvider | None = None,
        token_store: AsyncTokenStore | None = None,
        base_url: str | None = None,
        graphql_path: str | None = None,
        export_base_url: str | None = None,
        sse_url: str | None = None,
        ws_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeouts: Timeouts | None = None,
        retry: RetryPolicy | None = None,
        logger: logging.Logger | None = None,
        user_agent_suffix: str | None = None,
        buy_reconciliation: BuyReconciliation | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        selling_batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        check_batch_size(selling_batch_size)
        credentials = [c for c in (partner_token, access_token, token_provider) if c is not None]
        if len(credentials) != 1:
            raise ValueError("pass exactly one of partner_token, access_token or token_provider")
        if token_store is not None and partner_token is None:
            raise ValueError(
                "token_store keeps the token obtained with partner_token: pass it with that only"
            )
        self._endpoints = Endpoints.resolve(
            base_url=base_url,
            graphql_path=graphql_path,
            export_base_url=export_base_url,
            sse_url=sse_url,
            ws_url=ws_url,
        )
        self._buy_reconciliation = buy_reconciliation or BuyReconciliation()
        config = TransportConfig(
            graphql_url=self._endpoints.graphql_url,
            user_agent=build_user_agent(require_user_agent_suffix(user_agent_suffix)),
            timeouts=timeouts or Timeouts(),
            max_response_bytes=max_response_bytes,
            retry=retry or RetryPolicy(),
        )
        self._clients = AsyncHttpClients.create(config, http_client)
        self._transport = AsyncGraphQLTransport(self._clients, config, logger=logger)
        provider, renew = build_provider(
            self._transport,
            partner_token=partner_token,
            access_token=access_token,
            token_provider=token_provider,
            token_store=token_store,
        )
        self.generated = AsyncGeneratedClient(
            AsyncGraphQLExecutor(self._transport, AsyncBearerCredentials(provider, renew))
        )
        self.auth = AsyncAuthApi(provider, self.generated)
        self._token_provider = provider
        self._user_agent = config.user_agent
        # The export side shares nothing with the credential: its own HTTP client, no token.
        self.exports = AsyncExportClient(
            options=ExportOptions(
                base_url=self._endpoints.export_base_url,
                connect_timeout=config.timeouts.connect,
                retry=config.retry,
                user_agent_suffix=user_agent_suffix,
            ),
            logger=logger,
        )
        self.market = AsyncMarketApi(self.generated)
        self.buying = AsyncBuyingApi(self.generated, self._buy_reconciliation)
        self.deals = AsyncDealsApi(self.generated)
        self.selling = AsyncSellingApi(self.generated, selling_batch_size)
        self.inventory = AsyncInventoryApi(self.generated)
        self.wallet = AsyncWalletApi(self.generated)
        self.profile = AsyncProfileApi(self.generated)
        self.store = AsyncStoreApi(self.generated)

    @classmethod
    def from_env(cls, **options: Unpack[AsyncClientOptions]) -> Self:
        """A client with the Partner Token of `WHITEMARKET_PARTNER_TOKEN`.

        `WHITEMARKET_BASE_URL`, when set and not empty, replaces `base_url`. Nothing else is read
        from the environment.
        """
        for credential in _CREDENTIAL_OPTIONS:
            if credential in options:
                raise TypeError(
                    f"from_env takes the Partner Token from the environment, not {credential}"
                )
        token = os.environ.get(ENV_PARTNER, "")
        if not token:
            raise ValueError(f"{ENV_PARTNER} is not set")
        if not is_valid_header_value(token):
            raise ValueError(
                f"{ENV_PARTNER} is not a valid HTTP header value "
                "(visible ASCII, no leading or trailing whitespace): check for a trailing newline"
            )
        base_url = os.environ.get(ENV_BASE_URL, "")
        if base_url:
            options["base_url"] = base_url
        return cls(partner_token=token, **options)

    def live(
        self, transport: LiveTransport = LiveTransport.WS, options: LiveOptions | None = None
    ) -> AsyncLiveSession:
        """A live session (SDK_SPEC 3.11): `LiveTransport.WS` (default, needs the `live` extra)
        or `LiveTransport.SSE`. Register handlers, then `connect()` or iterate; close it (or use
        `async with`) when done. The session fetches a fresh access token before every connect."""
        return AsyncLiveSession.create(
            tokens=self._token_provider,
            transport=transport,
            ws_url=self._endpoints.ws_url,
            sse_url=self._endpoints.sse_url,
            user_agent=self._user_agent,
            options=options,
        )

    async def aclose(self) -> None:
        """Close the HTTP clients the SDK created (an injected one stays open)."""
        await self._clients.aclose()
        await self.exports.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self._endpoints.base_url!r})"


def build_provider(
    transport: AsyncGraphQLTransport,
    *,
    partner_token: str | Secret | None = None,
    access_token: str | Secret | None = None,
    token_provider: AsyncTokenProvider | None = None,
    token_store: AsyncTokenStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[AsyncTokenProvider, AsyncTokenRenewer | None]:
    """The token provider of the given credential, and how it renews a token a 401 rejected.

    Exactly one credential is expected (the client checks). A Partner Token gets a provider that
    exchanges it over `transport` and renews by its own rejected-token rule; the other credentials
    renew through `provider.refresh()` (`renew` is `None`).
    """
    if partner_token is not None:
        secret = _secret("partner_token", partner_token, is_valid_header_value)
        executor = AsyncGraphQLExecutor(transport, AsyncPartnerTokenCredentials(secret))
        exchanging = AsyncPartnerTokenProvider(executor, store=token_store, clock=clock)
        return exchanging, exchanging.refresh_rejected
    if access_token is not None:
        static = AsyncStaticAccessToken(
            _secret("access_token", access_token, is_valid_bearer_token)
        )
        return static, None
    return cast("AsyncTokenProvider", token_provider), None  # exactly one credential was checked


def _secret(name: str, value: str | Secret, valid: Callable[[str], bool]) -> Secret:
    secret = value if isinstance(value, Secret) else _wrap(name, value)
    text = secret.reveal()
    if not text:
        raise ValueError(f"{name} must not be empty")
    if not valid(text):
        raise ValueError(f"{name} is not a valid credential (see the documentation)")
    return secret


def _wrap(name: str, value: object) -> Secret:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str or a Secret")
    return Secret(value)
