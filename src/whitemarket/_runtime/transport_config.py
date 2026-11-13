"""Settings of one transport: plain values, no IO."""

import platform
from dataclasses import dataclass, field

from whitemarket._version import __version__
from whitemarket.config import DEFAULT_MAX_RESPONSE_BYTES, Timeouts
from whitemarket.retry import RetryPolicy


def build_user_agent(suffix: str | None = None) -> str:
    """`whitemarket-sdk-python/<version> (CPython/<x.y.z>)`, then the optional suffix."""
    agent = (
        f"whitemarket-sdk-python/{__version__} "
        f"({platform.python_implementation()}/{platform.python_version()})"
    )
    return f"{agent} {suffix}" if suffix else agent


@dataclass(frozen=True, slots=True)
class TransportConfig:
    graphql_url: str
    user_agent: str = field(default_factory=build_user_agent)
    timeouts: Timeouts = field(default_factory=Timeouts)
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be at least 1")
