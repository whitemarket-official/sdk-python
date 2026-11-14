"""Mapper of the `Profile` model (SDK_SPEC 3.9)."""

from whitemarket._generated.fragments import PersonFullFields, TradingCompetitionPersonItemFields
from whitemarket._mappers.common import convert_enum, optional_enum, optional_secret
from whitemarket.models.account_enums import Locale
from whitemarket.models.enums import DeliveryPromise
from whitemarket.models.profile import Profile, TradingCompetitionStat


def map_profile(person: PersonFullFields, stat: TradingCompetitionPersonItemFields) -> Profile:
    """The profile of the `PersonFull` fragment and the `tradingCompetitionStat` next to it (every
    operation that returns a profile selects both)."""
    return Profile(
        id=person.id,
        registered_at=person.registered_at,
        locale=convert_enum(Locale, person.locale),
        email=person.email,
        is_email_confirmed=person.is_email_confirmed,
        can_buy=person.can_buy,
        can_sell=person.can_sell,
        can_deposit=person.can_deposit,
        can_withdraw=person.can_withdraw,
        is_kyc_verified=person.is_kyc_verified,
        has_partner_token=person.is_partner_token_exist,
        orders_auto_activate=person.market_order_auto_activate,
        delivery_promise=optional_enum(DeliveryPromise, person.delivery_promise_selected),
        steam_id=person.steam_id,
        steam_name=person.steam_name,
        steam_level=person.steam_level,
        steam_avatar_medium=person.steam_avatar_medium,
        steam_avatar_full=person.steam_avatar_full,
        steam_registered_at=person.steam_registered_at,
        steam_trade_url=optional_secret(person.steam_trade_url),
        inventory_updated_at=person.inventory_updated_at,
        discount_percent=person.discount_percent,
        discount_active_to=person.discount_active_to,
        sell_banned_until=person.sell_banned_until,
        vacation_until=person.vacation_until,
        level=person.level,
        points=person.points,
        left_points=person.left_points,
        percent=person.percent,
        referrals_count=person.referrals_count,
        inviter_code=person.inviter_code,
        referrer_code=person.referrer_code,
        referral_tag=person.referral_tag,
        country_code_of_residence=person.country_code_of_residence,
        country_code_of_current_location=person.country_code_of_current_location,
        is_achievements_enabled=person.is_achievements_enabled,
        is_skin_translation_enabled=person.is_skin_translation_enabled,
        is_mc_battle_pass_enabled=person.is_mc_battle_pass_enabled,
        trading_competition_stat=TradingCompetitionStat(
            position=stat.position, top_level=stat.top_level
        ),
    )
