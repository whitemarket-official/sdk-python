"""The public export files: prices, streamed products, the freshness sidecar, raw downloads
(SDK_SPEC 3.10). No authentication, so it works standalone.

Hand-written async; the sync twin is generated (tools/unasync.py).

Failures: a status other than 200 is an `HttpError`; a network failure, a refused redirect, an
undecodable, incomplete or over-sized body is a `TransportError`; a body that is not the expected
JSON or CSV is a `DecodeError`; a destination that cannot be written is a `GeneralExportError`;
data older than `max_age` is a `StaleExportError`. An argument error is a `ValueError` or a
`TypeError`, raised before any request.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import BinaryIO, Literal, overload

import httpx

from whitemarket._async.export_cache import AsyncExportCache
from whitemarket._async.export_stream import AsyncRowStream, replay
from whitemarket._async.export_transport import (
    AsyncExportBody,
    AsyncExportTransport,
    http_timeout,
)
from whitemarket._async.seams import AsyncTransportSeams
from whitemarket._concurrency import async_acquire_blocking, async_run_blocking
from whitemarket._runtime.body import BodyBytes, body_pieces
from whitemarket._runtime.download_sink import abort_sink, open_sink
from whitemarket._runtime.export_urls import (
    DEFAULT_APP,
    META_SUFFIX,
    export_file_url,
    max_age_seconds,
)
from whitemarket.errors.base import StaleExportError
from whitemarket.exports._stream import aiter_product_rows, iter_price_rows
from whitemarket.exports.conditional import NotModified
from whitemarket.exports.kinds import ExportFormat, ExportKind
from whitemarket.exports.meta import ExportMeta, parse_meta
from whitemarket.exports.options import ExportOptions
from whitemarket.exports.price_list import PriceList
from whitemarket.exports.rows import PriceRow, ProductRow
from whitemarket.exports.window import ExportWindow

_JSON = ExportFormat.JSON


class AsyncExportClient:
    """Downloads the public export files of `export.white.market`.

    Without `http_client` the SDK creates an httpx client with the connect and idle timeouts of
    `options` and no total timeout, and closes it in `aclose()`. An injected client keeps its
    timeouts and stays open, but every request is sent with `follow_redirects=False`, `auth=None`
    and none of the client's default headers or cookies (the SDK follows redirects itself, under
    the rules of SDK_SPEC 3.10). TLS
    verification is always on.

    `cache` holds the `ETag` and `Last-Modified` of the files fetched with `conditional=True`
    (never a body).

    `max_age` of the read calls (a `timedelta` or seconds): the `.meta.json` is fetched first and a
    `data_as_of` older than that raises `StaleExportError` before the file is downloaded.
    """

    def __init__(
        self,
        *,
        options: ExportOptions | None = None,
        cache: AsyncExportCache | None = None,
        http_client: httpx.AsyncClient | None = None,
        logger: logging.Logger | None = None,
        seams: AsyncTransportSeams | None = None,
    ) -> None:
        self._options = options or ExportOptions()
        self._owned = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=http_timeout(self._options), follow_redirects=False
        )
        seams = seams or AsyncTransportSeams()
        self._clock = seams.clock
        self._transport = AsyncExportTransport(
            self._http, self._options, cache=cache, logger=logger, seams=seams
        )

    async def meta(
        self,
        kind: ExportKind,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        format: ExportFormat = _JSON,
    ) -> ExportMeta:
        """The freshness sidecar `<file>.meta.json` of an export file."""
        return await self._fetch_meta(self._file_url(kind, app, window, format))

    @overload
    async def prices(
        self,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        *,
        conditional: Literal[False] = False,
        max_age: timedelta | float | None = None,
    ) -> PriceList: ...

    @overload
    async def prices(
        self,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        *,
        conditional: bool,
        max_age: timedelta | float | None = None,
    ) -> PriceList | NotModified: ...

    async def prices(
        self,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        *,
        conditional: bool = False,
        max_age: timedelta | float | None = None,
    ) -> PriceList | NotModified:
        """Download and parse the prices file (JSON; about 21 thousand rows).

        `conditional=True` sends the validators remembered for this file and returns
        `NotModified` when the server says it did not change; it needs a `cache`. The validators
        are stored only after the 200 response parsed, so a body that failed to parse never makes
        the next call answer `NotModified`.
        """
        url = self._file_url(ExportKind.PRICES, app, window, _JSON)
        if conditional and not self._transport.has_cache:
            raise ValueError("a conditional call needs a cache: pass cache= to the export client")
        await self._assert_fresh(url, max_age)
        if conditional:
            fetched = await self._transport.get_if_modified(url)
            if isinstance(fetched, NotModified):
                return fetched
            body = fetched
        else:
            body = await self._transport.get(url)
        data = await self._read_whole(body)
        price_list = PriceList(iter_price_rows(body_pieces(data)))
        if conditional:
            await self._transport.remember(body)
        return price_list

    async def stream_prices(
        self,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        *,
        max_age: timedelta | float | None = None,
    ) -> AsyncRowStream[PriceRow]:
        """The rows of the prices file, in file order.

        The file is small: the body is read whole (bounded by `max_body_bytes` decoded) and parsed
        before this returns, so it saves no memory over `prices()`; it exists for the iterator
        shape of the spec. The requests are sent by this call, not by the first iteration.
        """
        url = self._file_url(ExportKind.PRICES, app, window, _JSON)
        await self._assert_fresh(url, max_age)
        body = await self._transport.get(url)
        data = await self._read_whole(body)
        return AsyncRowStream(replay(list(iter_price_rows(body_pieces(data)))), body)

    async def stream_products(
        self,
        app: int = DEFAULT_APP,
        window: ExportWindow | None = None,
        format: ExportFormat = _JSON,
        *,
        max_age: timedelta | float | None = None,
    ) -> AsyncRowStream[ProductRow]:
        """The rows of the products file (millions of lots), parsed as the body arrives.

        One row is in memory at a time and the body has no size limit. The requests are sent by
        this call, so a status other than 200 fails here; a row that does not decode, or a body
        that breaks off, fails at that row of the iteration, after the rows before it. A row whose
        category is null is skipped (the server sends a few). Stop early with `aclose()` (or
        `async with`): the connection is closed.
        """
        url = self._file_url(ExportKind.PRODUCTS, app, window, format)
        await self._assert_fresh(url, max_age)
        body = await self._transport.get(url)
        return AsyncRowStream(aiter_product_rows(body.chunks(), format), body)

    async def download(
        self,
        kind: ExportKind,
        app: int,
        window: ExportWindow | None,
        format: ExportFormat,
        destination: str | os.PathLike[str] | BinaryIO,
    ) -> None:
        """Write the decoded file to `destination` as it arrives: no memory held, no size limit.

        A path is written through a private temporary file next to it (`.<name>.<random>.part`)
        and renamed over it when complete; on failure the temporary file is removed and the path
        is untouched. A binary file object is written as is, flushed on success, left open and
        unrewound. A destination that cannot be written is a `GeneralExportError`.
        """
        url = self._file_url(kind, app, window, format)
        sink = await async_acquire_blocking(open_sink, abort_sink, destination)
        body = None
        try:
            body = await self._transport.get(url)
            async for chunk in body.chunks():
                await async_run_blocking(sink.write, chunk)
            await async_run_blocking(sink.commit)
        except BaseException:
            await async_run_blocking(sink.abort)
            raise
        finally:
            if body is not None:
                await body.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client the SDK created (an injected one stays open)."""
        if self._owned:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncExportClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self._options.base_url!r})"

    def _file_url(
        self, kind: ExportKind, app: int, window: ExportWindow | None, format: ExportFormat
    ) -> str:
        return export_file_url(self._options.base_url, kind, app, window, format)

    async def _read_whole(self, body: AsyncExportBody) -> BodyBytes:
        return await body.read(self._options.max_body_bytes)

    async def _fetch_meta(self, file_url: str) -> ExportMeta:
        body = await self._transport.get(file_url + META_SUFFIX)
        return parse_meta(await self._read_whole(body))

    async def _assert_fresh(self, file_url: str, max_age: timedelta | float | None) -> None:
        seconds = max_age_seconds(max_age)
        if seconds is None:
            return
        meta = await self._fetch_meta(file_url)
        now: datetime = self._clock()
        if (now - meta.data_as_of).total_seconds() > seconds:
            raise StaleExportError(meta.data_as_of, seconds)
