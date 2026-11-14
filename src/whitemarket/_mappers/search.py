"""High-level filters and settings to generated search inputs (CLAUDE.md rule 12: API names only at
the boundary). The filter classes are plain data; this module is the one place that knows the schema
names of their inputs. A value the wire enum does not know cannot be sent: `ValueError` here.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

from whitemarket._generated.enums import (
    AvatarType,
    BannerType,
    CatalogColor,
    CSGOCategory,
    CSGOExterior,
    CSGOPhase,
    CSGORarity,
    CSGOStickerFilm,
    CSGOSubcategory,
    MarketDealActionType,
    MarketDealHistorySortField,
    MarketDealHistoryStatus,
    MarketOfferType,
    MarketProductSortField,
    SortType,
    SteamApp,
    WalletTransactionFeeType,
    WalletTransactionReason,
    WalletTransactionSortField,
    WalletTransactionStatus,
)
from whitemarket._generated.enums import DeliveryPromise as WireDeliveryPromise
from whitemarket._generated.enums import DeliveryType as WireDeliveryType
from whitemarket._generated.enums import LogicOperand as WireLogicOperand
from whitemarket._generated.input_types import (
    MarkerDealHistorySearchInput,
    MarketDealHistorySortInput,
    MarketProductSearchInput,
    MarketProductSortInput,
    PersonInventorySearchInput,
    PersonStoreInput,
    WalletTransactionSearchInput,
    WalletTransactionSortInput,
)
from whitemarket._mappers.wire import (
    present,
    wire_date_range,
    wire_decimal,
    wire_enum,
    wire_enums,
    wire_list,
    wire_money_range,
)
from whitemarket._runtime.unset import UNSET, UnsetType
from whitemarket.models.enums import Currency

if TYPE_CHECKING:
    from whitemarket.deals.history import DealHistoryFilter, DealHistorySort
    from whitemarket.inventory.filter import InventoryFilter
    from whitemarket.market.filter import ProductFilter, ProductSort
    from whitemarket.store.settings import StoreSettings
    from whitemarket.wallet.filter import WalletTransactionFilter, WalletTransactionSort

_F = TypeVar("_F")
_R = TypeVar("_R")


def search_argument(
    value: object, raw_type: type[_R], encode: Callable[[_F], _R]
) -> _R | UnsetType:
    """The `search` variable of a list operation: a filter is encoded, a raw generated input of
    `raw_type` is sent as is, and nothing at all is sent for None.

    `value` is typed `object` because a type checker cannot solve `_F | _R` from a union argument;
    the callers' own signatures name the two accepted types."""
    if value is None:
        return UNSET
    if isinstance(value, raw_type):
        return value
    return encode(cast("_F", value))


def product_sort_input(sort: "ProductSort") -> MarketProductSortInput:
    return MarketProductSortInput(
        field=wire_enum(MarketProductSortField, sort.field),
        type_=wire_enum(SortType, sort.direction),
    )


def product_search_input(product_filter: "ProductFilter") -> MarketProductSearchInput:
    """The generated search input of a `ProductFilter`; unset conditions are left out."""
    return MarketProductSearchInput(
        **present(
            app_id=wire_enum(SteamApp, product_filter.app),
            color_enum=wire_enums(CatalogColor, product_filter.colors),
            created_at=wire_date_range(product_filter.created_from, product_filter.created_to),
            csgo_charm=product_filter.has_charm,
            csgo_collection=product_filter.collection,
            csgo_exterior_enum=wire_enums(CSGOExterior, product_filter.exteriors),
            csgo_fade_from=product_filter.fade_from,
            csgo_fade_rank_from=product_filter.fade_rank_from,
            csgo_fade_rank_to=product_filter.fade_rank_to,
            csgo_fade_to=product_filter.fade_to,
            csgo_float_from=wire_decimal(product_filter.float_from),
            csgo_float_to=wire_decimal(product_filter.float_to),
            csgo_item_categories_exclude=wire_enums(
                CSGOCategory, product_filter.exclude_categories
            ),
            csgo_item_category_enum=wire_enum(CSGOCategory, product_filter.category),
            csgo_item_skin=product_filter.skin,
            csgo_item_subcategories_exclude=wire_enums(
                CSGOSubcategory, product_filter.exclude_subcategories
            ),
            csgo_item_subcategory_enum=wire_enum(CSGOSubcategory, product_filter.subcategory),
            csgo_pattern=product_filter.pattern,
            csgo_phase_enum=wire_enum(CSGOPhase, product_filter.phase),
            csgo_rarity_enum=wire_enums(CSGORarity, product_filter.rarities),
            csgo_souvenir=product_filter.souvenir,
            csgo_stat_trak=product_filter.stat_trak,
            csgo_sticker_film=wire_enum(CSGOStickerFilm, product_filter.sticker_film),
            csgo_sticker_names=wire_list(product_filter.sticker_names),
            csgo_sticker_names_by_slot=wire_list(product_filter.sticker_names_by_slot),
            csgo_sticker_names_operand=wire_enum(
                WireLogicOperand, product_filter.sticker_names_operand
            ),
            csgo_sticker_player=product_filter.sticker_player_id,
            csgo_sticker_team=product_filter.sticker_team_id,
            csgo_sticker_tournament=product_filter.sticker_tournament_id,
            csgo_stickers=product_filter.has_stickers,
            delivery_promise=wire_enum(WireDeliveryPromise, product_filter.delivery_promise),
            delivery_type=wire_enum(WireDeliveryType, product_filter.delivery_type),
            distinct_values=product_filter.distinct_values,
            ids=wire_list(product_filter.ids),
            is_popular=product_filter.popular,
            is_weapon_and_gear=product_filter.weapon_and_gear,
            name=product_filter.name,
            name_hash=product_filter.name_hash,
            name_strict=product_filter.name_strict,
            names=wire_list(product_filter.names),
            names_hash=wire_list(product_filter.name_hashes),
            offer_type=wire_enum(MarketOfferType, product_filter.offer_type),
            only_promo=product_filter.only_promo,
            price=wire_money_range(product_filter.price_from, product_filter.price_to),
            sort=None if product_filter.sort is None else product_sort_input(product_filter.sort),
            special=product_filter.special,
            store_slug=product_filter.store_slug,
            super_deal=product_filter.super_deal,
        )
    )


def deal_history_sort_input(value: "DealHistorySort") -> MarketDealHistorySortInput:
    """The generated sort input of a `DealHistorySort`."""
    return MarketDealHistorySortInput(
        field=wire_enum(MarketDealHistorySortField, value.field),
        type_=wire_enum(SortType, value.direction),
    )


def deal_history_search_input(value: "DealHistoryFilter") -> MarkerDealHistorySearchInput:
    """The generated search input of a `DealHistoryFilter`; unset conditions are left out."""
    return MarkerDealHistorySearchInput(
        **present(
            action=wire_enum(MarketDealActionType, value.action),
            asset_ids=wire_list(value.asset_ids),
            color_enum=wire_enums(CatalogColor, value.colors),
            created_at=wire_date_range(value.created_from, value.created_to),
            csgo_charm=value.has_charm,
            csgo_collection=value.collection,
            csgo_exterior_enum=wire_enums(CSGOExterior, value.exteriors),
            csgo_float_from=wire_decimal(value.float_from),
            csgo_float_to=wire_decimal(value.float_to),
            csgo_pattern=value.pattern,
            csgo_phase_enum=wire_enum(CSGOPhase, value.phase),
            csgo_rarity_enum=wire_enums(CSGORarity, value.rarities),
            csgo_souvenir=value.souvenir,
            csgo_stat_trak=value.stat_trak,
            csgo_sticker_film=wire_enum(CSGOStickerFilm, value.sticker_film),
            csgo_sticker_names=wire_list(value.sticker_names),
            csgo_sticker_names_by_slot=wire_list(value.sticker_names_by_slot),
            csgo_sticker_names_operand=wire_enum(WireLogicOperand, value.sticker_names_operand),
            csgo_sticker_player=value.sticker_player_id,
            csgo_sticker_team=value.sticker_team_id,
            csgo_sticker_tournament=value.sticker_tournament_id,
            csgo_stickers=value.has_stickers,
            name=value.name,
            name_hash=value.name_hash,
            name_strict=value.name_strict,
            only_for_orders=value.only_for_orders,
            price=wire_money_range(value.price_from, value.price_to),
            sort=None if value.sort is None else deal_history_sort_input(value.sort),
            status=wire_enum(MarketDealHistoryStatus, value.status),
        )
    )


def wallet_transaction_sort_input(value: "WalletTransactionSort") -> WalletTransactionSortInput:
    """The generated sort input of a `WalletTransactionSort`."""
    return WalletTransactionSortInput(
        field=wire_enum(WalletTransactionSortField, value.field),
        type_=wire_enum(SortType, value.direction),
    )


def wallet_transaction_search_input(
    value: "WalletTransactionFilter",
) -> WalletTransactionSearchInput:
    """The generated search input of a `WalletTransactionFilter`; unset conditions are left out."""
    return WalletTransactionSearchInput(
        **present(
            created_at=wire_date_range(value.created_from, value.created_to),
            currency=wire_enum(Currency, value.currency),
            fee_type=wire_enum(WalletTransactionFeeType, value.fee_type),
            initial_currency_deposit=wire_enums(Currency, value.initial_deposit_currencies),
            initial_currency_withdrawal=wire_enums(Currency, value.initial_withdrawal_currencies),
            is_buyer=value.buyer,
            is_seller=value.seller,
            reason=wire_enum(WalletTransactionReason, value.reason),
            reasons=wire_enums(WalletTransactionReason, value.reasons),
            sort=None if value.sort is None else wallet_transaction_sort_input(value.sort),
            status=wire_enum(WalletTransactionStatus, value.status),
            wallet_methods_deposit=wire_list(value.deposit_methods),
            wallet_methods_withdrawal=wire_list(value.withdrawal_methods),
        )
    )


def inventory_search_input(value: "InventoryFilter") -> PersonInventorySearchInput:
    """The generated search input of an `InventoryFilter`; unset conditions are left out."""
    return PersonInventorySearchInput(
        **present(
            color_enum=wire_enums(CatalogColor, value.colors),
            csgo_charm=value.has_charm,
            csgo_collection=value.collection,
            csgo_exterior_enum=wire_enums(CSGOExterior, value.exteriors),
            csgo_fade_from=value.fade_from,
            csgo_fade_rank_from=value.fade_rank_from,
            csgo_fade_rank_to=value.fade_rank_to,
            csgo_fade_to=value.fade_to,
            csgo_float_from=wire_decimal(value.float_from),
            csgo_float_to=wire_decimal(value.float_to),
            csgo_item_category_enum=wire_enum(CSGOCategory, value.category),
            csgo_item_subcategory_enum=wire_enum(CSGOSubcategory, value.subcategory),
            csgo_pattern=value.pattern,
            csgo_phase_enum=wire_enum(CSGOPhase, value.phase),
            csgo_rarity_enum=wire_enums(CSGORarity, value.rarities),
            csgo_souvenir=value.souvenir,
            csgo_stat_trak=value.stat_trak,
            csgo_sticker_names=wire_list(value.sticker_names),
            csgo_sticker_names_operand=wire_enum(WireLogicOperand, value.sticker_names_operand),
            csgo_stickers=value.has_stickers,
            name=value.name,
            name_hash=value.name_hash,
            name_strict=value.name_strict,
            sort=None if value.sort is None else product_sort_input(value.sort),
        )
    )


def store_input(value: "StoreSettings") -> PersonStoreInput:
    """The generated input of `StoreSettings`; a field left out (`None`) is not sent.

    Raises `ValueError` for an avatar or banner the API schema does not accept."""
    return PersonStoreInput(
        **present(
            avatar=wire_enum(AvatarType, value.avatar),
            banner=wire_enum(BannerType, value.banner),
            encoded_custom_avatar=value.custom_avatar,
            is_achievements_public=value.is_achievements_public,
            is_favorites_public=value.is_favorites_public,
            is_items_on_sale_public=value.is_items_on_sale_public,
            is_store_name_public=value.is_store_name_public,
            is_trade_history_public=value.is_trade_history_public,
            store_name=value.store_name,
        )
    )
