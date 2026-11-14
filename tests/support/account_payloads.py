"""Synthetic wire JSON (by alias) of the inventory, wallet, profile and store operations.

Every builder starts from `model_json` (the smallest valid object of the generated model) and sets
what a test cares about; values are invented, never recorded.
"""

from typing import Any

from support import market_payloads as mp
from support.payloads import model_json
from whitemarket._generated.email_set import EmailSetEmailSet
from whitemarket._generated.fragments import PersonPublicFields
from whitemarket._generated.inventory_my import (
    InventoryMyInventoryMyEdgesNodeCSGOInventoryItem,
    InventoryMyInventoryMyEdgesNodeCSGOInventoryItemDescriptionCSGOSteamItem,
)
from whitemarket._generated.person_profile import PersonProfilePersonProfile
from whitemarket._generated.store_my import StoreMyStoreMy
from whitemarket._generated.wallet_credit_get import WalletCreditGetWalletCreditGet
from whitemarket._generated.wallet_deposits import WalletDepositsWalletDeposits
from whitemarket._generated.wallet_transactions import (
    WalletTransactionsWalletTransactionsEdgesNode,
)
from whitemarket._generated.wallet_transfers import WalletTransfersWalletTransfersEdgesNode
from whitemarket._generated.wallet_withdrawals import WalletWithdrawalsWalletWithdrawals

STEAM_ID = "76561190000000001"
T1 = "2026-10-30T10:00:00+00:00"
T2 = "2026-10-30T10:05:00+00:00"
T3 = "2026-10-31T10:00:00+00:00"


def money(value: str = "1.00", currency: str = "USD") -> dict[str, Any]:
    return mp.money(value, currency)


def person(id: str = "p-1", **overrides: Any) -> dict[str, Any]:
    """A `PersonPublic` (a party to a wallet operation)."""
    base = model_json(PersonPublicFields)
    return {
        **base,
        "id": id,
        "steamId": STEAM_ID,
        "steamName": "Synthetic",
        "steamLevel": 7,
        "deliveryPromise": "HOUR1",
        **overrides,
    }


def connection(
    root: str,
    nodes: list[dict[str, Any]],
    end_cursor: str | None = None,
    has_next_page: bool = False,
    total_count: int | None = None,
) -> dict[str, Any]:
    """The `data` of a paginated answer with one edge per node."""
    edges = [{"cursor": f"c-{index}", "node": node} for index, node in enumerate(nodes)]
    return {
        root: {
            "edges": edges,
            "pageInfo": mp.page_info(end_cursor, has_next_page),
            "totalCount": len(nodes) if total_count is None else total_count,
        }
    }


# ---- inventory ----


def inventory_item(**overrides: Any) -> dict[str, Any]:
    """A `CSGOInventoryItem` as `inventory_my` selects it."""
    base = model_json(InventoryMyInventoryMyEdgesNodeCSGOInventoryItem)
    steam = model_json(InventoryMyInventoryMyEdgesNodeCSGOInventoryItemDescriptionCSGOSteamItem)
    steam.update({"__typename": "CSGOSteamItem", "name": "AK-47 | Redline (Field-Tested)"})
    return {**base, **mp.item(description=steam), **overrides}


def inventory_page(
    ids: list[str], end_cursor: str | None = None, has_next_page: bool = False
) -> dict[str, Any]:
    nodes = [inventory_item(id=f"item-{i}", product=None, deal=None) for i in ids]
    return connection("inventory_my", nodes, end_cursor, has_next_page)


# ---- wallet ----


def deposit(**overrides: Any) -> dict[str, Any]:
    return {
        **model_json(WalletDepositsWalletDeposits),
        "id": "dep-1",
        "createdAt": T1,
        "completedAt": T2,
        "expiredAt": T3,
        "provider": "AIRWALLEX",
        "status": "PROCESSING",
        "amount": money("100.05"),
        "comment": "a comment",
        "providerCorrespondingId": "prov-1",
        "providerPaymentPage": "https://example.invalid/pay",
        "airwallexSecret": "synthetic-airwallex-secret",
        "person": person("p-1"),
        **overrides,
    }


def withdrawal(**overrides: Any) -> dict[str, Any]:
    return {
        **model_json(WalletWithdrawalsWalletWithdrawals),
        "id": "wd-1",
        "createdAt": T1,
        "completedAt": T2,
        "expiredAt": T3,
        "provider": "SEPA",
        "status": "SUCCESS",
        "amount": money("7.77"),
        "comment": "note",
        "providerCorrespondingId": "prov-9",
        "person": person("p-2"),
        **overrides,
    }


def transaction(**overrides: Any) -> dict[str, Any]:
    return {
        **model_json(WalletTransactionsWalletTransactionsEdgesNode),
        "id": "t-1",
        "createdAt": T1,
        "reason": "MARKET_PRODUCT",
        "reasonId": "deal-77",
        "status": "SUCCESS_HOLD",
        "amount": money("-10.10"),
        "fee": money("0.31"),
        "comment": "c",
        "initialCurrency": "USDT",
        "marketDealActionType": "SELL",
        "method": "WHITEBIT_CODE",
        "network": "TRC20",
        "withdrawalAddress": "synthetic-address",
        "person": person("me"),
        "counterparty": person("them", steamId="76561190000000002"),
        **overrides,
    }


def transfer(**overrides: Any) -> dict[str, Any]:
    """A `WalletTransfer` as `wallet_transfers` and `wallet_transfer_send` select it."""
    return {
        **model_json(WalletTransfersWalletTransfersEdgesNode),
        "id": "tr-1",
        "createdAt": T1,
        "completedAt": T2,
        "status": "PROCESSING",
        "amount": money("3.30"),
        "comment": "hi",
        "from": person("a"),
        "to": person("b"),
        **overrides,
    }


def debt(**overrides: Any) -> dict[str, Any]:
    return {
        **model_json(WalletCreditGetWalletCreditGet),
        "id": "debt-1",
        "createdAt": T1,
        "amount": money("25.00"),
        "person": person("me"),
        **overrides,
    }


def credit(max: str = "1000.00", used: str = "250.5", available: str = "749.50") -> dict[str, Any]:
    return {
        "wallet_credit_max": money(max),
        "wallet_credit_used": money(used),
        "wallet_credit_available": money(available),
    }


# ---- profile ----

TRADE_URL = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=syntheticTradeToken"


def profile(**overrides: Any) -> dict[str, Any]:
    """A `PersonFull` plus `tradingCompetitionStat`, the same for every operation returning one."""
    base = model_json(PersonProfilePersonProfile)
    return {**base, "id": "person-1", "locale": "UK_UA", **overrides}


def email_profile(**overrides: Any) -> dict[str, Any]:
    base = model_json(EmailSetEmailSet)
    return {**base, "id": "person-1", "locale": "UK_UA", **overrides}


# ---- store ----


def achievement(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "FIRST_SELL",
        "points": 10,
        "status": "IN_PROGRESS",
        "type": "PROGRESS",
        "unlockedAt": None,
        "params": [],
        **overrides,
    }


def store(**overrides: Any) -> dict[str, Any]:
    base = model_json(StoreMyStoreMy)
    return {
        **base,
        "id": "store-1",
        "storeName": "Synthetic store",
        "achievements": [],
        **overrides,
    }
