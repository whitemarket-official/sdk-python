"""GETs of export files: gzip, redirects, retries, bounded and complete bodies (SDK_SPEC 3.10).

Hand-written async; the sync twin is generated (tools/unasync.py). No credential travels here:
the export is public, and no header other than the ones built in `_headers` is ever sent.
"""

import logging
import time
from collections.abc import AsyncIterator

import httpx

from whitemarket._async.export_cache import AsyncExportCache
from whitemarket._async.http_reply import (
    HttpReply,
    NoReply,
    failure_name,
    read_error_excerpt,
)
from whitemarket._async.seams import AsyncTransportSeams
from whitemarket._runtime.body import (
    BodyAccumulator,
    BodyBytes,
    BodyError,
    announced_length,
    body_is_gzip,
)
from whitemarket._runtime.credential_format import is_valid_header_value
from whitemarket._runtime.endpoints import require_origin
from whitemarket._runtime.export_redirect import (
    MAX_REDIRECTS,
    REDIRECT_STATUSES,
    Origin,
    redirect_target,
)
from whitemarket._runtime.http_errors import http_error_for
from whitemarket._runtime.log_redaction import redact_url
from whitemarket._runtime.retry_after import retry_after_for
from whitemarket._runtime.safe_log import LOGGER_NAME, SafeLog
from whitemarket._runtime.transport_config import build_user_agent
from whitemarket.errors.base import TransportError
from whitemarket.exports.conditional import ExportValidators, NotModified
from whitemarket.exports.options import ExportOptions

_OK = 200
_NOT_MODIFIED = 304


def http_timeout(options: ExportOptions) -> httpx.Timeout:
    """Connect timeout and idle timeout (the longest silence per read); no total timeout."""
    idle = options.idle_timeout
    return httpx.Timeout(connect=options.connect_timeout, read=idle, write=idle, pool=idle)


class AsyncExportBody:
    """The body of a 200 response, not read yet, with the validators the server sent.

    Read it once, either whole and bounded (`read`) or as decoded chunks (`chunks`). Both close
    the connection when they end, fail or are stopped; `aclose` closes it for a body never read.
    """

    def __init__(
        self,
        response: httpx.Response,
        url: str,
        validators: ExportValidators | None,
        *,
        gzip: bool,
        expected_bytes: int | None,
    ) -> None:
        self._response = response
        self.url = url
        self.validators = validators
        self._gzip = gzip
        self._expected = expected_bytes
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once the connection was closed (by an end, a failure, a stop or `aclose`)."""
        return self._closed

    async def read(self, limit: int) -> BodyBytes:
        """The decoded body, at most `limit` decoded bytes; `TransportError` when it is longer,
        corrupt, cut short or unreadable."""
        body = bytearray()
        try:
            async for piece in self.chunks(limit):
                body += piece
        finally:
            await self.aclose()
        return body

    async def chunks(self, limit: int | None = None) -> AsyncIterator[bytes]:
        """The decoded body as it arrives (`limit`: at most that many decoded bytes, else no
        limit); `TransportError` when it is longer, corrupt, cut short or unreadable, at the point
        it breaks. Stopping the iteration closes the connection."""
        accumulator = BodyAccumulator(
            limit=limit, gzip=self._gzip, strict=True, expected_raw_bytes=self._expected
        )
        failure = ""
        try:
            async for raw in self._response.aiter_raw():
                for piece in accumulator.decode(raw):  # not `yield from`: none in async code
                    yield piece
            accumulator.finish()
        except Exception as error:
            failure = _failure_text(error)
        finally:
            await self.aclose()
        if failure:
            raise TransportError(f"WhiteMarket export body: {failure}")

    async def aclose(self) -> None:
        self._closed = True
        await _close(self._response)


async def _close(response: httpx.Response) -> None:
    try:
        await response.aclose()
    except Exception:
        return


def _no_check() -> None:
    """The export has no total deadline to poll between chunks."""


def _failure_text(error: Exception) -> str:
    """What a body failure says: the message of a `BodyError` (it never quotes content), else the
    class name only."""
    return str(error) if isinstance(error, BodyError) else failure_name(error)


class AsyncExportTransport:
    """GETs export URLs over one httpx client. The only place of the export side that talks HTTP.

    Every request is sent with `follow_redirects=False` and `auth=None` and carries no default
    header of the client, so an injected client cannot follow a redirect or send a credential
    here: redirects are followed by this class, under the rules of SDK_SPEC 3.10 (at most 3, same
    host and port, https).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        options: ExportOptions,
        *,
        cache: AsyncExportCache | None = None,
        logger: logging.Logger | None = None,
        seams: AsyncTransportSeams | None = None,
    ) -> None:
        self._http = http
        self._options = options
        self._cache = cache
        self._log = SafeLog(logger or logging.getLogger(LOGGER_NAME))
        seams = seams or AsyncTransportSeams()
        self._clock = seams.clock
        self._sleeper = seams.sleeper
        self._random = seams.random
        origin = Origin.of(require_origin("base_url", options.base_url))
        if origin is None:
            raise ValueError("base_url must be an https origin")
        self._origin = origin
        self._user_agent = build_user_agent(options.user_agent_suffix)

    @property
    def has_cache(self) -> bool:
        return self._cache is not None

    async def get(self, url: str) -> AsyncExportBody:
        """A 200 response of `url`; `HttpError` for any other final status."""
        outcome = await self._exchange(url, None)
        if isinstance(outcome, NotModified):
            raise TransportError("WhiteMarket export: unexpected 304")  # unreachable: no validators
        return outcome

    async def get_if_modified(self, url: str) -> AsyncExportBody | NotModified:
        """A conditional GET with the validators remembered for `url`; a 304 gives `NotModified`."""
        return await self._exchange(url, await self._recall(url))

    async def remember(self, body: AsyncExportBody) -> None:
        """Keep the validators of a 200 for the next conditional call of its URL.

        Call it once the caller has parsed the data: the validators of a body that failed to parse
        must not make the next call answer `NotModified`. A 200 without validators is stored too
        (as empty ones) when older ones are remembered, so the validators of an earlier answer are
        not sent for a newer file.
        """
        validators = body.validators
        if self._cache is None or validators is None:
            return
        try:
            if validators.is_empty and await self._cache.get(body.url) is None:
                return  # nothing remembered, nothing to forget
            await self._cache.set(body.url, validators)
        except Exception as error:
            self._log.warning("WhiteMarket export cache write failed (%s)", type(error).__name__)

    async def _exchange(
        self, url: str, validators: ExportValidators | None
    ) -> AsyncExportBody | NotModified:
        policy = self._options.retry
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            outcome = await self._attempt(url, validators)
            status = outcome.status if isinstance(outcome, HttpReply) else _OK
            self._log.debug(
                "WhiteMarket export GET %s attempt=%d status=%s duration_ms=%d",
                redact_url(url),
                attempt,
                status if not isinstance(outcome, NoReply) else None,
                int((time.monotonic() - started) * 1000),
            )
            if isinstance(outcome, HttpReply):
                retry_after = retry_after_for(
                    outcome.status, outcome.retry_after_header, self._clock()
                )
                if not policy.should_retry_export(attempt, outcome.status, retry_after):
                    raise http_error_for(outcome.status, bytes(outcome.body), retry_after)
            elif isinstance(outcome, NoReply):
                if not policy.should_retry_export(attempt, None):
                    raise TransportError(f"WhiteMarket export {outcome.what}")
            else:
                return outcome
            await self._sleeper(policy.delay(attempt, self._random()))

    async def _attempt(
        self, url: str, validators: ExportValidators | None
    ) -> AsyncExportBody | NotModified | HttpReply | NoReply:
        headers = self._headers(validators)
        current = url
        hop = 0
        while True:
            sent = await self._send(current, headers)
            if isinstance(sent, NoReply):
                return sent
            location = sent.headers.get("location", "").strip()
            if sent.status_code not in REDIRECT_STATUSES or not location:
                return await self._classify(sent, url, validators)
            await _close(sent)
            if hop >= MAX_REDIRECTS:
                raise TransportError(f"The export redirected more than {MAX_REDIRECTS} times.")
            current = redirect_target(location, self._origin)
            hop += 1

    async def _send(self, url: str, headers: dict[str, str]) -> httpx.Response | NoReply:
        # The failure is reported by name only and raised AFTER the except blocks, so an httpx
        # error (which holds the request) never becomes a __context__.
        failure = ""
        retryable = False
        try:
            # Built without `build_request`: an injected client's default headers, cookies and base
            # URL never reach the export host. `send` is told not to follow redirects (they are
            # followed here, under the rules of SDK_SPEC 3.10) and to apply no `auth`.
            request = httpx.Request(
                "GET",
                url,
                headers=headers,
                extensions={"timeout": self._http.timeout.as_dict()},
            )
            return await self._http.send(request, stream=True, follow_redirects=False, auth=None)
        except httpx.TransportError as error:
            failure, retryable = failure_name(error), True
        except Exception as error:
            failure = failure_name(error)
        if retryable:
            return NoReply(failure)
        raise TransportError(f"WhiteMarket export {failure}")

    async def _classify(
        self, response: httpx.Response, url: str, validators: ExportValidators | None
    ) -> AsyncExportBody | NotModified | HttpReply:
        status = response.status_code
        # Only a plain 200 is the file: 206 is a range, 202 and 204 carry no complete file.
        if status == _OK:
            return await self._open_body(response, url)
        if status == _NOT_MODIFIED and validators is not None:
            await _close(response)
            return NotModified(url)
        return await self._error_reply(response)

    async def _open_body(self, response: httpx.Response, url: str) -> AsyncExportBody:
        failure = ""
        gzip = False
        expected: int | None = None
        try:
            gzip = body_is_gzip(response.headers.get("content-encoding"))
            expected = announced_length(response.headers.get("content-length"))
        except BodyError as error:
            failure = str(error)
        if failure:
            await _close(response)
            raise TransportError(f"WhiteMarket export {failure}")
        validators = ExportValidators(
            etag=_header_value(response.headers.get("etag")),
            last_modified=_header_value(response.headers.get("last-modified")),
        )
        return AsyncExportBody(response, url, validators, gzip=gzip, expected_bytes=expected)

    async def _error_reply(self, response: httpx.Response) -> HttpReply:
        """The status and an excerpt of the body; a body that cannot be read is an empty excerpt."""
        body = b""
        try:
            body = await read_error_excerpt(response, _no_check)
        except Exception:
            body = b""
        finally:
            await _close(response)
        return HttpReply(response.status_code, response.headers.get("retry-after"), body)

    def _headers(self, validators: ExportValidators | None) -> dict[str, str]:
        headers = {
            "Accept-Encoding": "gzip",  # decoded by the body reader, under a size bound
            "User-Agent": self._user_agent,
        }
        if validators is not None and validators.etag is not None:
            headers["If-None-Match"] = validators.etag
        if validators is not None and validators.last_modified is not None:
            headers["If-Modified-Since"] = validators.last_modified
        return headers

    async def _recall(self, url: str) -> ExportValidators | None:
        if self._cache is None:
            return None
        try:
            entry = await self._cache.get(url)
        except Exception as error:
            self._log.warning("WhiteMarket export cache read failed (%s)", type(error).__name__)
            return None
        # What another process or version left in the cache is checked like server input: it goes
        # into request headers.
        if not isinstance(entry, ExportValidators):
            return None
        checked = ExportValidators(
            etag=_header_value(entry.etag), last_modified=_header_value(entry.last_modified)
        )
        return None if checked.is_empty else checked


def _header_value(value: object) -> str | None:
    return value if isinstance(value, str) and is_valid_header_value(value) else None
