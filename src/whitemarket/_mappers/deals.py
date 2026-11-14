"""Mappers of the deal models: `Deal` (in progress and archived) and `DealState`."""

from datetime import datetime
from typing import Protocol

from whitemarket._mappers.common import (
    MoneySource,
    Path,
    convert_enum,
    money,
    optional_enum,
    optional_money,
    optional_secret,
)
from whitemarket._mappers.products import (
    ProductHistorySource,
    map_inventory_item,
    map_product_history,
)
from whitemarket.models.deal_status import DealStatus
from whitemarket.models.deals import Deal, DealState
from whitemarket.models.enums import DealCancelReason, DeliveryType


class DealStateSource(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def custom_id(self) -> str | None: ...
    @property
    def status(self) -> str: ...
    @property
    def cancel_reason(self) -> str | None: ...
    @property
    def price(self) -> MoneySource: ...
    @property
    def steam_id(self) -> str | None: ...
    @property
    def trade_id(self) -> str | None: ...
    @property
    def is_trade_protected(self) -> bool | None: ...
    @property
    def settlement_time_at(self) -> datetime | None: ...
    @property
    def reverse_penalty_value(self) -> MoneySource | None: ...
    @property
    def reverse_refund_value(self) -> MoneySource | None: ...


class DealSource(Protocol):
    """A deal in progress (`MarketDeal`)."""

    @property
    def id(self) -> str: ...
    @property
    def custom_id(self) -> str | None: ...
    @property
    def status(self) -> str: ...
    @property
    def price(self) -> MoneySource: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def delivery_type(self) -> DeliveryType: ...
    @property
    def steam_id(self) -> str | None: ...
    @property
    def trade_id(self) -> str | None: ...
    @property
    def is_trade_protected(self) -> bool: ...
    @property
    def settlement_time_at(self) -> datetime | None: ...
    @property
    def expired_at(self) -> datetime: ...
    @property
    def is_cancel_by_buyer_supported(self) -> bool: ...
    @property
    def cancel_by_buyer_need_wait(self) -> int | None: ...
    @property
    def receiver_trade_url(self) -> str | None: ...
    @property
    def product(self) -> ProductHistorySource: ...
    @property
    def item(self) -> object: ...


class ArchivedDealSource(Protocol):
    """An archived deal (`MarketDealHistory`)."""

    @property
    def id(self) -> str: ...
    @property
    def custom_id(self) -> str | None: ...
    @property
    def status(self) -> str: ...
    @property
    def price(self) -> MoneySource: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def delivery_type(self) -> DeliveryType: ...
    @property
    def steam_id(self) -> str | None: ...
    @property
    def cancel_reason(self) -> str | None: ...
    @property
    def archived_at(self) -> datetime: ...
    @property
    def reverse_penalty_value(self) -> MoneySource | None: ...
    @property
    def reverse_refund_value(self) -> MoneySource | None: ...
    @property
    def product(self) -> ProductHistorySource: ...


def map_deal_state(source: DealStateSource, path: Path) -> DealState:
    return DealState(
        id=source.id,
        custom_id=source.custom_id,
        status=convert_enum(DealStatus, source.status),
        cancel_reason=optional_enum(DealCancelReason, source.cancel_reason),
        price=money(source.price, (*path, "price")),
        steam_id=source.steam_id,
        trade_id=source.trade_id,
        is_trade_protected=source.is_trade_protected,
        settlement_time_at=source.settlement_time_at,
        reverse_penalty=optional_money(
            source.reverse_penalty_value, (*path, "reversePenaltyValue")
        ),
        reverse_refund=optional_money(source.reverse_refund_value, (*path, "reverseRefundValue")),
    )


def deal_state_of(deal: Deal) -> DealState:
    """The status snapshot of a deal read with `deal_item` / `deal_history_item` (a seller's deal
    is not in `deal_buyer_statuses`)."""
    return DealState(
        id=deal.id,
        custom_id=deal.custom_id,
        status=deal.status,
        cancel_reason=deal.cancel_reason,
        price=deal.price,
        steam_id=deal.steam_id,
        trade_id=deal.trade_id,
        is_trade_protected=deal.is_trade_protected,
        settlement_time_at=deal.settlement_time_at,
        reverse_penalty=deal.reverse_penalty,
        reverse_refund=deal.reverse_refund,
    )


def map_deal(source: DealSource, path: Path) -> Deal:
    """A deal in progress. A null or empty `receiver_trade_url` is no URL (SDK_SPEC 3.4 rule 11)."""
    return Deal(
        id=source.id,
        custom_id=source.custom_id,
        status=convert_enum(DealStatus, source.status),
        price=money(source.price, (*path, "price")),
        created_at=source.created_at,
        delivery_type=source.delivery_type,
        steam_id=source.steam_id,
        trade_id=source.trade_id,
        is_trade_protected=source.is_trade_protected,
        settlement_time_at=source.settlement_time_at,
        expires_at=source.expired_at,
        is_cancel_by_buyer_supported=source.is_cancel_by_buyer_supported,
        cancel_by_buyer_need_wait=source.cancel_by_buyer_need_wait,
        cancel_reason=None,
        archived_at=None,
        reverse_penalty=None,
        reverse_refund=None,
        product=map_product_history(source.product, (*path, "product")),
        item=map_inventory_item(source.item, None, (*path, "item")),
        receiver_trade_url=optional_secret(source.receiver_trade_url),
    )


def map_archived_deal(source: ArchivedDealSource, path: Path) -> Deal:
    return Deal(
        id=source.id,
        custom_id=source.custom_id,
        status=convert_enum(DealStatus, source.status),
        price=money(source.price, (*path, "price")),
        created_at=source.created_at,
        delivery_type=source.delivery_type,
        steam_id=source.steam_id,
        trade_id=None,
        is_trade_protected=None,
        settlement_time_at=None,
        expires_at=None,
        is_cancel_by_buyer_supported=False,
        cancel_by_buyer_need_wait=None,
        cancel_reason=optional_enum(DealCancelReason, source.cancel_reason),
        archived_at=source.archived_at,
        reverse_penalty=optional_money(
            source.reverse_penalty_value, (*path, "reversePenaltyValue")
        ),
        reverse_refund=optional_money(source.reverse_refund_value, (*path, "reverseRefundValue")),
        product=map_product_history(source.product, (*path, "product")),
        item=None,
    )
