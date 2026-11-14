"""What the HTTP transports take from the outside world: the clock, the wait and the jitter source.

Hand-written async; the sync twin is generated (tools/unasync.py). Shared by the GraphQL and the
export transport.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from whitemarket._concurrency import async_sleep


class AsyncSleeper(Protocol):
    async def __call__(self, seconds: float) -> None: ...


_JITTER = secrets.SystemRandom().random


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AsyncTransportSeams:
    """What the transport takes from the outside world: the clock, the wait and the jitter source.

    Tests inject fixed ones; there is no public use for them.
    """

    clock: Callable[[], datetime] = _utc_now
    sleeper: AsyncSleeper = async_sleep
    random: Callable[[], float] = _JITTER
