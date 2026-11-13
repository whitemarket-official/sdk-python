"""The hand-written async/sync primitive pairs the unasync rules map onto each other."""

import asyncio
import time

import pytest

from whitemarket import _concurrency as c


def test_the_sync_pair_blocks_the_thread_for_the_time() -> None:
    start = time.monotonic()

    c.sleep(0.02)

    assert time.monotonic() - start >= 0.015


async def test_the_async_pair_yields_to_the_loop_while_it_sleeps() -> None:
    sleeping = asyncio.create_task(c.async_sleep(0.05))
    ticks = 0

    while not sleeping.done():
        ticks += 1
        await asyncio.sleep(0)

    # A blocking sleep would run the whole 50 ms inside the first yield: one tick.
    assert ticks > 3


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
def test_a_zero_sleep_returns_at_once(seconds: float) -> None:
    start = time.monotonic()

    c.sleep(seconds)

    assert time.monotonic() - start < 0.05


@pytest.mark.parametrize("seconds", [0, 0.0])
async def test_a_zero_async_sleep_returns_at_once(seconds: float) -> None:
    start = time.monotonic()

    await c.async_sleep(seconds)

    assert time.monotonic() - start < 0.05
