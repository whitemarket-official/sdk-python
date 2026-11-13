"""Options of a live session (SDK_SPEC 3.11)."""

from dataclasses import dataclass
from enum import StrEnum

MIN_MESSAGE_BYTES = 1024
MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class LiveTransport(StrEnum):
    """How the live connection is made. `WS` is the default; `SSE` is unidirectional."""

    WS = "ws"
    SSE = "sse"


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveOptions:
    """Tuning of a live session. Durations are seconds.

    `connect_timeout` bounds one connect attempt up to the connect reply. `max_message_bytes`
    bounds one SSE event. `max_reconnect_attempts` (`None`: reconnect forever) caps the number of
    consecutive backoff reconnects; the counter resets after a connection stayed up 60 s.
    """

    connect_timeout: float = 10.0
    max_message_bytes: int = 1_048_576
    max_reconnect_attempts: int | None = None

    def __post_init__(self) -> None:
        if not self.connect_timeout > 0:
            raise ValueError("connect_timeout must be positive")
        if not MIN_MESSAGE_BYTES <= self.max_message_bytes <= MAX_MESSAGE_BYTES:
            raise ValueError(
                f"max_message_bytes must be between {MIN_MESSAGE_BYTES} and {MAX_MESSAGE_BYTES}"
            )
        if self.max_reconnect_attempts is not None and self.max_reconnect_attempts < 1:
            raise ValueError("max_reconnect_attempts must be at least 1 or None for unlimited")
