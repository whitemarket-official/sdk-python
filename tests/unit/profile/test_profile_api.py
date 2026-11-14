"""`client.profile` through the HTTP boundary: request shape, secrets, mapping (SDK_SPEC 3.9).

Every case runs against the async client and its generated sync twin. Responses are synthetic.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from support import account_payloads as ap
from support.clients import Rig
from support.flavors import Flavor
from support.http import Reply, data, json_response, reply
from whitemarket import RetryPolicy, Secret
from whitemarket.errors import GraphQLError, ServerError
from whitemarket.models import DeliveryPromise
from whitemarket.models.account_enums import Locale

STEAM_PAYLOAD = "synthetic-steam-token-payload"
PROXY = "http://synthetic-user:synthetic-pass@proxy.invalid:8080"
TRADE_URL = ap.TRADE_URL
Call = Callable[[Any], Any]


def case(
    call: Call, operation: str, variables: dict[str, Any], answer: dict[str, Any], expected: Any
) -> Any:
    return pytest.param(call, operation, variables, answer, expected, id=operation)


CALLS = [
    case(lambda p: p.id(), "ProfileId", {}, {"profile_id": "person-77"}, "person-77"),
    case(
        lambda p: p.set_trade_url(TRADE_URL),
        "ProfileSteamLink",
        {"link": {"value": TRADE_URL}},
        {"profile_steam_link": True},
        True,
    ),
    pytest.param(
        lambda p: p.set_trade_url(TRADE_URL),
        "ProfileSteamLink",
        {"link": {"value": TRADE_URL}},
        {"profile_steam_link": False},
        False,
        id="set_trade_url returns the server Boolean",
    ),
    pytest.param(
        lambda p: p.set_steam_proxy(Secret(PROXY)),
        "ProfileSteamProxySet",
        {"proxy": {"value": PROXY}},
        {"profile_steam_proxy_set": True},
        True,
        id="set_steam_proxy without ttl",
    ),
    pytest.param(
        lambda p: p.set_steam_proxy(Secret(PROXY), 3600),
        "ProfileSteamProxySet",
        {"proxy": {"value": PROXY}, "ttl": 3600},
        {"profile_steam_proxy_set": True},
        True,
        id="set_steam_proxy with ttl passed through",
    ),
    pytest.param(
        lambda p: p.set_steam_proxy(Secret(PROXY), 0),
        "ProfileSteamProxySet",
        {"proxy": {"value": PROXY}, "ttl": 0},
        {"profile_steam_proxy_set": True},
        True,
        id="set_steam_proxy with ttl 0 is not dropped",
    ),
    case(
        lambda p: p.delete_steam_proxy(),
        "ProfileSteamProxyDelete",
        {},
        {"profile_steam_proxy_delete": True},
        True,
    ),
    pytest.param(
        lambda p: p.set_steam_token(Secret(STEAM_PAYLOAD)),
        "ProfileTokenSet",
        {"ownProxyRequired": False, "payload": STEAM_PAYLOAD},
        {"profile_token_set": True},
        True,
        id="set_steam_token default sends ownProxyRequired false",
    ),
    pytest.param(
        lambda p: p.set_steam_token(Secret(STEAM_PAYLOAD), True, 60),
        "ProfileTokenSet",
        {"ownProxyRequired": True, "payload": STEAM_PAYLOAD, "ttl": 60},
        {"profile_token_set": True},
        True,
        id="set_steam_token with own_proxy_required and ttl",
    ),
    pytest.param(
        lambda p: p.check_steam_token(),
        "ProfileTokenCheck",
        {},
        {"profile_token_check": 7},
        7,
        id="check_steam_token returns the Int verbatim",
    ),
    pytest.param(
        lambda p: p.check_steam_token(),
        "ProfileTokenCheck",
        {},
        {"profile_token_check": None},
        None,
        id="check_steam_token null",
    ),
    case(
        lambda p: p.delete_steam_token(),
        "ProfileTokenDelete",
        {},
        {"profile_token_delete": True},
        True,
    ),
    pytest.param(
        lambda p: p.link_referrer("REF1"),
        "ProfileReferrer",
        {"referrerInput": {"referrerCode": {"value": "REF1"}}},
        {"profile_referrer": True},
        True,
        id="link_referrer without tag",
    ),
    pytest.param(
        lambda p: p.link_referrer("REF1", "tag-a"),
        "ProfileReferrer",
        {"referrerInput": {"referrerCode": {"value": "REF1"}, "referrerTag": "tag-a"}},
        {"profile_referrer": True},
        True,
        id="link_referrer with tag",
    ),
    case(
        lambda p: p.change_referrer_code("NEWCODE"),
        "ProfileReferrerCode",
        {"referrerCode": {"value": "NEWCODE"}},
        {"profile_referrer_code": True},
        True,
    ),
]


@pytest.mark.parametrize(("call", "operation", "variables", "answer", "expected"), CALLS)
def test_sends_one_request_with_the_exact_variables_and_returns_the_server_value(
    flavor: Flavor,
    *,
    call: Call,
    operation: str,
    variables: dict[str, Any],
    answer: dict[str, Any],
    expected: Any,
) -> None:
    with Rig(flavor, data(**answer)) as rig:
        result = rig.call(call(rig.client.profile))

        (body,) = rig.bodies()
    assert (body["operationName"], body.get("variables", {})) == (operation, variables)
    assert result == expected
    assert type(result) is type(expected)


PROFILE_CALLS = [
    pytest.param(lambda p: p.get(), "PersonProfile", "person_profile", id="get"),
    pytest.param(
        lambda p: p.set_email("someone@example.invalid"), "EmailSet", "email_set", id="set_email"
    ),
    pytest.param(
        lambda p: p.confirm_email("123456", "sign-1"),
        "EmailConfirm",
        "email_confirm",
        id="confirm_email",
    ),
    pytest.param(
        lambda p: p.resend_email_confirmation(),
        "EmailConfirmationResend",
        "email_confirmation_resend",
        id="resend_email_confirmation",
    ),
]


@pytest.mark.parametrize(("call", "operation", "field"), PROFILE_CALLS)
def test_every_profile_returning_method_maps_the_same_profile(
    flavor: Flavor, call: Call, operation: str, field: str
) -> None:
    with Rig(flavor, data(**{field: ap.profile(email="someone@example.invalid")})) as rig:
        profile = rig.call(call(rig.client.profile))

        assert rig.bodies()[0]["operationName"] == operation
    assert profile.id == "person-1"
    assert profile.email == "someone@example.invalid"
    assert profile.locale is Locale.UK_UA


def test_set_email_and_confirm_email_send_their_variables(flavor: Flavor) -> None:
    answers = [
        data(email_set=ap.profile()),
        data(email_confirm=ap.profile()),
        data(email_confirm=ap.profile()),
    ]
    with Rig(flavor, *answers) as rig:
        rig.call(rig.client.profile.set_email("someone@example.invalid"))
        rig.call(rig.client.profile.confirm_email("123456"))
        rig.call(rig.client.profile.confirm_email("123456", "sign-1"))

        assert [(b["operationName"], b["variables"]) for b in rig.bodies()] == [
            ("EmailSet", {"email": {"value": "someone@example.invalid"}}),
            ("EmailConfirm", {"code": "123456"}),
            ("EmailConfirm", {"code": "123456", "sign": "sign-1"}),
        ]


def test_the_profile_maps_every_field(flavor: Flavor) -> None:
    node = ap.profile(
        registeredAt="2026-01-02T03:04:05+00:00",
        locale="RU_RU",
        email="someone@example.invalid",
        isEmailConfirmed=True,
        canBuy=True,
        canSell=False,
        canDeposit=True,
        canWithdraw=False,
        isKycVerified=True,
        isPartnerTokenExist=True,
        marketOrderAutoActivate=True,
        deliveryPromiseSelected="MINUTES10",
        steamId=ap.STEAM_ID,
        steamName="Synthetic",
        steamLevel=12,
        steamAvatarMedium="https://example.invalid/m.png",
        steamAvatarFull="https://example.invalid/f.png",
        steamRegisteredAt="2020-05-06T00:00:00+00:00",
        steamTradeUrl=TRADE_URL,
        inventoryUpdatedAt="2026-11-01T00:00:00+00:00",
        discountPercent=5,
        discountActiveTo="2026-12-01T00:00:00+00:00",
        sellBannedUntil="2026-11-05T00:00:00+00:00",
        vacationUntil="2026-11-06T00:00:00+00:00",
        level=3,
        points=100,
        leftPoints=20,
        percent="12.5",
        referralsCount=4,
        inviterCode="INV",
        referrerCode="REF",
        referralTag="tag",
        countryCodeOfResidence="UA",
        countryCodeOfCurrentLocation="PL",
        isAchievementsEnabled=True,
        isSkinTranslationEnabled=True,
        isMcBattlePassEnabled=True,
        tradingCompetitionStat={"position": 9, "topLevel": 2},
    )
    with Rig(flavor, data(person_profile=node)) as rig:
        p = rig.call(rig.client.profile.get())

    assert p.registered_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert p.locale is Locale.RU_RU
    assert (p.can_buy, p.can_sell, p.can_deposit, p.can_withdraw) == (True, False, True, False)
    assert (p.is_email_confirmed, p.is_kyc_verified) == (True, True)
    assert (p.has_partner_token, p.orders_auto_activate) == (True, True)
    assert p.delivery_promise is DeliveryPromise.MINUTES10
    assert (p.steam_id, p.steam_name, p.steam_level) == (ap.STEAM_ID, "Synthetic", 12)
    assert (p.steam_avatar_medium, p.steam_avatar_full) == (
        "https://example.invalid/m.png",
        "https://example.invalid/f.png",
    )
    assert p.steam_registered_at == datetime(2020, 5, 6, tzinfo=UTC)
    assert p.inventory_updated_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert (p.discount_percent, p.discount_active_to) == (5, datetime(2026, 12, 1, tzinfo=UTC))
    assert p.sell_banned_until == datetime(2026, 11, 5, tzinfo=UTC)
    assert p.vacation_until == datetime(2026, 11, 6, tzinfo=UTC)
    assert (p.level, p.points, p.left_points) == (3, 100, 20)
    assert p.percent == "12.5"
    assert (p.referrals_count, p.inviter_code, p.referrer_code, p.referral_tag) == (
        4,
        "INV",
        "REF",
        "tag",
    )
    assert (p.country_code_of_residence, p.country_code_of_current_location) == ("UA", "PL")
    assert (p.is_achievements_enabled, p.is_skin_translation_enabled) == (True, True)
    assert p.is_mc_battle_pass_enabled is True
    assert (p.trading_competition_stat.position, p.trading_competition_stat.top_level) == (9, 2)


def test_a_profile_with_nulls_maps_them_to_none(flavor: Flavor) -> None:
    with Rig(flavor, data(person_profile=ap.profile(deliveryPromiseSelected=None))) as rig:
        p = rig.call(rig.client.profile.get())

    assert (p.email, p.delivery_promise, p.steam_trade_url, p.percent, p.vacation_until) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert (p.trading_competition_stat.position, p.trading_competition_stat.top_level) == (
        None,
        None,
    )


def test_unknown_profile_enum_values_are_kept(flavor: Flavor) -> None:
    node = ap.profile(locale="XX_XX", deliveryPromiseSelected="WEEKS2")
    with Rig(flavor, data(person_profile=node)) as rig:
        p = rig.call(rig.client.profile.get())

    assert (p.locale.value, p.locale.is_unknown) == ("XX_XX", True)
    assert p.delivery_promise is not None
    assert p.delivery_promise.value == "WEEKS2"


@pytest.mark.parametrize(
    ("server", "revealed"),
    [
        pytest.param(TRADE_URL, TRADE_URL, id="a URL -> Secret"),
        pytest.param(None, None, id="null -> None"),
        pytest.param("", None, id="empty string -> None"),
    ],
)
def test_the_trade_url_of_the_profile_is_a_secret_or_none(
    flavor: Flavor, server: str | None, revealed: str | None
) -> None:
    with Rig(flavor, data(person_profile=ap.profile(steamTradeUrl=server))) as rig:
        p = rig.call(rig.client.profile.get())

    if revealed is None:
        assert p.steam_trade_url is None
        return
    assert isinstance(p.steam_trade_url, Secret)
    assert p.steam_trade_url.reveal() == revealed


def test_the_profile_never_prints_the_trade_url(flavor: Flavor) -> None:
    with Rig(flavor, data(person_profile=ap.profile(steamTradeUrl=TRADE_URL))) as rig:
        p = rig.call(rig.client.profile.get())

    for text in (repr(p), str(p), f"{p.steam_trade_url}", repr(p.steam_trade_url)):
        assert "syntheticTradeToken" not in text
    assert str(p.steam_trade_url) == "***"


@pytest.mark.parametrize(
    ("server", "revealed"),
    [
        pytest.param(PROXY, PROXY, id="a URL -> Secret"),
        pytest.param(None, None, id="null -> None"),
        pytest.param("", None, id="empty string -> None"),
    ],
)
def test_steam_proxy_wraps_the_url_in_a_secret_and_maps_nothing_to_none(
    flavor: Flavor, server: str | None, revealed: str | None
) -> None:
    with Rig(flavor, data(profile_steam_proxy_get=server)) as rig:
        proxy = rig.call(rig.client.profile.steam_proxy())

        (body,) = rig.bodies()
        assert (body["operationName"], body.get("variables", {})) == ("ProfileSteamProxyGet", {})
    if revealed is None:
        assert proxy is None
        return
    assert isinstance(proxy, Secret)
    assert proxy.reveal() == revealed
    assert "synthetic-pass" not in f"{proxy!r} {proxy} {proxy:>20}"


def test_steam_proxy_is_retried_like_a_query(flavor: Flavor) -> None:
    answers = (reply(503), data(profile_steam_proxy_get=None))
    with Rig(flavor, *answers, retry=RetryPolicy(max_attempts=2, base_delay=0)) as rig:
        assert rig.call(rig.client.profile.steam_proxy()) is None
        assert rig.script.count == 2


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda p: p.set_trade_url(TRADE_URL), id="set_trade_url"),
        pytest.param(lambda p: p.set_steam_proxy(Secret(PROXY)), id="set_steam_proxy"),
        pytest.param(lambda p: p.delete_steam_proxy(), id="delete_steam_proxy"),
        pytest.param(lambda p: p.set_steam_token(Secret(STEAM_PAYLOAD)), id="set_steam_token"),
        pytest.param(lambda p: p.check_steam_token(), id="check_steam_token"),
        pytest.param(lambda p: p.delete_steam_token(), id="delete_steam_token"),
        pytest.param(lambda p: p.set_email("someone@example.invalid"), id="set_email"),
        pytest.param(lambda p: p.confirm_email("123456"), id="confirm_email"),
        pytest.param(lambda p: p.resend_email_confirmation(), id="resend_email_confirmation"),
        pytest.param(lambda p: p.link_referrer("REF1"), id="link_referrer"),
        pytest.param(lambda p: p.change_referrer_code("NEWCODE"), id="change_referrer_code"),
    ],
)
def test_a_mutation_answered_503_is_sent_exactly_once_and_the_failure_propagates(
    flavor: Flavor, call: Call
) -> None:
    with Rig(flavor, reply(503), retry=RetryPolicy(max_attempts=3, base_delay=0)) as rig:
        with pytest.raises(ServerError):
            rig.call(call(rig.client.profile))

        assert rig.script.count == 1


def test_a_graphql_error_of_a_mutation_propagates_as_it_is_with_its_category(
    flavor: Flavor,
) -> None:
    answer: Reply = json_response(
        {
            "data": None,
            "errors": [{"message": "x", "extensions": {"category": "profile.email.invalid"}}],
        }
    )
    with Rig(flavor, answer) as rig, pytest.raises(GraphQLError) as caught:
        rig.call(rig.client.profile.set_email("not-an-email"))

    assert caught.value.errors[0].category == "profile.email.invalid"


@pytest.mark.parametrize(
    ("call", "secret"),
    [
        pytest.param(
            lambda p: p.set_steam_token(Secret(STEAM_PAYLOAD)), STEAM_PAYLOAD, id="set_steam_token"
        ),
        pytest.param(
            lambda p: p.set_steam_proxy(Secret(PROXY)), "synthetic-pass", id="set_steam_proxy"
        ),
        pytest.param(
            lambda p: p.set_trade_url(TRADE_URL), "syntheticTradeToken", id="set_trade_url"
        ),
        pytest.param(
            lambda p: p.confirm_email("synthetic-code-424242"),
            "synthetic-code-424242",
            id="confirm_email",
        ),
    ],
)
def test_a_failed_mutation_reveals_its_secret_neither_in_the_error_nor_in_the_log(
    flavor: Flavor,
    caplog: pytest.LogCaptureFixture,
    call: Call,
    secret: str,
) -> None:
    with Rig(flavor, reply(500)) as rig, caplog.at_level(logging.DEBUG):
        with pytest.raises(ServerError) as caught:
            rig.call(call(rig.client.profile))

        sent = rig.script.requests[0].content.decode()
    assert secret in sent, "the secret is sent in the request body"
    error = caught.value
    assert secret not in f"{error} {error!r}"
    assert secret not in caplog.text


@pytest.mark.parametrize("wrong", ["http://user:pass@proxy.invalid:1", None, b"x"])
def test_secret_parameters_refuse_a_plain_value(flavor: Flavor, wrong: Any) -> None:
    with Rig(flavor, data(profile_steam_proxy_set=True)) as rig:
        with pytest.raises(TypeError, match="proxy"):
            rig.call(rig.client.profile.set_steam_proxy(wrong))
        with pytest.raises(TypeError, match="payload"):
            rig.call(rig.client.profile.set_steam_token(wrong))

        assert rig.script.count == 0


def test_the_secret_arguments_do_not_show_in_a_traceback_message(flavor: Flavor) -> None:
    with Rig(flavor, reply(500)) as rig, pytest.raises(ServerError) as caught:
        rig.call(rig.client.profile.set_steam_token(Secret(STEAM_PAYLOAD)))

    assert STEAM_PAYLOAD not in str(caught.value.__cause__ or "")
    assert STEAM_PAYLOAD not in repr(caught.value)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda p: p.set_trade_url("https://x.invalid/?t=\ud800"), id="set_trade_url"),
        pytest.param(lambda p: p.set_email("a\ud800@example.invalid"), id="set_email"),
    ],
)
def test_a_text_that_cannot_be_encoded_is_refused_before_anything_is_sent(
    flavor: Flavor, call: Call
) -> None:
    with Rig(flavor, data(profile_steam_link=True)) as rig:
        with pytest.raises(ValueError, match="valid Unicode text") as caught:
            rig.call(call(rig.client.profile))

        assert rig.script.count == 0
    assert "\ud800" not in str(caught.value)
