"""The live session engine (SDK_SPEC 3.11): reconnect, deadlines, token handling, dispatch.

A port of the PHP `LiveSession`. Pull-driven: all work happens inside `connect()`, `poll()` and
`close()`, on the caller's task, so a handler exception propagates out of the call that
dispatched it and `close()` leaves nothing running except what the connection owns (it closes
that too). Time comes from an injected monotonic clock, sleeper and random source.
"""

import asyncio
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable
from typing import Final, NoReturn, Protocol

from whitemarket._runtime.secret import Secret
from whitemarket.errors.base import (
    DecodeError,
    LiveConnectionError,
    TransportError,
    WhiteMarketError,
)
from whitemarket.errors.http import AuthenticationError, HttpError
from whitemarket.live import _policy as policy
from whitemarket.live._connection import (
    HTTP_SERVER_ERRORS,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_UNAUTHORIZED,
    Connection,
    ConnectRejectedError,
    ServerClosedError,
    StatusFailureError,
    http_error,
)
from whitemarket.live._handlers import LiveDisconnected
from whitemarket.live.envelope import (
    Disconnect,
    Publication,
    Reply,
    Unsubscribe,
    map_publication,
)
from whitemarket.live.events import LiveEvent
from whitemarket.live.options import LiveOptions

_LOGGER: Final = logging.getLogger("whitemarket.live")
_INF: Final = math.inf
_SYSTEM_RANDOM: Final = random.SystemRandom().random


class TokenSource(Protocol):
    """The client's access tokens: `access_token()` is valid now, `refresh()` forces a new one."""

    async def access_token(self) -> Secret: ...

    async def refresh(self) -> Secret: ...


class Sink(Protocol):
    """Where the engine reports. `LiveHandlers` is one; the threaded session queues instead."""

    async def event(self, event: LiveEvent) -> None: ...

    async def connecting(self) -> None: ...

    async def connected(self, reconnected: bool) -> None: ...

    async def disconnected(self, info: LiveDisconnected) -> None: ...

    async def error(self, error: Exception) -> None: ...


class Engine:
    def __init__(
        self,
        *,
        tokens: TokenSource,
        connection: Connection,
        options: LiveOptions,
        sink: Sink,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = _SYSTEM_RANDOM,
    ) -> None:
        self._tokens = tokens
        self._connection = connection
        self._options = options
        self._sink = sink
        self._clock = clock
        self._sleeper = sleeper
        self._random = random_source

        self._channels: list[str] = []
        self._pending: list[str] = []
        self._closed = False
        self._connected = False
        self._ever_connected = False
        self._force_refresh = False
        self._auth_retried = False
        self._refresh_used_in_streak = False
        self._attempt = 0
        self._other_closes = 0
        self._next_attempt_at = 0.0
        self._connected_at = 0.0
        self._idle_seconds: float | None = None
        self._idle_deadline: float | None = None
        self._refresh_at: float | None = None
        self._polling = False

    # --- public ----------------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    def now(self) -> float:
        """The engine clock, for deadlines that must agree with it."""
        return self._clock()

    def subscribe(self, channel: str) -> None:
        """Add a channel. On an open WebSocket it is subscribed by the next `poll()`; on SSE the
        session reconnects with the new list. Personal channels are never subscribed."""
        if self._closed or channel in self._channels:
            return
        self._channels.append(channel)
        if self._connected:
            self._pending.append(channel)

    async def connect(self) -> None:
        """Connect now and return once connected ; a terminal failure raises."""
        self._enter()
        try:
            while not self._closed and not self._connected:
                await self._attempt_connect(_INF)
        finally:
            self._polling = False

    async def poll(self, wait: float | None = None) -> LiveEvent | None:
        """The next event after its handlers ran, or `None` after `wait` seconds (`None`: no
        limit) or once closed. Connects and reconnects as needed. Raises `LiveConnectionError` or
        an `HttpError` on a terminal failure, and whatever a handler raises."""
        self._enter()
        try:
            return await self._poll(_INF if wait is None else self._now() + wait)
        finally:
            self._polling = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        was_connected = await self._end_connection()
        _LOGGER.info("live: closed (attempt %d)", self._attempt)
        if was_connected:
            await self._sink.disconnected(LiveDisconnected(None, "", False))

    # --- the loop --------------------------------------------------------------------------

    def _enter(self) -> None:
        if self._polling:
            raise RuntimeError("a live session has one consumer: connect() or poll() is running")
        self._polling = True

    async def _poll(self, until: float) -> LiveEvent | None:
        while not self._closed:
            if not self._connected:
                await self._attempt_connect(until)
                if not self._connected and self._reached(until):
                    return None
                continue
            if self._pending:
                await self._flush_subscriptions()
                continue
            if self._refresh_at is not None and self._reached(self._refresh_at):
                await self._scheduled_refresh()
                continue
            if self._idle_deadline is not None and self._reached(self._idle_deadline):
                await self._reconnect_after_backoff()
                continue
            deadline = min(until, self._idle_deadline or _INF, self._refresh_at or _INF)
            event = await self._read_once(deadline)
            if event is not None:
                return event
            if self._reached(until):
                return None
        return None

    async def _attempt_connect(self, until: float) -> None:
        now = self._now()
        if not self._reached(self._next_attempt_at):
            wait = min(self._next_attempt_at - now, until - now)
            if wait > 0:
                await self._sleeper(wait)
            return
        await self._sink.connecting()
        if self._closed:
            return
        try:
            token = await (
                self._tokens.refresh() if self._force_refresh else self._tokens.access_token()
            )
            self._force_refresh = False
        except AuthenticationError as error:
            await self._terminate(await self._end_connection(), error, None, "")
        except HttpError as error:
            await self._handle_http_failure(
                error.status, getattr(error, "retry_after", None), False, error
            )
            return
        except WhiteMarketError as error:
            await self._handle_failed_attempt(error)
            return
        await self._open(token)

    async def _open(self, token: Secret) -> None:
        try:
            info = await self._connection.open(token, self._channels, self._options.connect_timeout)
        except ConnectRejectedError as rejected:
            await self._handle_connect_rejected(rejected)
        except ServerClosedError as closed:
            await self._handle_close_code(closed.code, closed.reason)
        except StatusFailureError as failure:
            await self._handle_http_failure(failure.status, failure.retry_after, True, None)
        except TransportError as error:
            await self._handle_failed_attempt(error)
        else:
            await self._established(info)

    async def _established(self, info: policy.ConnectInfo) -> None:
        now = self._now()
        ttl = info.ttl
        short_lived = ttl is not None and ttl <= policy.REFRESH_BELOW
        if short_lived and not self._refresh_used_in_streak:
            self._refresh_used_in_streak = True
            await self._reconnect_now("token refresh", True)
            return
        # A short-lived token that was refreshed once in this streak: the provider cannot renew,
        # keep this connection and let the server end it at expiry.
        self._connected = True
        self._connected_at = now
        self._idle_seconds = info.idle_seconds
        self._idle_deadline = None if self._idle_seconds is None else now + self._idle_seconds
        self._refresh_at = None if ttl is None or short_lived else now + ttl - policy.REFRESH_BELOW
        self._next_attempt_at = 0.0
        self._pending.clear()
        _LOGGER.info("live: connected (attempt %d)", self._attempt)
        reconnected = self._ever_connected
        self._ever_connected = True
        await self._sink.connected(reconnected)

    async def _read_once(self, deadline: float) -> LiveEvent | None:
        remaining = None if deadline == _INF else max(0.0, deadline - self._now())
        try:
            message = await self._connection.read(remaining)
        except DecodeError as error:
            self._touch_idle()
            await self._sink.error(error)
            return None
        except ServerClosedError as closed:
            if not self._closed:
                await self._handle_close_code(closed.code, closed.reason)
            return None
        except TransportError:
            if not self._closed:  # `close()` woke the reader
                await self._reconnect_after_backoff()
            return None
        if message is None:
            return None
        self._touch_idle()
        return await self._process(message)

    def _touch_idle(self) -> None:
        if self._idle_seconds is not None:
            self._idle_deadline = self._now() + self._idle_seconds

    async def _process(self, message: object) -> LiveEvent | None:
        if isinstance(message, Publication):
            mapped = map_publication(message)
            if mapped.error is not None:
                await self._sink.error(mapped.error)
            await self._sink.event(mapped.event)
            return mapped.event
        if isinstance(message, Reply):
            await self._handle_reply(message)
        elif isinstance(message, Disconnect):
            await self._handle_close_code(message.code, message.reason)
        elif isinstance(message, Unsubscribe):
            await self._handle_unsubscribe(message)
        # A ping (the connection answers it), a mid-stream connect reply and a kind we do not
        # model only move the idle deadline (rule 5).
        return None

    async def _handle_reply(self, reply: Reply) -> None:
        error = reply.error
        if error is None or error.code == policy.ALREADY_SUBSCRIBED_REPLY:
            return  # a success, or "already subscribed", which counts as subscribed
        if error.code == policy.AUTH_EXPIRED_REPLY:
            await self._handle_auth_rejection(error.code, error.message, None)
            return
        await self._sink.error(LiveConnectionError(error.code, error.message))

    async def _flush_subscriptions(self) -> None:
        channels, self._pending = self._pending, []
        for channel in channels:
            if not self._connected:
                return
            await self._subscribe_or_reconnect(channel, "subscriptions changed", True)

    async def _subscribe_or_reconnect(
        self, channel: str, reason: str, user_triggered: bool
    ) -> None:
        if self._connection.can_subscribe_after_connect:
            try:
                await self._connection.subscribe(channel)
            except TransportError:
                await self._reconnect_after_backoff()
            return
        if user_triggered:
            await self._reconnect_now(reason, False)
        else:
            await self._reconnect_server_triggered(reason, False)

    async def _handle_unsubscribe(self, message: Unsubscribe) -> None:
        if message.code >= policy.RESUBSCRIBE_FROM:
            await self._subscribe_or_reconnect(message.channel, "resubscribe", False)
            return
        self._channels = [c for c in self._channels if c != message.channel]
        await self._sink.error(LiveConnectionError(message.code, "unsubscribed by the server"))

    async def _handle_close_code(self, code: int, reason: str) -> None:
        kind = policy.classify_close(code)
        if kind is policy.CloseKind.TOKEN_INVALID:
            await self._handle_auth_rejection(code, reason, None)
        elif kind is policy.CloseKind.RECONNECT:
            if code == policy.TOKEN_EXPIRED_CLOSE and not self._refresh_used_in_streak:
                self._refresh_used_in_streak = True
                self._force_refresh = True
            await self._reconnect_after_backoff(code, reason)
        elif kind is policy.CloseKind.TERMINAL:
            await self._terminate(
                await self._end_connection(), LiveConnectionError(code, reason), code, reason
            )
        else:
            await self._reconnect_after_other_close(code, reason)

    async def _reconnect_after_other_close(self, code: int, reason: str) -> None:
        was_connected = await self._end_connection()
        self._other_closes += 1
        if self._other_closes > policy.MAX_OTHER_CLOSES:
            await self._terminate(was_connected, LiveConnectionError(code, reason), code, reason)
        await self._schedule_after_backoff(was_connected, code, reason, None)

    async def _handle_connect_rejected(self, rejected: ConnectRejectedError) -> None:
        if rejected.code == policy.AUTH_EXPIRED_REPLY:
            await self._handle_auth_rejection(rejected.code, "", None)
        elif rejected.temporary:
            await self._handle_failed_attempt(rejected_as_error(rejected))
        else:
            await self._terminate(
                await self._end_connection(), LiveConnectionError(rejected.code), rejected.code, ""
            )

    async def _handle_http_failure(
        self,
        status: int,
        retry_after: float | None,
        from_stream: bool,
        original: HttpError | None,
    ) -> None:
        """401 from the stream refreshes once (a provider's 401 is final); 429 and 5xx reconnect
        (`Retry-After` lengthens the wait, at most 5 minutes); other statuses stop."""
        if status == HTTP_UNAUTHORIZED and from_stream:
            await self._handle_auth_rejection(status, "", None)
        elif status == HTTP_TOO_MANY_REQUESTS or status in HTTP_SERVER_ERRORS:
            error = original if original is not None else http_error(status, retry_after)
            await self._handle_failed_attempt(error, retry_after)
        else:
            error = original if original is not None else http_error(status, retry_after)
            await self._terminate(await self._end_connection(), error, None, "")

    async def _handle_failed_attempt(
        self, error: Exception, retry_after: float | None = None
    ) -> None:
        min_wait = None if retry_after is None else min(retry_after, policy.MAX_RETRY_AFTER)
        await self._reconnect_after_backoff(min_wait=min_wait)
        await self._sink.error(error)

    async def _handle_auth_rejection(
        self, code: int, reason: str, original: HttpError | None
    ) -> None:
        was_connected = await self._end_connection()
        if self._auth_retried:
            await self._terminate(
                was_connected,
                original if isinstance(original, AuthenticationError) else AuthenticationError(),
                code,
                reason,
            )
        self._auth_retried = True
        self._force_refresh = True
        await self._schedule_now(was_connected, code, reason)

    async def _reconnect_now(self, reason: str, refresh: bool) -> None:
        was_connected = await self._end_connection()
        self._force_refresh = self._force_refresh or refresh
        await self._schedule_now(was_connected, None, reason)

    async def _scheduled_refresh(self) -> None:
        """The scheduled token refresh is due. One already done in this streak waits until this
        connection has been up `STABLE_AFTER`, so a server that always reports a near ttl costs
        one refresh per streak, not one per backoff cycle."""
        if self._refresh_used_in_streak and not self._connected_long_enough():
            self._refresh_at = self._connected_at + policy.STABLE_AFTER
            return
        await self._reconnect_server_triggered("token refresh", True)
        self._refresh_used_in_streak = True

    async def _reconnect_server_triggered(self, reason: str, refresh: bool) -> None:
        """A reconnect a server message asks for is immediate only after a connection that stayed
        up `STABLE_AFTER`; otherwise it is a counted backoff attempt, so a server cannot make the
        session spin."""
        if self._connected and self._connected_long_enough():
            await self._reconnect_now(reason, refresh)
            return
        self._force_refresh = self._force_refresh or refresh
        await self._reconnect_after_backoff(None, reason)

    async def _reconnect_after_backoff(
        self, code: int | None = None, reason: str = "", min_wait: float | None = None
    ) -> None:
        await self._schedule_after_backoff(await self._end_connection(), code, reason, min_wait)

    async def _schedule_now(self, was_connected: bool, code: int | None, reason: str) -> None:
        self._next_attempt_at = self._now()
        await self._announce_disconnect(was_connected, code, reason)

    async def _schedule_after_backoff(
        self, was_connected: bool, code: int | None, reason: str, min_wait: float | None
    ) -> None:
        self._attempt += 1
        cap = self._options.max_reconnect_attempts
        if cap is not None and self._attempt > cap:
            await self._terminate(
                was_connected,
                LiveConnectionError(code, "reconnect attempts exhausted"),
                code,
                reason,
            )
        delay = policy.backoff_delay(self._attempt, self._random())
        self._next_attempt_at = self._now() + max(min_wait or 0.0, delay)
        await self._announce_disconnect(was_connected, code, reason)

    async def _announce_disconnect(
        self, was_connected: bool, code: int | None, reason: str
    ) -> None:
        _LOGGER.info("live: disconnected (code %s, attempt %d)", code, self._attempt)
        if was_connected:
            await self._sink.disconnected(LiveDisconnected(code, reason, True))

    async def _terminate(
        self, was_connected: bool, error: Exception, code: int | None, reason: str
    ) -> NoReturn:
        self._closed = True
        _LOGGER.info("live: stopped (code %s, attempt %d)", code, self._attempt)
        if was_connected:
            await self._sink.disconnected(LiveDisconnected(code, reason, False))
        raise error

    async def _end_connection(self) -> bool:
        """Release the connection; True when it had been announced as connected. A connection that
        stayed up `STABLE_AFTER` ends the streak: counters reset."""
        was_connected = self._connected
        if was_connected and self._connected_long_enough():
            self._attempt = 0
            self._auth_retried = False
            self._refresh_used_in_streak = False
            self._other_closes = 0
        self._connected = False
        self._refresh_at = None
        self._idle_deadline = None
        await self._connection.close()
        return was_connected

    def _now(self) -> float:
        return self._clock()

    def _connected_long_enough(self) -> bool:
        return self._reached(self._connected_at + policy.STABLE_AFTER)

    def _reached(self, moment: float) -> bool:
        return self._now() >= moment - policy.EPSILON


def rejected_as_error(rejected: ConnectRejectedError) -> LiveConnectionError:
    """A temporary connect rejection for `on_error`: the code only, no server text."""
    return LiveConnectionError(rejected.code)
