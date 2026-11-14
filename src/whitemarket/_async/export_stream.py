"""The iterator `stream_products` returns: rows as the body arrives, closable at any time."""

from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Generic, Self, TypeVar

from whitemarket._async.export_transport import AsyncExportBody
from whitemarket._concurrency import async_close_soon

Row = TypeVar("Row")


class AsyncRowStream(Generic[Row]):
    """Single-pass iterator over the rows of a file being downloaded.

    Stopping early (leaving the loop, then `aclose()`, or `async with`) closes the connection;
    reaching the end or failing closes it too. Close a stream that was never iterated as well:
    the connection is open from the moment the call returned. Prefer `async with`: a bare `break`
    cannot close an async generator (Python runs no code there), so a stream that is dropped
    open is closed when it is garbage collected, as a task on the running event loop
    (docs/DEVIATIONS.md).
    """

    def __init__(self, rows: AsyncGenerator[Row, None], body: AsyncExportBody) -> None:
        self._rows = rows
        self._body = body

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Row:
        return await anext(self._rows)

    def __del__(self) -> None:
        if not self._body.closed:
            async_close_soon(self._body.aclose)

    async def aclose(self) -> None:
        try:
            await self._rows.aclose()
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


async def replay(rows: list[Row]) -> AsyncGenerator[Row, None]:
    """A list of rows already in memory as an iterator."""
    for row in rows:  # not `yield from`: that does not exist in async code
        yield row
