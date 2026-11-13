"""Scripted HTTP answers for the transport tests (no network)."""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

Outcome = "Reply | Exception | Callable[[httpx.Request], httpx.Response]"


class Chunks(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A body delivered in chunks, readable by the sync and the async client."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = list(chunks)
        self.served = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.served += len(chunk)
            yield chunk

    async def __aiter__(self) -> Any:
        for chunk in self._chunks:
            self.served += len(chunk)
            yield chunk


@dataclass(frozen=True)
class Reply:
    """A scripted answer. Built into a streamed response each time it is used: a response made
    with `content=` is read at construction, which httpx then refuses to stream (and decode) again.
    """

    status: int = 200
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    def build(self) -> httpx.Response:
        return httpx.Response(self.status, headers=self.headers, stream=Chunks([self.content]))


def reply(status: int = 200, content: bytes = b"", headers: dict[str, str] | None = None) -> Reply:
    return Reply(status, content, headers or {})


def json_response(
    payload: object, status: int = 200, headers: dict[str, str] | None = None
) -> Reply:
    return reply(status, json.dumps(payload).encode(), headers)


def data(**fields: object) -> Reply:
    return json_response({"data": fields})


class Script:
    """A handler that answers with the next outcome (the last one repeats) and records requests."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Reply):
            return outcome.build()  # a fresh response each time: the last answer repeats
        return outcome(request)

    @property
    def count(self) -> int:
        return len(self.requests)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]
