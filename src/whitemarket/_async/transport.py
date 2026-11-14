"""GraphQL over HTTP: headers, retries for queries, size limit, status mapping (SDK_SPEC 1.3, 1.4).

Hand-written async; the sync twin is generated (tools/unasync.py). One request per call, never a
redirect, never a retry of a mutation. httpx facts behind these choices: docs/decisions/0002.
"""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from whitemarket._async.http_reply import (
    HttpReply,
    NoReply,
    failure_name,
    read_error_excerpt,
)
from whitemarket._async.seams import AsyncTransportSeams
from whitemarket._concurrency import AsyncDeadline
from whitemarket._runtime.body import BodyAccumulator, BodyBytes, BodyError, body_is_gzip
from whitemarket._runtime.http_errors import http_error_for
from whitemarket._runtime.log_redaction import redact_headers, redact_url
from whitemarket._runtime.operation import OperationType
from whitemarket._runtime.retry_after import retry_after_for
from whitemarket._runtime.safe_log import LOGGER_NAME, SafeLog
from whitemarket._runtime.secret import Secret
from whitemarket._runtime.transport_config import TransportConfig
from whitemarket.errors.base import TransportError

_SUCCESS_LOWER, _SUCCESS_UPPER = 200, 299


@dataclass(frozen=True, slots=True)
class AsyncHttpClients:
    """The httpx clients of one SDK client.

    `query` serves queries and keeps connections alive. `mutation` serves mutations on a
    connection that is never reused (ADR 0002). An injected client (`owned=False`) serves both and
    is neither reconfigured nor closed, but every request is sent with `follow_redirects=False` and
    `auth=None`, whatever the client was set up with (the credential must not follow a redirect).
    """

    query: httpx.AsyncClient
    mutation: httpx.AsyncClient
    owned: bool

    @classmethod
    def create(
        cls, config: TransportConfig, injected: httpx.AsyncClient | None
    ) -> "AsyncHttpClients":
        if injected is not None:
            return cls(injected, injected, owned=False)
        timeout = _httpx_timeout(config)
        # `follow_redirects=False` is httpx's default; it is set explicitly because the credential
        # must never follow a redirect. `verify` is left at its default (on): no switch for TLS.
        query = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        mutation = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        return cls(query, mutation, owned=True)

    async def aclose(self) -> None:
        """Close what the SDK created; an injected client stays open."""
        if not self.owned:
            return
        await self.query.aclose()
        await self.mutation.aclose()


def _httpx_timeout(config: TransportConfig) -> httpx.Timeout:
    seconds = config.timeouts.request
    return httpx.Timeout(seconds, connect=config.timeouts.connect)


class AsyncGraphQLTransport:
    """Posts GraphQL request bodies; the only place that talks HTTP."""

    def __init__(
        self,
        clients: AsyncHttpClients,
        config: TransportConfig,
        *,
        logger: logging.Logger | None = None,
        seams: AsyncTransportSeams | None = None,
    ) -> None:
        self._clients = clients
        self._config = config
        self._log = SafeLog(logger or logging.getLogger(LOGGER_NAME))
        seams = seams or AsyncTransportSeams()
        self._clock = seams.clock
        self._sleeper = seams.sleeper
        self._random = seams.random
        if not clients.owned:
            self._log.info(
                "WhiteMarket SDK: the injected HTTP client keeps its own settings; the SDK "
                "timeouts are not applied to it. Every request is still sent without redirects and "
                "without the client's auth."
            )

    async def post(
        self,
        operation_name: str,
        operation_type: OperationType,
        body: bytes,
        headers: Mapping[str, Secret],
    ) -> BodyBytes:
        """The body of the 2xx answer.

        Raises an `HttpError` subclass for any other status once the retry policy gives up, and
        `TransportError` when no answer could be read. A mutation is sent once.
        """
        policy = self._config.retry
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            outcome = await self._attempt(operation_type, body, headers)
            status = outcome.status if isinstance(outcome, HttpReply) else None
            self._log.debug(
                "WhiteMarket API request: operation=%s type=%s attempt=%d status=%s duration_ms=%d",
                operation_name,
                operation_type,
                attempt,
                status,
                int((time.monotonic() - started) * 1000),
            )
            if isinstance(outcome, HttpReply):
                if _SUCCESS_LOWER <= outcome.status <= _SUCCESS_UPPER:
                    return outcome.body
                retry_after = self._retry_after(outcome)
                if not policy.should_retry(operation_type, attempt, outcome.status, retry_after):
                    raise http_error_for(outcome.status, bytes(outcome.body), retry_after)
            elif not policy.should_retry(operation_type, attempt, None):
                raise TransportError(f"WhiteMarket API {outcome.what} on {operation_name}")
            delay = policy.delay(attempt, self._random())
            self._log.debug("WhiteMarket API retry: operation=%s delay=%.3f", operation_name, delay)
            await self._sleeper(delay)

    def _retry_after(self, reply: HttpReply) -> int | None:
        return retry_after_for(reply.status, reply.retry_after_header, self._clock())

    def _request_headers(
        self, operation_type: OperationType, secrets: Mapping[str, Secret]
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # gzip only: the body reader below decodes it with a size bound.
            "Accept-Encoding": "gzip",
            "User-Agent": self._config.user_agent,
        }
        if operation_type == "mutation" and self._clients.owned:
            headers["Connection"] = "close"
        for name, secret in secrets.items():
            headers[name] = secret.reveal()
        # The allow-list redaction is what keeps credentials out of the log.
        self._log.debug("WhiteMarket API request headers: %s", redact_headers(headers))
        return headers

    async def _attempt(
        self, operation_type: OperationType, body: bytes, secrets: Mapping[str, Secret]
    ) -> HttpReply | NoReply:
        client = self._clients.mutation if operation_type == "mutation" else self._clients.query
        headers = self._request_headers(operation_type, secrets)
        timeouts = self._config.timeouts
        self._log.debug("WhiteMarket API POST %s", redact_url(self._config.graphql_url))
        request = client.build_request(
            "POST",
            self._config.graphql_url,
            content=body,
            headers=headers,
        )
        # Whatever fails below is reported by name only and raised AFTER the except blocks: an httpx
        # error holds the request (with its credential header), so it must not become a __context__.
        reply: HttpReply | None = None
        failure = ""
        sent = False
        try:
            async with AsyncDeadline(timeouts.request if self._clients.owned else None) as deadline:
                response = await client.send(
                    request, stream=True, follow_redirects=False, auth=None
                )
                sent = True
                try:
                    reply = await self._read(response, deadline.check)
                finally:
                    await response.aclose()
        except BodyError as error:
            failure = str(error)
        except TimeoutError:
            failure = "timed out"
        except httpx.HTTPError as error:
            failure = failure_name(error)
        if reply is not None:
            return reply
        if not sent:
            return NoReply(failure)
        raise TransportError(f"WhiteMarket API could not read the response: {failure}")

    async def _read(self, response: httpx.Response, check: Callable[[], None]) -> HttpReply:
        status = response.status_code
        retry_after = response.headers.get("retry-after")
        if not _SUCCESS_LOWER <= status <= _SUCCESS_UPPER:
            return HttpReply(status, retry_after, await read_error_excerpt(response, check))
        accumulator = BodyAccumulator(
            limit=self._config.max_response_bytes,
            gzip=body_is_gzip(response.headers.get("content-encoding")),
        )
        async for chunk in response.aiter_raw():
            accumulator.feed(chunk)
            if accumulator.done:
                break
            check()
        return HttpReply(status, retry_after, accumulator.finish())
