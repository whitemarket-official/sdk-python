"""What the seller decides for new listings, and the limits of the selling API (SDK_SPEC 3.5)."""

from dataclasses import dataclass
from typing import Final

from whitemarket.models.enums import DeliveryPromise, DeliveryType
from whitemarket.selling._checks import require_whole_seconds

MIN_LIFETIME: Final = 60  # seconds; SDK_SPEC 3.5, WHITEMARKET_API.md 4
MAX_LIFETIME: Final = 31_536_000  # seconds, 365 days; SDK_SPEC 3.5, WHITEMARKET_API.md 4
MIN_LIFETIME_FOR_ALL: Final = 600  # seconds; `market_lifetime_all`, SDK_SPEC 3.5
DEFAULT_BATCH_SIZE: Final = 100  # items per `*_multiple` request; SDK_SPEC 3.5 rule 5 (unconfirmed)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListingOptions:
    """How new listings are delivered, how fast the seller promises to deliver and how long a
    listing stays on the market (applies to every item of a `list_many` call).

    `delivery_type` is `SEMI` (default) or `MANUAL`; `AUTO` is reserved by the server and refused
    here. `delivery_promise` is the server's default when None. `lifetime` is in seconds,
    `MIN_LIFETIME` to `MAX_LIFETIME`, and the server's default (the maximum) when None.

    Raises `ValueError` for `AUTO` delivery or a lifetime outside the range, `TypeError` for a
    lifetime that is not an `int`.
    """

    delivery_type: DeliveryType = DeliveryType.SEMI
    delivery_promise: DeliveryPromise | None = None
    lifetime: int | None = None

    def __post_init__(self) -> None:
        if self.delivery_type == DeliveryType.AUTO:
            raise ValueError(
                "AUTO delivery is reserved by the server and rejected; use SEMI or MANUAL."
            )
        if self.lifetime is None:
            return
        require_whole_seconds(self.lifetime, "lifetime")
        if not MIN_LIFETIME <= self.lifetime <= MAX_LIFETIME:
            raise ValueError(
                f"The lifetime must be {MIN_LIFETIME}..{MAX_LIFETIME} seconds, got {self.lifetime}."
            )
