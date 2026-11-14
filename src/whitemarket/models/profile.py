"""Model of the partner's own account (SDK_SPEC 3.9)."""

from dataclasses import dataclass, field
from datetime import datetime

from whitemarket._runtime.secret import Secret
from whitemarket.models.account_enums import Locale
from whitemarket.models.enums import DeliveryPromise


@dataclass(frozen=True, slots=True, kw_only=True)
class TradingCompetitionStat:
    """The account's standing in the trading competition; both figures are `None` when it does
    not take part."""

    position: int | None
    top_level: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    """The partner's own account (`profile.get()` and the result of the `*_email` methods).

    `steam_trade_url` is a `Secret` (`None` for null or an empty value, left out of `repr()`): the
    URL carries the account's trade token; call `.reveal()` to read it. `percent` is the server's
    "personal percentage based on points earned", kept as sent (its format is undocumented).
    `delivery_promise` is the seller promise the account selected.
    """

    id: str
    registered_at: datetime
    locale: Locale
    email: str | None
    is_email_confirmed: bool
    can_buy: bool
    can_sell: bool
    can_deposit: bool
    can_withdraw: bool
    is_kyc_verified: bool
    has_partner_token: bool
    orders_auto_activate: bool
    delivery_promise: DeliveryPromise | None
    steam_id: str | None
    steam_name: str | None
    steam_level: int | None
    steam_avatar_medium: str | None
    steam_avatar_full: str | None
    steam_registered_at: datetime | None
    inventory_updated_at: datetime | None
    discount_percent: int | None
    discount_active_to: datetime | None
    sell_banned_until: datetime | None
    vacation_until: datetime | None
    level: int | None
    points: int | None
    left_points: int | None
    percent: str | None
    referrals_count: int | None
    inviter_code: str | None
    referrer_code: str | None
    referral_tag: str | None
    country_code_of_residence: str | None
    country_code_of_current_location: str | None
    is_achievements_enabled: bool
    is_skin_translation_enabled: bool
    is_mc_battle_pass_enabled: bool
    trading_competition_stat: TradingCompetitionStat
    steam_trade_url: Secret | None = field(default=None, repr=False)
