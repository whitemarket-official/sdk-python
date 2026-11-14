"""One read-only call with minimal variables for EVERY generated query operation.

Keyed by the GraphQL operation name. A test pins the key set to `graphql/operations/query/`, so a
schema sync that adds a query fails until it is added here.
"""

import uuid
from collections.abc import Callable
from typing import Any

from whitemarket._generated.enums import Currency
from whitemarket._generated.input_types import ForwardPaginationInput, SteamLinkInput
from whitemarket._generated.sync_client import GeneratedClient

# Synthetic trade offer URL: well-formed, belongs to no real account. A profile URL is rejected
# by the server (SPEC_SYNC 4), so it must not be used here.
SYNTHETIC_TRADE_URL = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcdefgh"
NON_EXISTENT_STATUS_ID = "non-existent"


def steps(api: GeneratedClient) -> dict[str, Callable[[], Any]]:
    first = ForwardPaginationInput(first=1)
    unknown_id = str(uuid.uuid4())
    return {
        "DealBalanceHold": lambda: api.deal_balance_hold(Currency.USD),
        "DealBalancesHold": api.deal_balances_hold,
        "DealBuyerList": api.deal_buyer_list,
        "DealBuyerStatuses": lambda: api.deal_buyer_statuses([NON_EXISTENT_STATUS_ID]),
        "DealHistory": lambda: api.deal_history(forward_pagination=first),
        "DealHistoryItem": lambda: api.deal_history_item(id=unknown_id),
        "DealItem": lambda: api.deal_item(id=unknown_id),
        "DealSellerList": api.deal_seller_list,
        "InventoryMy": lambda: api.inventory_my(forward_pagination=first),
        "MarketCsgoStickersSuggestion": lambda: api.market_csgo_stickers_suggestion("a", limit=1),
        "MarketItem": lambda: api.market_item(unknown_id),
        "MarketList": lambda: api.market_list(forward_pagination=first),
        "MarketMy": lambda: api.market_my(forward_pagination=first),
        "MarketTradeUrl": lambda: api.market_trade_url(SteamLinkInput(value=SYNTHETIC_TRADE_URL)),
        "OrderList": lambda: api.order_list(forward_pagination=first),
        "OrderMy": lambda: api.order_my(forward_pagination=first),
        "OrderMyActive": lambda: api.order_my_active(forward_pagination=first),
        "OrderMyFulfilled": lambda: api.order_my_fulfilled(forward_pagination=first),
        "OrderMyInactive": lambda: api.order_my_inactive(forward_pagination=first),
        "PersonProfile": api.person_profile,
        "ProfileId": api.profile_id,
        "ProfileSteamProxyGet": api.profile_steam_proxy_get,
        "StoreMy": api.store_my,
        "TestPing": api.test_ping,
        "WalletBalance": lambda: api.wallet_balance(Currency.USD),
        "WalletBalances": api.wallet_balances,
        "WalletCreditAvailable": api.wallet_credit_available,
        "WalletCreditMax": api.wallet_credit_max,
        "WalletCreditUsed": api.wallet_credit_used,
        "WalletDeposits": api.wallet_deposits,
        "WalletTransactions": lambda: api.wallet_transactions(forward_pagination=first),
        "WalletTransfers": lambda: api.wallet_transfers(forward_pagination=first),
        "WalletWithdrawals": api.wallet_withdrawals,
    }
