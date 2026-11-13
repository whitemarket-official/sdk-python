"""SSE live connection: one HTTPS GET with `cf_connect`, read as an event stream (SDK_SPEC 3.11).

Own parser over httpx streaming (Centrifugo's unidirectional SSE has one `data:` JSON line per
event, WHITEMARKET_API.md 9). The GET never follows a redirect (SDK_SPEC 1.3), asks for no
compression, and its URL holds the credential (`cf_connect`): nothing here logs it, and the
`httpx` request log record is redacted while a connection exists.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

import httpx

from whitemarket._runtime.log_redaction import redact_url
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import Incoming, ServerClosedError, StatusFailureError
from whitemarket.live._policy import ConnectInfo
from whitemarket.live.envelope import ConnectReply, Disconnect, decode_message
from whitemarket.live.options import LiveOptions
from whitemarket.live.sse_parser import SseParser
from whitemarket.retry import parse_retry_after

QUEUE_SIZE: Final = 4096
_HTTP_OK: Final = range(200, 300)


class _Ended:
    """The stream ended or failed."""


class _RedactCfConnect(logging.Filter):
    """`httpx` logs `HTTP Request: GET <url>` at INFO, and the SSE URL carries the JWT."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_url(str(arg)) if "cf_connect" in str(arg) else arg for arg in record.args
            )
        return True


_REDACT: Final = _RedactCfConnect()


def _redact_httpx_log() -> None:
    logger = logging.getLogger("httpx")
    if _REDACT not in logger.filters:
        logger.addFilter(_REDACT)


class SseConnection:
    can_subscribe_after_connect = False

    def __init__(
        self,
        url: str,
        user_agent: str,
        options: LiveOptions,
        *,
        trust_env: bool = True,
    ) -> None:
        self._url = url
        self._user_agent = user_agent
        self._options = options
        self._trust_env = trust_env
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._pump: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[str | _Ended] = asyncio.Queue(QUEUE_SIZE)

    async def open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo:
        await self.close()
        _redact_httpx_log()
        try:
            async with asyncio.timeout(seconds):
                return await self._open(token, channels, seconds)
        except TimeoutError:
            await self.close()
            raise TransportError("the live connection sent no connect reply in time") from None
        except BaseException:
            await self.close()
            raise

    async def _open(self, token: Secret, channels: Sequence[str], seconds: float) -> ConnectInfo:
        subs: dict[str, dict[str, str]] = {
            channel: {} for channel in channels if not channel.startswith("#")
        }
        connect = json.dumps({"token": token.reveal(), "subs": subs}, separators=(",", ":"))
        url = f"{self._url}?cf_connect={quote(connect, safe='')}"
        client = httpx.AsyncClient(
            follow_redirects=False,
            trust_env=self._trust_env,
            timeout=httpx.Timeout(connect=seconds, read=None, write=seconds, pool=seconds),
        )
        self._client = client
        headers = {
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity",
            "User-Agent": self._user_agent,
        }
        result = await _send(client, url, headers)
        if isinstance(result, str):
            # Raised outside any `except` block: an httpx error holds the request, whose URL holds
            # the token, and a raise inside one would keep it as `__context__`.
            raise TransportError(f"the live HTTP request failed ({result})")
        response = result
        self._response = response
        if response.status_code not in _HTTP_OK:
            retry_after = parse_retry_after(response.headers.get("Retry-After"), datetime.now(UTC))
            raise StatusFailureError(response.status_code, retry_after)
        encoding = response.headers.get("Content-Encoding", "").strip().lower()
        if encoding not in ("", "identity"):
            raise TransportError(
                "the live stream has a content encoding although none was accepted"
            )
        queue: asyncio.Queue[str | _Ended] = asyncio.Queue(QUEUE_SIZE)
        self._queue = queue
        self._pump = asyncio.create_task(
            _pump(response, SseParser(self._options.max_message_bytes), queue)
        )
        return _connect_info(await self._first(queue))

    async def _first(self, queue: "asyncio.Queue[str | _Ended]") -> str:
        item = await queue.get()
        if isinstance(item, _Ended):
            raise TransportError("the live stream ended before the connect reply")
        return item

    async def read(self, seconds: float | None) -> Incoming | None:
        try:
            item = await asyncio.wait_for(self._queue.get(), seconds)
        except TimeoutError:
            return None
        if isinstance(item, _Ended):
            raise TransportError("the live stream ended")
        return decode_message(item)

    async def subscribe(self, channel: str) -> None:
        raise TransportError("SSE subscribes at connect time; reconnect with the new channel list")

    async def close(self) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(
                _Ended()
            )  # wakes a reader blocked in `read` (close from another task)
        pump, self._pump = self._pump, None
        response, self._response = self._response, None
        client, self._client = self._client, None
        if pump is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump
        if response is not None:
            with contextlib.suppress(Exception):
                await response.aclose()
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()


async def _send(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> httpx.Response | str:
    """The streaming response, or the name of the httpx error class (never the error itself)."""
    try:
        request = client.build_request("GET", url, headers=headers)
        return await client.send(request, stream=True, follow_redirects=False)
    except httpx.HTTPError as error:
        return type(error).__name__


def _connect_info(first: str) -> ConnectInfo:
    try:
        message = decode_message(first)
    except DecodeError:
        raise TransportError("the first live message is not a valid message") from None
    if isinstance(message, Disconnect):
        raise ServerClosedError(message.code, message.reason)
    if not isinstance(message, ConnectReply):
        raise TransportError("the first live message is not a connect reply")
    return ConnectInfo.from_reply(message.ping, message.pong, message.ttl, message.expires)


async def _pump(
    response: httpx.Response, parser: SseParser, queue: "asyncio.Queue[str | _Ended]"
) -> None:
    """Read the body into the queue. A full queue stops the read: TCP backpressure."""
    try:
        async for chunk in response.aiter_bytes():
            try:
                parser.feed(chunk)
            finally:  # events completed before a size-limit error are still delivered
                while (data := parser.next()) is not None:
                    await queue.put(data)
    except (httpx.HTTPError, TransportError):
        pass  # the end marker below tells the reader; no detail that could hold the URL
    await queue.put(_Ended())
