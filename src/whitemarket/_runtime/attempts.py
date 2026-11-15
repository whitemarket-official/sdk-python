"""The attempt count one GraphQL call shares across the 401 replay (SDK_SPEC 1.4)."""


class AttemptBudget:
    """The attempts one GraphQL call has sent, shared by its first send and the replay after a 401.

    The replay continues the count, so a query sends at most `max_attempts` requests in total
    (plus the token exchange); a 401 on the last attempt is still replayed once, and that replay
    is not retried. One instance per call, never shared between calls.
    """

    __slots__ = ("_sent",)

    def __init__(self) -> None:
        self._sent = 0

    def next_attempt(self) -> int:
        """Count one more send of the call and return its 1-based number."""
        self._sent += 1
        return self._sent
