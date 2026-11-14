"""Retry policy of the transport: pure rules, no IO (SDK_SPEC 1.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from whitemarket._runtime.operation import OperationType
from whitemarket._runtime.retry_after import RETRY_AFTER_STATUSES

_RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504})


_TOO_MANY_REQUESTS: Final = 429
_SERVER_ERRORS: Final = range(500, 600)


def _is_read_retryable(status: int) -> bool:
    return status == _TOO_MANY_REQUESTS or status in _SERVER_ERRORS


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """When and how long to wait before repeating a GraphQL query. Durations are in seconds.

    A mutation is never retried, whatever the configuration (CLAUDE.md rule 2); this class has no
    switch for it. A query is retried on a network error before a response and on 429, 500, 502,
    503 and 504, at most `max_attempts` attempts in total. The delay is exponential with full
    jitter: `random() * min(max_delay, base_delay * factor ** (attempt - 1))`.

    A 429 or 503 that carries `Retry-After` is not retried: the caller gets the error with
    `retry_after` at once and decides when to try again, so the SDK never blocks for a time the
    server chose (owner decision 2026-10-31). On every other status the header is ignored.
    An unparsable value counts as no header (the query is retried), as in the PHP SDK.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    factor: float = 2.0
    max_delay: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0 or self.factor < 1:
            raise ValueError("delays must not be negative and factor must be at least 1")

    @classmethod
    def none(cls) -> "RetryPolicy":
        """One attempt, no retry."""
        return cls(max_attempts=1)

    def should_retry(
        self,
        operation_type: OperationType,
        attempt: int,
        status: int | None,
        retry_after: float | None = None,
    ) -> bool:
        """Whether attempt number `attempt` (1-based) may be repeated.

        `status` is `None` when no response came (a network error before the answer).
        """
        if operation_type != "query":
            return False
        return self._may_repeat(attempt, status, retry_after, _RETRYABLE_STATUSES.__contains__)

    def should_retry_export(
        self, attempt: int, status: int | None, retry_after: float | None = None
    ) -> bool:
        """The same for an export GET: 429 and every 5xx (500-599) are retried.

        `status` is `None` when no response came (a network error before the answer).
        """
        return self._may_repeat(attempt, status, retry_after, _is_read_retryable)

    def _may_repeat(
        self,
        attempt: int,
        status: int | None,
        retry_after: float | None,
        retryable: Callable[[int], bool],
    ) -> bool:
        if attempt >= self.max_attempts:
            return False
        if status is None:
            return True
        if retry_after is not None and status in RETRY_AFTER_STATUSES:
            return False
        return retryable(status)

    def delay(self, attempt: int, random: float) -> float:
        """Seconds to wait after attempt number `attempt` (1-based) failed.

        `random` is a uniform sample of [0, 1): the full-jitter fraction of the ceiling.
        """
        if self.base_delay == 0:
            return 0.0
        try:
            ceiling = min(self.max_delay, self.base_delay * self.factor ** max(0, attempt - 1))
        except OverflowError:
            ceiling = self.max_delay
        return random * ceiling
