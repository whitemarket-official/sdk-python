"""Hand-written async/sync primitive pairs (not generated).

Code under `_async/` uses the `Async...` and `async_...` names; tools/unasync.py rewrites them to
the plain names when it derives `_sync/`. Code under `_async/` must not import `asyncio` itself
(unasync refuses it): it goes through here.
"""

import asyncio
import threading
import time

AsyncLock = asyncio.Lock
Lock = threading.Lock


async def async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def sleep(seconds: float) -> None:
    time.sleep(seconds)
