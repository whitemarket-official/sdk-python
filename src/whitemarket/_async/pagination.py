"""Lazy auto-pagination for every `iterate_*` method (SDK_SPEC 3)."""

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from whitemarket._mappers.common import Path
from whitemarket.errors import DecodeError
from whitemarket.models.page import Page

_T_co = TypeVar("_T_co", covariant=True)
_T = TypeVar("_T")


class AsyncPageFetcher(Protocol[_T_co]):
    """Fetches the page after a cursor (`None`: the first page)."""

    async def __call__(self, after: str | None, /) -> Page[_T_co]: ...


async def iterate_pages(fetch_page: AsyncPageFetcher[_T], path: Path) -> AsyncIterator[_T]:
    """The items of every page, requesting the next page only after the previous one is consumed.

    Stops on `has_next_page` false. A page that reports a next page but no new cursor (none, or the
    one just used) is a `DecodeError` at `<path>.pageInfo.endCursor`, so a broken server cannot
    make the loop request the same page forever.
    """
    cursor: str | None = None
    while True:
        page = await fetch_page(cursor)
        for item in page.items:
            yield item
        if not page.has_next_page:
            return
        if page.end_cursor is None or page.end_cursor == cursor:
            raise DecodeError(
                "hasNextPage is true but there is no new cursor to continue from",
                (*path, "pageInfo", "endCursor"),
            )
        cursor = page.end_cursor
