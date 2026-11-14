"""`StoreSettings`: what `store.edit()` changes (SDK_SPEC 3.9)."""

from dataclasses import dataclass

from whitemarket._generated.enums import AvatarType, BannerType
from whitemarket._generated.input_types import PersonStoreInput
from whitemarket._mappers.wire import present, wire_enum
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

    def to_input(self) -> PersonStoreInput:
        """The generated input; used by the high-level API, not part of the public API.

        Raises `ValueError` for an avatar or banner the API schema does not accept.
        """
        return PersonStoreInput(
            **present(
                avatar=wire_enum(AvatarType, self.avatar),
                banner=wire_enum(BannerType, self.banner),
                encoded_custom_avatar=self.custom_avatar,
                is_achievements_public=self.is_achievements_public,
                is_favorites_public=self.is_favorites_public,
                is_items_on_sale_public=self.is_items_on_sale_public,
                is_store_name_public=self.is_store_name_public,
                is_trade_history_public=self.is_trade_history_public,
                store_name=self.store_name,
            )
        )
