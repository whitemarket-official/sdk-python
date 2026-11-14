"""Hand-written async/sync primitive pairs (not generated).

Code under `_async/` uses the `Async...` and `async_...` names; tools/unasync.py rewrites them to
the plain names when it derives `_sync/`. Code under `_async/` must not import `asyncio` itself
(unasync refuses it): it goes through here.
"""

import asyncio
import contextlib
import threading
import time
from collections.abc import Awaitable, Callable
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


async def async_acquire_blocking(
    acquire: Callable[_P, _R], release: Callable[[_R], object], *args: _P.args, **kwargs: _P.kwargs
) -> _R:
    """Like `async_run_blocking`, for a call that returns something that must be given back.

    A worker thread cannot be interrupted: when the caller is cancelled while it runs, the call
    still finishes and its result would be lost. In that case `release(result)` is run on the
    default executor once it does, so the result (an open file, say) never leaks.
    """
    loop = asyncio.get_running_loop()
    work = asyncio.ensure_future(asyncio.to_thread(acquire, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:

        def give_back(done: "asyncio.Future[_R]") -> None:
            if not done.cancelled() and done.exception() is None:
                loop.run_in_executor(None, release, done.result())

        work.add_done_callback(give_back)
        raise


def acquire_blocking(
    acquire: Callable[_P, _R], release: Callable[[_R], object], *args: _P.args, **kwargs: _P.kwargs
) -> _R:
    """The sync twin of `async_acquire_blocking`: a sync call cannot be cancelled half way."""
    del release
    return acquire(*args, **kwargs)


_PENDING_CLOSES: set["asyncio.Task[object]"] = set()  # strong references until each close is done


def async_close_soon(close: Callable[[], Awaitable[object]]) -> None:
    """Run `close()` on the running event loop without waiting for it; a no-op without one.

    For a finalizer (`__del__`), which cannot await. Never raises.
    """
    try:
        task = asyncio.get_running_loop().create_task(_swallow(close))
    except RuntimeError:
        return  # no running loop: nothing can close an async connection from here
    _PENDING_CLOSES.add(task)
    task.add_done_callback(_PENDING_CLOSES.discard)


async def _swallow(close: Callable[[], Awaitable[object]]) -> None:
    with contextlib.suppress(Exception):
        await close()


def close_soon(close: Callable[[], object]) -> None:
    """The sync twin of `async_close_soon`: closes at once. Never raises."""
    with contextlib.suppress(Exception):
        close()
