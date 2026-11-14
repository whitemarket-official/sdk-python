"""`client.market`: search the public market and look up one listing (SDK_SPEC 3.2).

Every method is a read-only query, so the transport retries it on transient failures (SDK_SPEC 1.4).
"""

from collections.abc import AsyncIterator

from whitemarket._async.pagination import forward_pagination, iterate_pages
from whitemarket._generated.client import AsyncGeneratedClient
from whitemarket._generated.input_types import MarketProductSearchInput, SteamLinkInput
from whitemarket._mappers.products import map_product, map_product_page, map_sticker_suggestions
from whitemarket._mappers.wire import search_argument
from whitemarket.market.filter import ProductFilter
from whitemarket.models.page import Page, PageRequest
from whitemarket.models.products import Product, StickerSuggestions

_LIST = ("market_list",)


class AsyncMarketApi:
    """`client.market`."""

    def __init__(self, generated: AsyncGeneratedClient) -> None:
        self._generated = generated

    async def search(
        self,
        filter: ProductFilter | MarketProductSearchInput | None = None,
        page: PageRequest | None = None,
    ) -> Page[Product]:
        """One page of listings (`market_list`).

        Pass `PageRequest(after=previous.end_cursor)` for the next page while
        `previous.has_next_page` is true, or use `iterate()`. A raw `MarketProductSearchInput` is
        sent as is. The server's defaults apply to what `page` leaves out. A listing whose item is
        of a type this SDK does not know is returned with `item=None`.

        Raises `DecodeError` for an unreadable answer (a malformed amount names its path) and the
        other `WhiteMarketError` subclasses for transport, HTTP and GraphQL failures.
        """
        result = await self._generated.market_list(
            forward_pagination=forward_pagination(page),
            search=search_argument(filter),
        )
        return map_product_page(result.market_list, _LIST)

    def iterate(
        self,
        filter: ProductFilter | MarketProductSearchInput | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[Product]:
        """Every listing that matches, page after page; a page is requested only when the previous
        one is consumed. `page_size` is the items per request (the server's default when None).

        Raises what `search()` raises, at the point of the iteration that reads the failing page,
        and `DecodeError` when the server reports a next page without a new cursor.
        """

        async def fetch(after: str | None) -> Page[Product]:
            return await self.search(filter, PageRequest(first=page_size, after=after))

        return iterate_pages(fetch, _LIST)

    async def get(self, id_or_slug: str) -> Product:
        """One listing by its id or slug (`market_item`).

        Raises `NotFoundError` when there is no such listing (category `market.product.not_found`).
        """
        result = await self._generated.market_item(id_or_slug)
        return map_product(result.market_item, ("market_item",))

    async def sticker_suggestions(
        self, search: str, limit: int = 10, offset: int = 0
    ) -> StickerSuggestions:
        """Sticker names that match `search` (`market_csgo_stickers_suggestion`), to fill
        `ProductFilter(sticker_names=...)`. `limit` is the window size and `offset` its start (the
        API defaults are 10 and 0)."""
        result = await self._generated.market_csgo_stickers_suggestion(search, limit, offset)
        return map_sticker_suggestions(result.market_csgo_stickers_suggestion)

    async def check_trade_url(self, url: str) -> str:
        """Ask the API to check a Steam trade offer URL (`market_trade_url`).

        Only a trade offer URL (`https://steamcommunity.com/tradeoffer/new/?partner=..&token=..`)
        is answered normally; a Steam profile URL gets an uncategorized "An unknown error
        occurred." [observed 2026-11-01, SPEC_SYNC fact c]. The schema documents only "Check
        passed trade url", so the returned string is not interpreted: it is returned unchanged. An
        invalid URL surfaces as a `GraphQLError`, not as a return value.
        """
        result = await self._generated.market_trade_url(SteamLinkInput(value=url))
        return result.market_trade_url
