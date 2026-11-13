"""High-level enums against the generated (wire) enums they mirror.

Every value of a high-level enum must exist in the generated enum it is sent as, or `to_input()`
refuses it. The reverse is asserted only where a new value needs a decision (see
`test_deal_and_wallet_enums_know_every_schema_value`): a schema sync that adds a filter value
must stay green, and a raw `MarketProductSearchInput` reaches the new value meanwhile.
"""

import pytest

from whitemarket._generated import enums as wire
from whitemarket._runtime.enums import UnknownTolerantEnum
from whitemarket.models import enums as high
from whitemarket.models.deal_status import DealStatus

PAIRS = [
    (high.App, wire.SteamApp),
    (high.Color, wire.CatalogColor),
    (high.Exterior, wire.CSGOExterior),
    (high.ItemCategory, wire.CSGOCategory),
    (high.ItemSubcategory, wire.CSGOSubcategory),
    (high.Phase, wire.CSGOPhase),
    (high.Rarity, wire.CSGORarity),
    (high.StickerFilm, wire.CSGOStickerFilm),
    (high.LogicOperand, wire.LogicOperand),
    (high.OfferType, wire.MarketOfferType),
    (high.ProductSortField, wire.MarketProductSortField),
    (high.SortDirection, wire.SortType),
    (high.DeliveryType, wire.DeliveryType),
    (high.DeliveryPromise, wire.DeliveryPromise),
    (high.Currency, wire.Currency),
    (high.ProductStatus, wire.MarketProductStatus),
    (high.DealAction, wire.MarketDealActionType),
    (DealStatus, wire.MarketDealStatus),
    (high.DealCancelReason, wire.MarketDealCancelReason),
    (high.TransactionReason, wire.WalletTransactionReason),
]
KNOWN_ALL = [
    (DealStatus, wire.MarketDealStatus),
    (high.DealCancelReason, wire.MarketDealCancelReason),
    (high.TransactionReason, wire.WalletTransactionReason),
    (high.ProductStatus, wire.MarketProductStatus),
    (high.DealAction, wire.MarketDealActionType),
]


def values(enum: type[UnknownTolerantEnum]) -> set[str]:
    return {member.value for member in enum}


@pytest.mark.parametrize(
    ("mirror", "generated"), PAIRS, ids=[mirror.__name__ for mirror, _ in PAIRS]
)
def test_every_high_level_value_exists_in_the_generated_enum(
    mirror: type[UnknownTolerantEnum], generated: type[UnknownTolerantEnum]
) -> None:
    assert values(mirror)  # a mirror with no members would pass the check below
    assert values(mirror) - values(generated) == set()


@pytest.mark.parametrize(
    ("mirror", "generated"), KNOWN_ALL, ids=[mirror.__name__ for mirror, _ in KNOWN_ALL]
)
def test_deal_and_wallet_enums_know_every_schema_value(
    mirror: type[UnknownTolerantEnum], generated: type[UnknownTolerantEnum]
) -> None:
    # A value added to the schema must be added here too (and, for a status, classified), or it
    # reaches users as unknown. SPEC_SYNC 2026-11-13: QUEUED, INSTANT_EXCHANGE_FAILED and the seven
    # INSTANT_EXCHANGE* transaction reasons are mirrored, with no exception listed.
    assert values(generated) - values(mirror) == set()


def test_app_skips_the_schema_unknown_value() -> None:
    assert "UNKNOWN" not in values(high.App)
    assert "UNKNOWN" in values(wire.SteamApp)


def test_the_instant_exchange_values_of_2026_11_10_are_known() -> None:
    reasons = {r.value for r in high.TransactionReason if r.value.startswith("INSTANT_EXCHANGE")}

    assert reasons == {
        "INSTANT_EXCHANGE",
        "INSTANT_EXCHANGE_TRANSFER_IN",
        "INSTANT_EXCHANGE_TRANSFER_OUT",
        "INSTANT_EXCHANGE_REFUND_IN",
        "INSTANT_EXCHANGE_REFUND_OUT",
        "INSTANT_EXCHANGE_HOLD_RELEASE_IN",
        "INSTANT_EXCHANGE_HOLD_RELEASE_OUT",
    }
    assert not high.DealCancelReason("INSTANT_EXCHANGE_FAILED").is_unknown
    assert not DealStatus("QUEUED").is_unknown


@pytest.mark.parametrize(
    "enum",
    [
        high.TransactionReason,
        high.DealCancelReason,
        high.ProductStatus,
        high.DealAction,
        DealStatus,
    ],
    ids=lambda e: e.__name__,
)
def test_a_value_the_enum_does_not_know_decodes_to_an_unknown_member_with_the_raw_value(
    enum: type[UnknownTolerantEnum],
) -> None:
    member = enum("A_VALUE_FROM_THE_FUTURE")

    assert member.is_unknown
    assert member.value == "A_VALUE_FROM_THE_FUTURE"
    assert not next(iter(enum)).is_unknown
