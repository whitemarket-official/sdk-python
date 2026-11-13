"""`PriceList`: the prices file keyed by `(market_hash_name, paint_index)` (SDK_SPEC 3.10)."""

from dataclasses import replace
from decimal import Decimal

import pytest

from support.exports import PRICE_ROW, achunked, chunked, fixture, json_body
from whitemarket.errors import DecodeError
from whitemarket.exports import ExportFormat, PriceList, PriceRow, iter_price_rows
from whitemarket.models import Money

DOPPLER = "★ Synthetic Knife | Doppler (Factory New)"


def fixture_list(name: str, fmt: ExportFormat) -> PriceList:
    return PriceList.from_chunks(chunked(fixture(name), 100), fmt)


def make_row(name: str = "A", paint_index: str = "0", price: str = "1") -> PriceRow:
    (row,) = iter_price_rows([json_body([{**PRICE_ROW, "market_hash_name": name}])])
    return replace(row, paint_index=paint_index, price=Money.usd(price))


def test_a_small_file_becomes_a_list_with_every_row() -> None:
    prices = fixture_list("prices.json", ExportFormat.JSON)

    assert len(prices) == 4
    assert [row.paint_index for row in prices] == ["282", "0", "415", "418"]


def test_json_and_csv_files_give_the_same_rows() -> None:
    from_json = fixture_list("prices.json", ExportFormat.JSON)
    from_csv = fixture_list("prices.csv", ExportFormat.CSV)

    assert list(from_csv) == [replace(row, extra={}) for row in from_json]


def test_doppler_phases_are_told_apart_by_the_paint_index() -> None:
    prices = fixture_list("prices.json", ExportFormat.JSON)

    phase_2 = prices.get(DOPPLER, "415")
    phase_4 = prices.get(DOPPLER, "418")

    assert phase_2 is not None
    assert phase_4 is not None
    assert phase_2.price.amount == Decimal("950.000")
    assert phase_4.price.amount == Decimal("1800.000")


def test_all_phases_returns_every_row_of_the_name_in_file_order() -> None:
    prices = fixture_list("prices.json", ExportFormat.JSON)

    phases = prices.all_phases(DOPPLER)

    assert [row.paint_index for row in phases] == ["415", "418"]
    assert isinstance(phases, tuple)


@pytest.mark.parametrize(
    ("name", "paint_index"),
    [
        pytest.param(
            "Sticker | Synthetic Crown (Foil)", "1", id="a known name, another paint index"
        ),
        pytest.param("Nothing", "0", id="an unknown name"),
        pytest.param("", "0", id="an empty name"),
        pytest.param("sticker | synthetic crown (foil)", "0", id="another case"),
    ],
)
def test_get_misses_return_none(name: str, paint_index: str) -> None:
    assert fixture_list("prices.json", ExportFormat.JSON).get(name, paint_index) is None


def test_the_paint_index_defaults_to_zero_for_items_without_one() -> None:
    prices = fixture_list("prices.json", ExportFormat.JSON)

    row = prices.get("Sticker | Synthetic Crown (Foil)")

    assert row is not None
    assert row.paint_index == "0"
    assert (
        prices.get(DOPPLER) is None
    )  # a Doppler has no paint index "0": no arbitrary phase is picked


def test_all_phases_of_an_unknown_name_is_empty() -> None:
    assert PriceList([]).all_phases("x") == ()


def test_a_repeated_pair_keeps_the_first_row_for_get_and_every_row_for_all_phases() -> None:
    first, second = make_row("A", "0", "1"), make_row("A", "0", "2")
    prices = PriceList([first, second])

    assert prices.get("A") is first
    assert prices.all_phases("A") == (first, second)
    assert len(prices) == 2


def test_the_key_is_the_pair_not_a_joined_string() -> None:
    a, b = make_row("A", "1"), make_row("A1", "")
    prices = PriceList([a, b])

    assert prices.get("A", "1") is a
    assert prices.get("A1", "") is b
    assert prices.get("A", "") is None
    assert prices.get("A1", "1") is None


def test_an_empty_list() -> None:
    prices = PriceList([])

    assert len(prices) == 0
    assert list(prices) == []
    assert prices.get("A") is None


def test_iteration_can_be_repeated() -> None:
    prices = PriceList([make_row("A"), make_row("B")])

    assert list(prices) == list(prices)
    assert len(list(prices)) == 2


def test_a_bad_row_in_the_file_fails_the_whole_list_with_its_path() -> None:
    body = json_body([PRICE_ROW, {**PRICE_ROW, "price": 7}])

    with pytest.raises(DecodeError) as error:
        PriceList.from_chunks(chunked(body, 100))

    assert error.value.path == ("prices", 1, "price")


async def test_the_async_loader_gives_the_same_list() -> None:
    prices = await PriceList.afrom_chunks(achunked(fixture("prices.json"), 50))

    assert list(prices) == list(fixture_list("prices.json", ExportFormat.JSON))
