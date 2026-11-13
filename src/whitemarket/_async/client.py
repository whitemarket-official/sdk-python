"""The client: configuration, token wiring and the shared transport (SDK_SPEC 2, 3.1)."""

import logging
import os
from collections.abc import Callable
from typing import Self, TypedDict, Unpack, cast

import httpx

from whitemarket._async.credentials import AsyncBearerCredentials, AsyncPartnerTokenCredentials
from whitemarket._async.graphql import AsyncGraphQLExecutor
from whitemarket._async.partner_token import AsyncPartnerTokenProvider
from whitemarket._async.tokens import AsyncStaticAccessToken, AsyncTokenProvider, AsyncTokenStore
from whitemarket._async.transport import AsyncGraphQLTransport, AsyncHttpClients
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._runtime.endpoints import Endpoints, require_user_agent_suffix
from whitemarket._runtime.secret import Secret
from whitemarket._runtime.tokens import is_valid_bearer_token, is_valid_header_value
from whitemarket._runtime.transport_config import TransportConfig, build_user_agent
from whitemarket.config import DEFAULT_MAX_RESPONSE_BYTES, BuyReconciliation, Timeouts
from whitemarket.retry import RetryPolicy

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


class AsyncWhiteMarketClient:
    """Entry point of the SDK (async). Every client owns its transport and token.

    Give exactly one of `partner_token` (preferred: the SDK exchanges it for access tokens and
    renews them), `access_token` (a JWT the caller renews) or `token_provider`. `token_store` goes
    with `partner_token` only. An injected `http_client` is used as is for queries and mutations:
    the SDK cannot set its timeouts or redirect policy (it must not follow redirects or resend a
    request whose connection failed) and does not close it. TLS verification is always on.

    Use it as `async with` or call `aclose()`: that closes the HTTP clients the SDK created.

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
    ) -> None:
        credentials = [c for c in (partner_token, access_token, token_provider) if c is not None]
        if len(credentials) != 1:
            raise ValueError("pass exactly one of partner_token, access_token or token_provider")
        if token_store is not None and partner_token is None:
            raise ValueError(
                "token_store keeps the token obtained with partner_token: pass it with that only"
            )
        self.endpoints = Endpoints.resolve(
            base_url=base_url,
            graphql_path=graphql_path,
            export_base_url=export_base_url,
            sse_url=sse_url,
            ws_url=ws_url,
        )
        self.buy_reconciliation = buy_reconciliation or BuyReconciliation()
        config = TransportConfig(
            graphql_url=self.endpoints.graphql_url,
            user_agent=build_user_agent(require_user_agent_suffix(user_agent_suffix)),
            timeouts=timeouts or Timeouts(),
            max_response_bytes=max_response_bytes,
            retry=retry or RetryPolicy(),
        )
        self._clients = AsyncHttpClients.create(config, http_client)
        self._transport = AsyncGraphQLTransport(self._clients, config, logger=logger)
        provider = self._token_provider(partner_token, access_token, token_provider, token_store)
        self._provider = provider
        self.generated = AsyncGeneratedClient(
            AsyncGraphQLExecutor(self._transport, AsyncBearerCredentials(provider))
        )
        self.auth = AsyncAuthApi(provider, self.generated)

    def _token_provider(
        self,
        partner_token: str | Secret | None,
        access_token: str | Secret | None,
        token_provider: AsyncTokenProvider | None,
        token_store: AsyncTokenStore | None,
    ) -> AsyncTokenProvider:
        if partner_token is not None:
            secret = _secret("partner_token", partner_token, is_valid_header_value)
            executor = AsyncGraphQLExecutor(self._transport, AsyncPartnerTokenCredentials(secret))
            return AsyncPartnerTokenProvider(executor, store=token_store)
        if access_token is not None:
            return AsyncStaticAccessToken(
                _secret("access_token", access_token, is_valid_bearer_token)
            )
        return cast("AsyncTokenProvider", token_provider)  # exactly one credential was checked

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

    async def aclose(self) -> None:
        """Close the HTTP clients the SDK created (an injected one stays open)."""
        await self._clients.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.endpoints.base_url!r})"


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
