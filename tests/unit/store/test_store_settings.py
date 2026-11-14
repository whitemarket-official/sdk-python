"""`StoreSettings`: the high-level builder over `PersonStoreInput` (SDK_SPEC 3.9)."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from whitemarket._runtime.json_codec import to_plain
from whitemarket.models.account_enums import StoreAvatar, StoreBanner
from whitemarket.store import StoreSettings


def wire(settings: StoreSettings) -> Any:
    return to_plain(settings.to_input())


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        pytest.param(StoreSettings(), {}, id="empty settings -> nothing"),
        pytest.param(
            StoreSettings(avatar=StoreAvatar.AVATAR_12), {"avatar": "AVATAR_12"}, id="avatar"
        ),
        pytest.param(
            StoreSettings(avatar=StoreAvatar.STEAM), {"avatar": "STEAM"}, id="avatar steam"
        ),
        pytest.param(
            StoreSettings(banner=StoreBanner.BANNER_8), {"banner": "BANNER_8"}, id="banner"
        ),
        pytest.param(
            StoreSettings(custom_avatar="aGVsbG8="),
            {"encodedCustomAvatar": "aGVsbG8="},
            id="custom_avatar -> encodedCustomAvatar",
        ),
        pytest.param(StoreSettings(store_name="Shop"), {"storeName": "Shop"}, id="store_name"),
        pytest.param(
            StoreSettings(store_name=""), {"storeName": ""}, id="empty store_name is sent"
        ),
        pytest.param(
            StoreSettings(is_achievements_public=True),
            {"isAchievementsPublic": True},
            id="achievements public",
        ),
        pytest.param(
            StoreSettings(is_achievements_public=False),
            {"isAchievementsPublic": False},
            id="achievements public false is sent",
        ),
        pytest.param(
            StoreSettings(is_favorites_public=False), {"isFavoritesPublic": False}, id="favorites"
        ),
        pytest.param(
            StoreSettings(is_items_on_sale_public=True),
            {"isItemsOnSalePublic": True},
            id="items on sale",
        ),
        pytest.param(
            StoreSettings(is_store_name_public=False), {"isStoreNamePublic": False}, id="store name"
        ),
        pytest.param(
            StoreSettings(is_trade_history_public=True),
            {"isTradeHistoryPublic": True},
            id="trade history",
        ),
    ],
)
def test_each_field_is_encoded_to_its_wire_name(settings: StoreSettings, expected: Any) -> None:
    assert wire(settings) == expected


def test_every_field_together() -> None:
    settings = StoreSettings(
        avatar=StoreAvatar.AVATAR_1,
        banner=StoreBanner.BANNER_1,
        custom_avatar="x",
        store_name="s",
        is_achievements_public=True,
        is_favorites_public=False,
        is_items_on_sale_public=True,
        is_store_name_public=False,
        is_trade_history_public=True,
    )

    assert wire(settings) == {
        "avatar": "AVATAR_1",
        "banner": "BANNER_1",
        "encodedCustomAvatar": "x",
        "isAchievementsPublic": True,
        "isFavoritesPublic": False,
        "isItemsOnSalePublic": True,
        "isStoreNamePublic": False,
        "isTradeHistoryPublic": True,
        "storeName": "s",
    }


def test_the_settings_are_immutable() -> None:
    settings = StoreSettings()

    with pytest.raises(FrozenInstanceError):
        settings.store_name = "x"


def test_a_banner_the_schema_does_not_accept_is_refused() -> None:
    with pytest.raises(ValueError, match="BANNER_99"):
        StoreSettings(banner=StoreBanner("BANNER_99")).to_input()
