"""`StoreSettings`: what `store.edit()` changes (SDK_SPEC 3.9)."""

from dataclasses import dataclass

from whitemarket.models.account_enums import StoreAvatar, StoreBanner


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreSettings:
    """The settings `store.edit()` changes. Every field is optional; one left out (`None`) is not
    sent, so the server keeps its value. There is no client-side validation: the API documents no
    limits.

    `custom_avatar` is the avatar image, base64 encoded, sent as `encodedCustomAvatar`. The
    multipart upload of the API is not supported (an SDK that sends JSON only cannot send it).
    """

    avatar: StoreAvatar | None = None
    banner: StoreBanner | None = None
    custom_avatar: str | None = None
    store_name: str | None = None
    is_achievements_public: bool | None = None
    is_favorites_public: bool | None = None
    is_items_on_sale_public: bool | None = None
    is_store_name_public: bool | None = None
    is_trade_history_public: bool | None = None
