"""Hand-written async/sync primitive pairs (not generated).

Code under `_async/` uses the `Async...` and `async_...` names; tools/unasync.py rewrites them to
the plain names when it derives `_sync/`. Code under `_async/` must not import `asyncio` itself
(unasync refuses it): it goes through here.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import ParamSpec, Self, TypeVar

AsyncLock = asyncio.Lock
Lock = threading.Lock


async def async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def sleep(seconds: float) -> None:
    time.sleep(seconds)


class AsyncDeadline:
    """`async with AsyncDeadline(s):` ends the block after `s` seconds (`None`: never).

    The block is cancelled and the `with` raises `TimeoutError`.

    httpx timeouts are per phase (connect, write, read, pool), so a server that sends one byte
    every few seconds never trips them; this bounds the whole block (ADR 0002).
    """

    def __init__(self, seconds: float | None) -> None:
        self._scope = asyncio.timeout(seconds)

    async def __aenter__(self) -> Self:
        await self._scope.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        await self._scope.__aexit__(exc_type, exc, traceback)
        return None

    def check(self) -> None:
        """The async deadline cancels by itself at the next `await`: nothing to check."""


class Deadline:
    """The sync twin of `AsyncDeadline`: it cannot interrupt a blocking read, only be polled.

    `check()` raises `TimeoutError` once the time is over; call it between reads. One blocked read
    can still last its own per-phase timeout, so the block ends within `seconds` plus one read
    timeout (ADR 0002, docs/DEVIATIONS.md).
    """

    def __init__(self, seconds: float | None) -> None:
        self._end = None if seconds is None else time.monotonic() + seconds

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def check(self) -> None:
        if self._end is not None and time.monotonic() >= self._end:
            raise TimeoutError


_P = ParamSpec("_P")
_R = TypeVar("_R")


async def async_run_blocking(func: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
    """Run a blocking call (file IO) without stopping the event loop: in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


def run_blocking(func: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
    """The sync twin of `async_run_blocking`: the caller is already allowed to block."""
    return func(*args, **kwargs)
