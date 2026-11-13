"""The hand-written async/sync primitive pairs the unasync rules map onto each other."""

import asyncio
import threading
import time

import pytest

from whitemarket import _concurrency as c


def test_the_sync_pair_blocks_the_thread_for_the_time() -> None:
    start = time.monotonic()

    c.sleep(0.02)

    assert time.monotonic() - start >= 0.015


async def test_the_async_pair_yields_to_the_loop_while_it_sleeps() -> None:
    ticks: list[int] = []

    async def ticker() -> None:
        while len(ticks) < 3:
            ticks.append(1)
            await asyncio.sleep(0)

    await asyncio.gather(c.async_sleep(0.02), ticker())

    assert len(ticks) >= 3


def test_the_lock_pair_are_the_stdlib_locks() -> None:
    assert c.AsyncLock is asyncio.Lock
    assert isinstance(c.Lock(), type(threading.Lock()))


async def test_the_async_lock_serialises() -> None:
    lock = c.AsyncLock()
    order: list[str] = []

    async def worker(name: str) -> None:
        async with lock:
            order.append(f"{name}-in")
            await asyncio.sleep(0.005)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a"), worker("b"))

    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


@pytest.mark.parametrize("seconds", [0, 0.0])
def test_a_zero_sleep_returns(seconds: float) -> None:
    c.sleep(seconds)
