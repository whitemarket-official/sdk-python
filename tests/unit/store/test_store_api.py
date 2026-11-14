"""`client.store` through the HTTP boundary: request shape, mapping, achievements (SDK_SPEC 3.9).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from support import account_payloads as ap
from support.clients import Rig
from support.flavors import Flavor
from support.http import data, json_response, reply
from whitemarket import RetryPolicy
from whitemarket.errors import GraphQLError, ServerError
from whitemarket.models import DeliveryPromise
from whitemarket.models.account_enums import (
    AchievementCondition,
    AchievementKind,
    AchievementName,
    AchievementStatus,
    StoreAvatar,
    StoreBanner,
)
from whitemarket.models.store import AchievementParam
from whitemarket.store import StoreSettings


def boolean_param(name: str = "CONDITION_BUY_KNIFE", value: bool = True) -> dict[str, Any]:
    return {"__typename": "AchievementBooleanParam", "name": name, "booleanValue": value}


def string_param(name: str = "CONDITION_TRADE_AMOUNT", value: str = "100") -> dict[str, Any]:
    return {"__typename": "AchievementStringParam", "name": name, "stringValue": value}


def test_get_sends_store_my_and_maps_the_store(flavor: Flavor) -> None:
    node = ap.store(
        slug="synthetic-shop",
        avatar="AVATAR_12",
        banner="BANNER_3",
        customAvatar="https://example.invalid/avatar.png",
        steamAvatar="https://example.invalid/steam.png",
        deliveryPromise="HOURS24",
        isTopSeller=True,
        isKycVerified=True,
        isAchievementsPublic=True,
        isFavoritesPublic=False,
        isItemsOnSalePublic=True,
        isStoreNamePublic=False,
        isTradeHistoryPublic=True,
        level=4,
        points=120,
        leftPoints=30,
        years=2,
        registeredAt="2024-01-02T03:04:05+00:00",
    )
    with Rig(flavor, data(store_my=node)) as rig:
        store = rig.call(rig.client.store.get())

        (body,) = rig.bodies()
    assert (body["operationName"], body.get("variables", {})) == ("StoreMy", {})
    assert (store.id, store.slug, store.store_name) == (
        "store-1",
        "synthetic-shop",
        "Synthetic store",
    )
    assert store.avatar is StoreAvatar.AVATAR_12
    assert store.banner is StoreBanner.BANNER_3
    assert store.custom_avatar_url == "https://example.invalid/avatar.png"
    assert store.steam_avatar == "https://example.invalid/steam.png"
    assert store.delivery_promise is DeliveryPromise.HOURS24
    assert (store.is_top_seller, store.is_kyc_verified) == (True, True)
    assert (store.is_achievements_public, store.is_favorites_public) == (True, False)
    assert (store.is_items_on_sale_public, store.is_store_name_public) == (True, False)
    assert store.is_trade_history_public is True
    assert (store.level, store.points, store.left_points, store.years) == (4, 120, 30, 2)
    assert store.registered_at == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert store.achievements == ()


def test_a_store_with_nulls_maps_them_to_none(flavor: Flavor) -> None:
    node = ap.store(
        id=None, slug=None, avatar=None, banner=None, customAvatar=None, deliveryPromise=None
    )
    with Rig(flavor, data(store_my=node)) as rig:
        store = rig.call(rig.client.store.get())

    assert (store.id, store.slug, store.avatar, store.banner) == (None, None, None, None)
    assert (store.custom_avatar_url, store.delivery_promise) == (None, None)


def test_unknown_store_enum_values_are_kept(flavor: Flavor) -> None:
    node = ap.store(avatar="AVATAR_99", banner="BANNER_99")
    with Rig(flavor, data(store_my=node)) as rig:
        store = rig.call(rig.client.store.get())

    assert store.avatar is not None
    assert (store.avatar.value, store.avatar.is_unknown) == ("AVATAR_99", True)
    assert store.banner is not None
    assert store.banner.is_unknown


def test_get_is_retried_like_a_query(flavor: Flavor) -> None:
    with Rig(flavor, reply(503), data(store_my=ap.store()), retry=RetryPolicy(base_delay=0)) as rig:
        rig.call(rig.client.store.get())

        assert rig.script.count == 2


def test_get_requests_the_aliased_achievement_params(flavor: Flavor) -> None:
    with Rig(flavor, data(store_my=ap.store())) as rig:
        rig.call(rig.client.store.get())

        (body,) = rig.bodies()
    assert "booleanValue: value" in body["query"]
    assert "stringValue: value" in body["query"]


def test_achievements_map_both_param_kinds_and_every_field(flavor: Flavor) -> None:
    achievement = ap.achievement(
        name="PRO_TRADER",
        points=50,
        status="COMPLETED",
        type="CHECKLIST",
        unlockedAt="2026-09-01T00:00:00+00:00",
        params=[boolean_param(value=False), string_param(value="0.5")],
    )
    with Rig(flavor, data(store_my=ap.store(achievements=[achievement]))) as rig:
        store = rig.call(rig.client.store.get())

    (a,) = store.achievements
    assert a.name is AchievementName.PRO_TRADER
    assert a.points == 50
    assert a.status is AchievementStatus.COMPLETED
    assert a.kind is AchievementKind.CHECKLIST
    assert a.unlocked_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert a.params == (
        AchievementParam(name=AchievementCondition.CONDITION_BUY_KNIFE, value=False),
        AchievementParam(name=AchievementCondition.CONDITION_TRADE_AMOUNT, value="0.5"),
    )
    assert type(a.params[0].value) is bool
    assert type(a.params[1].value) is str


def test_an_unknown_param_member_and_a_null_entry_are_skipped(flavor: Flavor) -> None:
    params = [
        boolean_param(),
        {"__typename": "AchievementFloatParam"},
        None,
        string_param(value="kept"),
    ]
    achievement = ap.achievement(params=params)
    with Rig(flavor, data(store_my=ap.store(achievements=[achievement]))) as rig:
        (a,) = rig.call(rig.client.store.get()).achievements

    assert [p.value for p in a.params] == [True, "kept"]


def test_null_params_and_null_achievements_are_empty_lists(flavor: Flavor) -> None:
    node = ap.store(achievements=[ap.achievement(params=None)])
    empty = ap.store(achievements=None)
    with Rig(flavor, data(store_my=node), data(store_my=empty)) as rig:
        with_null_params = rig.call(rig.client.store.get())
        without_list = rig.call(rig.client.store.get())

    assert with_null_params.achievements[0].params == ()
    assert without_list.achievements == ()


def test_unknown_achievement_enum_values_are_kept(flavor: Flavor) -> None:
    achievement = ap.achievement(
        name="FUTURE",
        status="PAUSED",
        type="DAILY",
        params=[boolean_param(name="CONDITION_FUTURE")],
    )
    with Rig(flavor, data(store_my=ap.store(achievements=[achievement]))) as rig:
        (a,) = rig.call(rig.client.store.get()).achievements

    assert (a.name.is_unknown, a.status.is_unknown, a.kind.is_unknown) == (True, True, True)
    assert a.params[0].name.value == "CONDITION_FUTURE"


def test_edit_sends_the_encoded_settings_and_maps_the_result(flavor: Flavor) -> None:
    settings = StoreSettings(
        avatar=StoreAvatar.CUSTOM,
        banner=StoreBanner.BANNER_8,
        custom_avatar="aGVsbG8=",
        store_name="Synthetic Shop",
        is_achievements_public=False,
        is_trade_history_public=True,
    )
    node = ap.store(
        storeName="Synthetic Shop",
        achievements=[ap.achievement(params=[boolean_param()])],
    )
    with Rig(flavor, data(store_edit=node)) as rig:
        store = rig.call(rig.client.store.edit(settings))

        (body,) = rig.bodies()
    assert body["operationName"] == "StoreEdit"
    assert body["query"].lstrip().startswith("mutation StoreEdit")
    assert body["variables"] == {
        "storeInput": {
            "avatar": "CUSTOM",
            "banner": "BANNER_8",
            "encodedCustomAvatar": "aGVsbG8=",
            "isAchievementsPublic": False,
            "isTradeHistoryPublic": True,
            "storeName": "Synthetic Shop",
        }
    }
    assert store.store_name == "Synthetic Shop"
    assert store.achievements[0].params[0].value is True


def test_edit_with_nothing_given_sends_an_empty_input(flavor: Flavor) -> None:
    with Rig(flavor, data(store_edit=ap.store())) as rig:
        rig.call(rig.client.store.edit(StoreSettings()))

        assert rig.variables() == [{"storeInput": {}}]


def test_edit_refuses_an_avatar_the_schema_does_not_accept_before_sending(flavor: Flavor) -> None:
    with Rig(flavor, data(store_edit=ap.store())) as rig:
        with pytest.raises(ValueError, match="AVATAR_99"):
            rig.call(rig.client.store.edit(StoreSettings(avatar=StoreAvatar("AVATAR_99"))))

        assert rig.script.count == 0


def test_edit_is_sent_once_and_never_retried_on_503(flavor: Flavor) -> None:
    with Rig(flavor, reply(503), retry=RetryPolicy(max_attempts=3, base_delay=0)) as rig:
        with pytest.raises(ServerError):
            rig.call(rig.client.store.edit(StoreSettings(store_name="x")))

        assert rig.script.count == 1


def test_edit_graphql_error_propagates_with_its_category(flavor: Flavor) -> None:
    answer = json_response(
        {"data": None, "errors": [{"message": "x", "extensions": {"category": "store.name.taken"}}]}
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.store.edit(StoreSettings(store_name="x")))

    assert caught.value.errors[0].category == "store.name.taken"
