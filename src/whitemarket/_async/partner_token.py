"""Partner Token -> access token with `auth_token`: cached, single-flight (SDK_SPEC 3.1)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from whitemarket._async.executor import AsyncOperationExecutor
from whitemarket._async.tokens import AsyncInMemoryTokenStore, AsyncTokenStore
from whitemarket._concurrency import AsyncLock
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._runtime.credential_format import is_valid_bearer_token
from whitemarket._runtime.jwt import token_expiry
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import DecodeError

REFRESH_MARGIN = timedelta(minutes=5)
# A token is kept at least this long, so one shorter than the margin is not exchanged on every
# call; if the server rejects it earlier, the 401 path renews it.
MIN_LIFETIME = 2 * REFRESH_MARGIN


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AsyncPartnerTokenProvider:
    """Exchanges the Partner Token with `auth_token` and keeps the JWT in a `TokenStore`.

    The JWT is reused until 5 minutes before it expires (`exp`, read without verifying the
    signature; 24 h when unreadable). `auth_token` is rate limited, so a token another worker
    stored is reused. Refreshing is single-flight: callers that arrive while an exchange runs wait
    for it and share its result.
    """

    def __init__(
        self,
        executor: AsyncOperationExecutor,
        *,
        store: AsyncTokenStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # `executor` authenticates with the Partner Token (`AsyncPartnerTokenCredentials`).
        self._exchange_client = AsyncGeneratedClient(executor)
        self._store: AsyncTokenStore = store if store is not None else AsyncInMemoryTokenStore()
        self._clock = clock or _utc_now
        self._lock = AsyncLock()
        self._generation = 0  # counts finished exchanges, failed ones too
        self._outcome: Secret | Exception | None = None

    async def access_token(self) -> Secret:
        seen = self._generation
        cached = await self._cached()
        if cached is not None:
            return cached
        async with self._lock:
            if self._generation != seen:
                return self._shared_outcome()
            cached = await self._cached()  # a worker sharing the store may have exchanged
            if cached is not None:
                return cached
            return await self._exchange()

    async def refresh(self) -> Secret:
        """Force an exchange. Callers that wait while another exchange runs share its outcome."""
        seen = self._generation
        async with self._lock:
            if self._generation != seen:
                return self._shared_outcome()
            return await self._exchange()

    async def refresh_rejected(self, rejected: Secret) -> Secret:
        """Exchange unless the store already holds a token other than the rejected one."""
        seen = self._generation
        async with self._lock:
            if self._generation != seen:
                return self._shared_outcome()
            current = await self._cached()
            if current is not None and current != rejected:
                return current
            return await self._exchange()

    async def _cached(self) -> Secret | None:
        stored = await self._store.get()
        if stored is None:
            return None
        if not is_valid_bearer_token(stored.token.reveal()):
            # Written by something else (a shared cache, an older SDK): never sent, replaced.
            await self._store.clear()
            return None
        if self._clock() < stored.expires_at - REFRESH_MARGIN:
            return stored.token
        return None

    def _shared_outcome(self) -> Secret:
        """The result of the exchange that finished while this caller waited for the lock.

        A failure is shared too: `auth_token` is rate limited, so N waiters must not each repeat
        an exchange that just failed. A caller that arrives after it finished exchanges by itself.
        """
        outcome = self._outcome
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            raise RuntimeError("an exchange finished without an outcome")
        return outcome

    async def _exchange(self) -> Secret:
        """One `auth_token` call (lock held); its outcome is kept for the callers queued behind."""
        try:
            token = await self._fetch_and_store()
        except Exception as error:  # a cancellation is not an outcome the waiters should share
            self._outcome = error
            self._generation += 1
            raise
        self._outcome = token
        self._generation += 1
        return token

    async def _fetch_and_store(self) -> Secret:
        token = (await self._exchange_client.auth_token()).auth_token.access_token
        if not is_valid_bearer_token(token.reveal()):
            raise DecodeError("not a valid bearer token", ("auth_token", "accessToken"))
        now = self._clock()
        expires_at = max(token_expiry(token.reveal(), now), now + MIN_LIFETIME)
        await self._store.set(token, expires_at)
        return token
