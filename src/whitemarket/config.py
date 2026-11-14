"""Public client settings that are plain values (SDK_SPEC 2)."""

import math
from dataclasses import dataclass
from typing import Final, cast

from whitemarket.retry import RetryPolicy

__all__ = ["BuyReconciliation", "RetryPolicy", "Timeouts"]

DEFAULT_MAX_RESPONSE_BYTES: Final = 32 * 1024 * 1024
_MIN_DELAY: Final = 10.0  # SDK_SPEC 0 / 3.3: the allowed window of the buy reconciliation delay
_MAX_DELAY: Final = 20.0


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Seconds. `connect` bounds opening a connection; `request` bounds one whole attempt.

    In the async client `request` is a hard limit on the whole request, body included. The sync
    client enforces it between reads of the body and bounds every single read by it (httpx has no
    total timeout; docs/DEVIATIONS.md). Not applied to an injected `http_client`.
    """

    connect: float = 10.0
    request: float = 30.0

    def __post_init__(self) -> None:
        if not (self.connect > 0 and self.request > 0):
            raise ValueError("timeouts must be positive")


@dataclass(frozen=True, slots=True)
class BuyReconciliation:
    """How buying looks a purchase up after an ambiguous failure (SDK_SPEC 3.3). Seconds.

    `delay` before the first lookup is 10 to 20 s (default 15), `attempts` lookups are made
    `interval` seconds apart.
    """

    delay: float = 15.0
    attempts: int = 3
    interval: float = 5.0

    def __post_init__(self) -> None:
        # NaN and infinity fail every range check below on their own (a NaN comparison is False).
        if not _MIN_DELAY <= self.delay <= _MAX_DELAY:
            raise ValueError("delay must be between 10 and 20 seconds")
        # A `bool` is an `int` to Python and 2.5 attempts are none: a loop count is a whole number.
        attempts = cast("object", self.attempts)
        if not isinstance(attempts, int) or isinstance(attempts, bool):
            raise TypeError("attempts must be an int")
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if not (math.isfinite(self.interval) and self.interval >= 0):
            raise ValueError("interval must be a finite number of seconds, not negative")
