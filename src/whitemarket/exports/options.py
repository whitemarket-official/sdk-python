"""Settings of the export client (SDK_SPEC 1.3, 3.10 rule 1, 8)."""

from dataclasses import dataclass, field
from typing import Final

from whitemarket._runtime.endpoints import (
    DEFAULT_EXPORT_BASE_URL,
    require_origin,
    require_user_agent_suffix,
)
from whitemarket.retry import RetryPolicy

DEFAULT_MAX_BODY_BYTES: Final = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportOptions:
    """Seconds and bytes.

    `connect_timeout` bounds opening a connection; `idle_timeout` is the longest silence on the
    connection (there is no total timeout: a large download is fine while bytes keep arriving).
    Both apply to the HTTP client the SDK creates, not to an injected one.

    `max_body_bytes` bounds the DECOMPRESSED size of the calls that read a whole file (`meta`,
    `prices`, `stream_prices`); `download` and `stream_products` have no bound. `retry` governs an
    export GET: a network error, 429 and every 5xx are retried (a 429 or 503 with `Retry-After` is
    not).

    `base_url` is an `https://host[:port]` origin without path, query or credentials.
    """

    base_url: str = DEFAULT_EXPORT_BASE_URL
    connect_timeout: float = 10.0
    idle_timeout: float = 60.0
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    user_agent_suffix: str | None = None

    def __post_init__(self) -> None:
        require_origin("base_url", self.base_url)
        if not (self.connect_timeout > 0 and self.idle_timeout > 0):
            raise ValueError("timeouts must be positive")
        if self.max_body_bytes < 1:
            raise ValueError("max_body_bytes must be at least 1")
        require_user_agent_suffix(self.user_agent_suffix)
