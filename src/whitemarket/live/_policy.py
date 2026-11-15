"""Pure rules of a live session: backoff, close codes, connect info (SDK_SPEC 3.11, 1.4)."""

import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

BACKOFF_BASE: Final = 0.5
BACKOFF_CAP: Final = 20.0
# A connection that stayed up this long ends the streak: counters reset.
STABLE_AFTER: Final = 60.0
# Reconnects with a code outside the Centrifugo ranges: the next one is terminal.
MAX_OTHER_CLOSES: Final = 5
# A token with this many seconds or fewer left is refreshed.
REFRESH_BELOW: Final = 600.0
MAX_RETRY_AFTER: Final = 300.0
DEFAULT_PING_SECONDS: Final = 25
MAX_PING_SECONDS: Final = 300
# A connect reply `ttl` above this (a year; the server sends about 86400, WHITEMARKET_API.md 11)
# is taken as this: any such token outlives the connection.
MAX_TTL_SECONDS: Final = 365 * 24 * 3600
IDLE_GRACE_SECONDS: Final = 10
EPSILON: Final = 1e-6
SYSTEM_RANDOM: Final = random.SystemRandom().random

AUTH_EXPIRED_REPLY: Final = 109
ALREADY_SUBSCRIBED_REPLY: Final = 105
TOKEN_INVALID_CLOSE: Final = 3500
TOKEN_EXPIRED_CLOSE: Final = 3005
RESUBSCRIBE_FROM: Final = 2500

PRODUCTS_CHANNEL: Final = "market_products_updates"
PERSONAL_PREFIX: Final = "#"


def is_personal(channel: str) -> bool:
    """A personal channel (`#<personId>`) is subscribed by the server on connect."""
    return channel.startswith(PERSONAL_PREFIX)


def backoff_delay(attempt: int, random_value: float) -> float:
    """Full jitter: `random * min(20, 0.5 * 2 ** (attempt - 1))`; `attempt` is 1-based."""
    exponent = min(max(attempt, 1) - 1, 30)
    return float(random_value * min(BACKOFF_CAP, BACKOFF_BASE * 2**exponent))


class CloseKind(Enum):
    TOKEN_INVALID = auto()  # 3500: refresh once and reconnect, a second in a row is terminal
    RECONNECT = auto()  # 3000-3499, 4000-4499 (3005 inside it also refreshes once per streak)
    TERMINAL = auto()  # 3500-3999, 4500-4999 apart from 3500 itself
    OTHER = auto()  # outside every Centrifugo range: reconnects, at most 5 in a row


_RECONNECT_CODES: Final = (range(3000, 3500), range(4000, 4500))
_TERMINAL_CODES: Final = (range(3500, 4000), range(4500, 5000))


def classify_close(code: int) -> CloseKind:
    if code == TOKEN_INVALID_CLOSE:
        return CloseKind.TOKEN_INVALID
    if any(code in codes for codes in _RECONNECT_CODES):
        return CloseKind.RECONNECT
    if any(code in codes for codes in _TERMINAL_CODES):
        return CloseKind.TERMINAL
    return CloseKind.OTHER


@dataclass(frozen=True, slots=True)
class ConnectInfo:
    """What the session needs from a connection that is open.

    `ping` is the server ping interval in seconds, or `None` when no idle deadline applies.
    `ttl` is the seconds the token has left, or `None` when it does not expire.
    """

    ping: int | None
    pong: bool
    ttl: float | None

    @classmethod
    def from_reply(
        cls, ping: int | None, pong: bool, ttl: int | None, expires: bool
    ) -> "ConnectInfo":
        seconds = (
            min(ping, MAX_PING_SECONDS) if ping is not None and ping > 0 else DEFAULT_PING_SECONDS
        )
        # Clamped to 0..MAX_TTL_SECONDS before `float()`: a server int may not fit a float, and
        # any `ttl` of 0 or less already means "refresh now" to the engine.
        left = float(max(0, min(ttl, MAX_TTL_SECONDS))) if expires and ttl is not None else None
        return cls(ping=seconds, pong=pong, ttl=left)

    @property
    def idle_seconds(self) -> float | None:
        return None if self.ping is None else float(self.ping + IDLE_GRACE_SECONDS)


def check_seconds(name: str, value: float | None) -> None:
    """Refuse a negative or NaN duration; `None` means no limit."""
    if value is not None and not value >= 0:  # also rejects NaN
        raise ValueError(f"{name} must be a number of seconds, 0 or more")
