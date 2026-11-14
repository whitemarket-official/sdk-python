"""Mapper of the `Store` model (SDK_SPEC 3.9)."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from whitemarket._generated.fragments import PersonAchievementFields, PersonStoreFields
from whitemarket._mappers.common import convert_enum, optional_enum
from whitemarket.models.account_enums import (
    AchievementCondition,
    AchievementKind,
    AchievementName,
    AchievementStatus,
    StoreAvatar,
    StoreBanner,
)
from whitemarket.models.enums import DeliveryPromise
from whitemarket.models.store import Achievement, AchievementParam, Store


@runtime_checkable
class BooleanParamSource(Protocol):
    """`AchievementBooleanParam`, selected with `value` aliased to `booleanValue`."""

    @property
    def name(self) -> str: ...
    @property
    def boolean_value(self) -> bool: ...


@runtime_checkable
class StringParamSource(Protocol):
    """`AchievementStringParam`, selected with `value` aliased to `stringValue`."""

    @property
    def name(self) -> str: ...
    @property
    def string_value(self) -> str: ...


def map_store(
    store: PersonStoreFields, achievements: Sequence[PersonAchievementFields] | None
) -> Store:
    """The store of the `PersonStore` fragment and its `achievements` (null: none)."""
    return Store(
        id=store.id,
        slug=store.slug,
        store_name=store.store_name,
        avatar=optional_enum(StoreAvatar, store.avatar),
        banner=optional_enum(StoreBanner, store.banner),
        custom_avatar_url=store.custom_avatar,
        steam_avatar=store.steam_avatar,
        delivery_promise=optional_enum(DeliveryPromise, store.delivery_promise),
        is_top_seller=store.is_top_seller,
        is_kyc_verified=store.is_kyc_verified,
        is_achievements_public=store.is_achievements_public,
        is_favorites_public=store.is_favorites_public,
        is_items_on_sale_public=store.is_items_on_sale_public,
        is_store_name_public=store.is_store_name_public,
        is_trade_history_public=store.is_trade_history_public,
        level=store.level,
        points=store.points,
        left_points=store.left_points,
        years=store.years,
        registered_at=store.registered_at,
        achievements=tuple(map_achievement(a) for a in achievements or ()),
    )


def map_achievement(source: PersonAchievementFields) -> Achievement:
    params: Sequence[object | None] = getattr(source, "params", None) or ()
    return Achievement(
        name=convert_enum(AchievementName, source.name),
        points=source.points,
        status=convert_enum(AchievementStatus, source.status),
        kind=convert_enum(AchievementKind, source.type_),
        unlocked_at=source.unlocked_at,
        params=tuple(p for p in (_param(param) for param in params) if p is not None),
    )


def _param(source: object) -> AchievementParam | None:
    """None for a null entry and for a member this SDK does not know (SDK_SPEC 3.9 store rule 4)."""
    if isinstance(source, BooleanParamSource):
        return AchievementParam(
            name=convert_enum(AchievementCondition, source.name), value=source.boolean_value
        )
    if isinstance(source, StringParamSource):
        return AchievementParam(
            name=convert_enum(AchievementCondition, source.name), value=source.string_value
        )
    return None
