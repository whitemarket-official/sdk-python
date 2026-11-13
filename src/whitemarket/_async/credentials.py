"""Which authentication headers a request carries, and what a 401 does (SDK_SPEC 1.4, 2)."""

from collections.abc import Mapping
from typing import Protocol, cast

from whitemarket._async.tokens import AsyncTokenProvider
from whitemarket._runtime.credential_format import is_valid_bearer_token
from whitemarket._runtime.secret import Secret

AUTHORIZATION = "Authorization"
PARTNER_HEADER = "X-partner-token"


class AsyncCredentials(Protocol):
    async def headers(self, operation_name: str) -> Mapping[str, Secret]: ...

    async def headers_after_rejection(
        self, rejected: Mapping[str, Secret]
    ) -> Mapping[str, Secret] | None:
        """Headers for the one replay after a 401, or `None` when a replay cannot help."""
        ...


class AsyncTokenRenewer(Protocol):
    """Renews the access token a 401 rejected (`AsyncPartnerTokenProvider.refresh_rejected`)."""

    async def __call__(self, rejected: Secret) -> Secret: ...


class AsyncPartnerTokenCredentials:
    """`auth_token`: `X-partner-token` and no `Authorization`; a 401 means a bad Partner Token."""

    def __init__(self, partner_token: Secret) -> None:
        self._headers = {PARTNER_HEADER: partner_token}

    async def headers(self, operation_name: str) -> Mapping[str, Secret]:
        return self._headers

    async def headers_after_rejection(
        self, rejected: Mapping[str, Secret]
    ) -> Mapping[str, Secret] | None:
        return None


class AsyncBearerCredentials:
    """The provider's access token as `Authorization: Bearer`.

    After a 401, `renew` (when given) replaces `provider.refresh()`: it gets the rejected token, so
    a provider that coalesces renewals can skip the exchange when another caller already did it.
    """

    def __init__(
        self, provider: AsyncTokenProvider, renew: AsyncTokenRenewer | None = None
    ) -> None:
        self._provider = provider
        self._renew = renew

    async def headers(self, operation_name: str) -> Mapping[str, Secret]:
        return _bearer(await self._provider.access_token())

    async def headers_after_rejection(
        self, rejected: Mapping[str, Secret]
    ) -> Mapping[str, Secret] | None:
        """Replay headers: the current token if it is not the rejected one, else a refreshed one.

        A replay is offered only with a token different from the rejected one, so a fixed access
        token is never replayed. Another worker may have stored a new token meanwhile; asking for
        the current one first spares an `auth_token` call.
        """
        rejected_header = rejected.get(AUTHORIZATION)
        token = await self._provider.access_token()
        if _was_rejected(token, rejected_header):
            token = await self._renew(token) if self._renew else await self._provider.refresh()
        if _was_rejected(token, rejected_header):
            return None
        return _bearer(token)


def _bearer(token: Secret) -> dict[str, Secret]:
    value = cast("object", token)  # a custom provider may break its contract
    if not isinstance(value, Secret):
        raise TypeError("the token provider must return a Secret")
    if not is_valid_bearer_token(token.reveal()):
        raise ValueError("the token provider returned a value that is not a valid bearer token")
    return {AUTHORIZATION: Secret(f"Bearer {token.reveal()}")}


def _was_rejected(token: Secret, rejected_header: Secret | None) -> bool:
    return rejected_header is not None and rejected_header == _bearer(token)[AUTHORIZATION]
