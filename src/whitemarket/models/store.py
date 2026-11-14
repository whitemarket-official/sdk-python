"""Model of the partner's own store (SDK_SPEC 3.9)."""

from dataclasses import dataclass
from datetime import datetime

from whitemarket.models.account_enums import (
    AchievementCondition,
    AchievementKind,
    AchievementName,
    AchievementStatus,
    StoreAvatar,
    StoreBanner,
)
from whitemarket.models.enums import DeliveryPromise


@dataclass(frozen=True, slots=True, kw_only=True)
class AchievementParam:
    """One parameter of an achievement: a condition `name` and its `value`, a `bool` for a boolean
    parameter and a `str` for a string parameter."""

    name: AchievementCondition
    value: bool | str


@dataclass(frozen=True, slots=True, kw_only=True)
class Achievement:
    """An achievement of a store. `params` holds the parameters this SDK knows (a parameter of an
    unknown kind is skipped)."""

    name: AchievementName
    points: int
    status: AchievementStatus
    kind: AchievementKind
    unlocked_at: datetime | None
    params: tuple[AchievementParam, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Store:
    """The partner's own store (`store.get()` and the result of `store.edit()`).

    `custom_avatar_url` is the URL of the uploaded avatar, as sent. `achievements` is empty when
    the server sends none.
    """

    id: str | None
    slug: str | None
    store_name: str
    avatar: StoreAvatar | None
    banner: StoreBanner | None
    custom_avatar_url: str | None
    steam_avatar: str | None
    delivery_promise: DeliveryPromise | None
    is_top_seller: bool
    is_kyc_verified: bool
    is_achievements_public: bool
    is_favorites_public: bool
    is_items_on_sale_public: bool
    is_store_name_public: bool
    is_trade_history_public: bool
    level: int | None
    points: int | None
    left_points: int | None
    years: int | None
    registered_at: datetime
    achievements: tuple[Achievement, ...]
