"""Synthetic wire JSON (by alias) of the market and deal operations, for mapping and API tests.

Every builder starts from `model_json` (the smallest valid object of the generated model) and sets
what a test cares about; values are invented, never recorded.
"""

from typing import Any

from support.payloads import model_json
from whitemarket._generated.deal_buyer_statuses import DealBuyerStatusesDealBuyerStatuses
from whitemarket._generated.deal_history_item import (
    DealHistoryItemDealHistoryItem,
    DealHistoryItemDealHistoryItemProduct,
)
from whitemarket._generated.deal_item import DealItemDealItem
from whitemarket._generated.market_item import MarketItemMarketItem
from whitemarket._generated.market_list import (
    MarketListMarketListEdgesNode,
    MarketListMarketListEdgesNodeItemCSGOInventoryItem,
    MarketListMarketListEdgesNodeItemCSGOInventoryItemDescriptionCSGOSteamItem,
    MarketListMarketListEdgesNodeItemCSGOInventoryItemStickers,
)

PRICE = {"currency": "USD", "value": "12.50"}
CREATED = "2026-11-01T10:00:00+02:00"


def money(value: str = "12.50", currency: str = "USD") -> dict[str, Any]:
    return {"currency": currency, "value": value}


def steam_item(**overrides: Any) -> dict[str, Any]:
    """`description` of a CS2 item: the Steam name and the StatTrak / Souvenir flags."""
    base = model_json(MarketListMarketListEdgesNodeItemCSGOInventoryItemDescriptionCSGOSteamItem)
    base.update({"__typename": "CSGOSteamItem", "name": "AK-47 | Redline (Field-Tested)"})
    return {**base, "isStatTrak": False, "isSouvenir": False, **overrides}


def sticker(**overrides: Any) -> dict[str, Any]:
    base = model_json(MarketListMarketListEdgesNodeItemCSGOInventoryItemStickers)
    return {
        **base,
        "name": "cph2024_team_navi",
        "title": "Natus Vincere",
        "wear": None,
        **overrides,
    }


def item(**overrides: Any) -> dict[str, Any]:
    """A `CSGOInventoryItem` as `market_list` / `market_item` select it."""
    base = model_json(MarketListMarketListEdgesNodeItemCSGOInventoryItem)
    base.update(
        {
            "__typename": "CSGOInventoryItem",
            "id": "item-1",
            "assetId": "9007199254740993",  # beyond 2^53: must stay a string
            "classId": "310776560",
            "instanceId": "188530139",
            "nameHash": "AK-47 | Redline (Field-Tested)",
            "float": "0.15234567890123456789",
            "paintSeed": "661",
            "paintIndex": "282",
            "phase": None,
            "link": "steam://inspect/synthetic",
            "product": None,
            "deal": None,
            "description": steam_item(),
            "stickers": [],
        }
    )
    return {**base, **overrides}


def product(**overrides: Any) -> dict[str, Any]:
    """A `market_list` node (a `MarketProduct`)."""
    base = model_json(MarketListMarketListEdgesNode)
    base.update({"id": "product-1", "slug": "ak-47-redline", "price": PRICE, "createdAt": CREATED})
    base.update({"item": item()})
    return {**base, **overrides}


def market_item_node(**overrides: Any) -> dict[str, Any]:
    """The `market_item` field (a `MarketProduct`)."""
    base = model_json(MarketItemMarketItem)
    base.update(
        {
            "id": "product-1",
            "slug": "ak-47-redline",
            "price": PRICE,
            "createdAt": CREATED,
            "item": item(),
        }
    )
    return {**base, **overrides}


def page_info(end_cursor: str | None, has_next_page: bool) -> dict[str, Any]:
    return {
        "endCursor": end_cursor,
        "hasNextPage": has_next_page,
        "hasPreviousPage": False,
        "startCursor": None,
    }


def market_list_data(
    slugs: list[str],
    end_cursor: str | None = None,
    has_next_page: bool = False,
    total_count: int | None = None,
) -> dict[str, Any]:
    """The `data` of a `market_list` answer with one product per slug."""
    edges = [
        {"cursor": f"c-{slug}", "node": product(id=f"id-{slug}", slug=slug, item=None)}
        for slug in slugs
    ]
    return {
        "market_list": {
            "edges": edges,
            "pageInfo": page_info(end_cursor, has_next_page),
            "totalCount": len(slugs) if total_count is None else total_count,
        }
    }


def history_product(**overrides: Any) -> dict[str, Any]:
    """`product` of a deal (`MarketProductHistory`) with the Steam description and `params`."""
    base = model_json(DealHistoryItemDealHistoryItemProduct)
    base.update(
        {
            "id": "listing-1",
            "status": "DEAL",
            "price": PRICE,
            "archivedAt": "2026-11-02T10:00:00+00:00",
            "assetId": "9007199254740993",
            "classId": "310776560",
            "instanceId": "188530139",
            "description": steam_item(),
            "params": None,
            "store": None,
        }
    )
    return {**base, **overrides}


def deal(**overrides: Any) -> dict[str, Any]:
    """A deal in progress (`deal_item`)."""
    base = model_json(DealItemDealItem)
    base.update(
        {
            "id": "deal-1",
            "customId": "custom-1",
            "status": "OFFERED",
            "price": PRICE,
            "createdAt": CREATED,
            "expiredAt": "2026-11-03T10:00:00+02:00",
            "deliveryType": "SEMI",
            "isTradeProtected": True,
            "isCancelByBuyerSupported": True,
            "cancelByBuyerNeedWait": 120,
            "receiverTradeUrl": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=synthetic",
            "product": history_product(),
            "item": None,
        }
    )
    return {**base, **overrides}


def archived_deal(**overrides: Any) -> dict[str, Any]:
    """An archived deal (`deal_history_item`)."""
    base = model_json(DealHistoryItemDealHistoryItem)
    base.update(
        {
            "id": "deal-1",
            "customId": "custom-1",
            "status": "CANCELLED",
            "cancelReason": "NO_FUNDS",
            "price": PRICE,
            "createdAt": CREATED,
            "archivedAt": "2026-11-02T10:00:00+00:00",
            "deliveryType": "SEMI",
            "reversePenaltyValue": None,
            "reverseRefundValue": None,
            "product": history_product(),
        }
    )
    return {**base, **overrides}


def deal_state(**overrides: Any) -> dict[str, Any]:
    base = model_json(DealBuyerStatusesDealBuyerStatuses)
    base.update(
        {
            "id": "deal-1",
            "customId": "custom-1",
            "status": "EXCHANGED",
            "cancelReason": None,
            "price": PRICE,
            "isTradeProtected": True,
            "settlementTimeAt": "2026-11-09T10:00:00+00:00",
            "reversePenaltyValue": None,
            "reverseRefundValue": None,
        }
    )
    return {**base, **overrides}
