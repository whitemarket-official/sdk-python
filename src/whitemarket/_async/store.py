"""`client.store`: the partner's own store (SDK_SPEC 3.9).

`get()` is a query, which the transport retries on transient failures (SDK_SPEC 1.4). `edit()` is
a mutation: sent exactly once and never retried (CLAUDE.md rule 2), and a failure propagates as it
is. It sets values, so the caller may repeat it after checking the state with `get()`.
"""

from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._mappers.store import map_store
from whitemarket.models.store import Store
from whitemarket.store.settings import StoreSettings


class AsyncStoreApi:
    """`client.store`."""

    def __init__(self, generated: AsyncGeneratedClient) -> None:
        self._generated = generated

    async def get(self) -> Store:
        """The store (`store_my`)."""
        answer = (await self._generated.store_my()).store_my
        return map_store(answer, answer.achievements)

    async def edit(self, settings: StoreSettings) -> Store:
        """Change the store settings that are given (`store_edit`) and return the store as the
        server now has it. A mutation: sent once, never retried.

        Raises `ValueError`, before anything is sent, for an avatar or banner the API schema does
        not accept.
        """
        answer = (await self._generated.store_edit(settings.to_input())).store_edit
        return map_store(answer, answer.achievements)
