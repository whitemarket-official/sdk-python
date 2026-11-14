"""`InventoryFilter`: the high-level builder over `PersonInventorySearchInput` (SDK_SPEC 3.6)."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import Any

import pytest

from whitemarket._mappers.search import inventory_search_input
from whitemarket._runtime.json_codec import to_plain
from whitemarket.inventory import InventoryFilter
from whitemarket.models import Exterior, Rarity


def wire(flt: InventoryFilter) -> Any:
    return to_plain(inventory_search_input(flt))


def test_an_empty_filter_sends_nothing() -> None:
    assert wire(InventoryFilter()) == {}


def test_lists_given_are_kept_as_tuples_and_the_filter_is_immutable() -> None:
    flt = InventoryFilter(rarities=[Rarity.RARE], exteriors=[Exterior.WELL_WORN])

    assert flt.rarities == (Rarity.RARE,)
    with pytest.raises(FrozenInstanceError):
        flt.name = "x"
    assert wire(replace(flt, stat_trak=True))["csgoStatTrak"] is True


def test_wear_bounds_are_sent_as_plain_decimal_text_without_an_exponent() -> None:
    flt = InventoryFilter(float_from=Decimal("1E-7"), float_to=Decimal("0.0700"))

    assert wire(flt) == {"csgoFloatFrom": "0.0000001", "csgoFloatTo": "0.0700"}


@pytest.mark.parametrize("field", ["float_from", "float_to", "fade_from", "fade_to"])
def test_a_float_where_a_decimal_is_required_is_refused(field: str) -> None:
    with pytest.raises(TypeError, match=field):
        InventoryFilter(**{field: 0.07})


def test_an_enum_value_the_schema_does_not_accept_is_refused_when_encoded() -> None:
    flt = InventoryFilter(rarities=[Rarity("TELEPORT")])

    with pytest.raises(ValueError, match="TELEPORT"):
        inventory_search_input(flt)
