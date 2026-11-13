"""The iterator `stream_products` returns: rows as the body arrives, closable at any time."""

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Generic, Self, TypeVar

from whitemarket._async.export_transport import AsyncExportBody

Row = TypeVar("Row")


class AsyncRowStream(Generic[Row]):
    """Single-pass iterator over the rows of a file being downloaded.

    Stopping early (leaving the loop, then `aclose()`, or `async with`) closes the connection;
    reaching the end or failing closes it too. Close a stream that was never iterated as well:
    the connection is open from the moment the call returned.
    """

    def __init__(self, rows: AsyncIterator[Row], body: AsyncExportBody) -> None:
        self._rows = rows
        self._body = body

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Row:
        return await anext(self._rows)

    async def aclose(self) -> None:
        # The rows are an async generator in practice; a plain iterator has nothing to close.
        aclose: Any = getattr(self._rows, "aclose", None)
        try:
            if aclose is not None:
                await aclose()
        finally:
            await self._body.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


async def replay(rows: list[Row]) -> AsyncIterator[Row]:
    """A list of rows already in memory as an iterator."""
    for index in range(len(rows)):  # an index loop: `yield from` does not exist in async code
        yield rows[index]
