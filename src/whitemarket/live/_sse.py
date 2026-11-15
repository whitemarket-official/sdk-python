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
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

import httpx

from whitemarket._runtime.log_redaction import redact_url
from whitemarket._runtime.retry_after import parse_retry_after
from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import DecodeError, TransportError
from whitemarket.live._connection import (
    BUFFER_BYTES,
    Incoming,
    ServerClosedError,
    StatusFailureError,
    queue_size,
)
from whitemarket.live._envelope import (
    ConnectReply,
    Disconnect,
    OtherMessage,
    Publication,
    decode_message,
)
from whitemarket.live._policy import ConnectInfo, is_personal
from whitemarket.live._sse_parser import SseParser
from whitemarket.live.options import LiveOptions

# The pump stops reading (TCP backpressure) when `queue_size` events wait for the consumer.
_HTTP_OK: Final = range(200, 300)


class _Ended:
    """The stream ended or failed."""


# A message before the connect reply: the raw text of a data message, a decoded one, or the error.
_Early = str | Incoming | DecodeError


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
        early_text_limit: int = BUFFER_BYTES,
    ) -> None:
        self._url = url
        self._user_agent = user_agent
        self._options = options
        self._trust_env = trust_env
        self._early_text_limit = early_text_limit
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._pump: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[str | _Ended] = asyncio.Queue(self._queue_size())
        # Messages that came before the connect reply; `read` returns them first.
        self._early: deque[_Early] = deque()

    def _queue_size(self) -> int:
        return queue_size(self._options.max_message_bytes)

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
            channel: {} for channel in channels if not is_personal(channel)
        }
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
        result = await _send(client, _connect_url(self._url, token, subs), headers)
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
        queue: asyncio.Queue[str | _Ended] = asyncio.Queue(self._queue_size())
        self._queue = queue
        self._pump = asyncio.create_task(
            _pump(response, SseParser(self._options.max_message_bytes), queue)
        )
        info, self._early = await _until_connect_reply(queue, self._early_text_limit)
        return info

    async def read(self, seconds: float | None) -> Incoming | None:
        if self._early:
            early = self._early.popleft()
            if isinstance(early, DecodeError):
                raise early
            if isinstance(early, str):
                return decode_message(early)  # the raw text of a data message, decoded once before
            return early
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
        self._early = deque()
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


def _connect_url(base: str, token: Secret, subs: dict[str, dict[str, str]]) -> str:
    """The stream URL with the connect command; built inline so no frame that can raise keeps it."""
    connect = json.dumps({"token": token.reveal(), "subs": subs}, separators=(",", ":"))
    return f"{base}?cf_connect={quote(connect, safe='')}"


async def _send(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> httpx.Response | str:
    """The streaming response, or the name of the httpx error class (never the error itself)."""
    try:
        request = client.build_request("GET", url, headers=headers)
        return await client.send(request, stream=True, follow_redirects=False, auth=None)
    except httpx.HTTPError as error:
        return type(error).__name__


async def _until_connect_reply(
    queue: "asyncio.Queue[str | _Ended]", text_limit: int
) -> tuple[ConnectInfo, deque[_Early]]:
    """Wait for the connect reply. The server sometimes sends publications before it, more than
    the queue holds (WHITEMARKET_API.md 11, observed 2026-11-15): every message before the reply
    is kept and returned with it for `read` to deliver first, in order. Their raw text
    is bounded by `text_limit` (characters; default the queue's byte budget), their time by the
    connect timeout."""
    early: deque[_Early] = deque()
    early_chars = 0
    while True:
        item = await queue.get()
        if isinstance(item, _Ended):
            raise TransportError("the live stream ended before the connect reply")
        try:
            message: Incoming | DecodeError = decode_message(item)
        except DecodeError as error:
            message = error.with_traceback(None)  # `read` raises it as after the reply
        if isinstance(message, ConnectReply):
            info = ConnectInfo.from_reply(message.ping, message.pong, message.ttl, message.expires)
            return info, early
        if isinstance(message, Disconnect):
            raise ServerClosedError(message.code, message.reason)
        early_chars += len(item)
        if early_chars > text_limit:
            raise TransportError("the live stream sent too much data before the connect reply")
        # The decoded form of a message can be far larger than its text (nested empty lists:
        # ~20x), so the data-bearing kinds are kept as text, as `_ws.py` `_message` does.
        early.append(item if isinstance(message, Publication | OtherMessage) else message)


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
