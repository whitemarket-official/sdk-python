"""Where access tokens come from and where they are cached (SDK_SPEC 2, 3.1)."""

from datetime import datetime
from typing import Protocol

from whitemarket._runtime.secret import Secret
from whitemarket._runtime.stored_token import StoredToken


class AsyncTokenProvider(Protocol):
    """Full control over the access token (custom refresh, `auth_steam_jwt`, a shared cache).

    `access_token()` returns a token that is valid now; `refresh()` forces a new one. After a 401
    the transport asks for the current token first and for a refresh only if it is the rejected
    one, then replays the request once.
    """

    async def access_token(self) -> Secret: ...

    async def refresh(self) -> Secret: ...


class AsyncTokenStore(Protocol):
    """Where the access token obtained with the Partner Token is kept.

    Workers that share a store share one token instead of each calling the rate limited
    `auth_token`. Use one store (one key of a shared cache) per Partner Token: a store shared by
    two accounts hands one account's token to the other.
    """

    async def get(self) -> StoredToken | None: ...

    async def set(self, token: Secret, expires_at: datetime) -> None: ...

    async def clear(self) -> None: ...


class AsyncInMemoryTokenStore:
    """The default store: one token in this object."""

    def __init__(self) -> None:
        self._stored: StoredToken | None = None

    async def get(self) -> StoredToken | None:
        return self._stored

    async def set(self, token: Secret, expires_at: datetime) -> None:
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        self._stored = StoredToken(token, expires_at)

    async def clear(self) -> None:
        self._stored = None


class AsyncStaticAccessToken:
    """A fixed access token the caller renews (the `access_token` option)."""

    def __init__(self, token: Secret) -> None:
        self._token = token

    async def access_token(self) -> Secret:
        return self._token

    async def refresh(self) -> Secret:
        return self._token
