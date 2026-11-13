"""Price and product rows from JSON (SDK_SPEC 3.10 rules 5 and 8)."""

import json
from decimal import Decimal
from typing import Any

import pytest

from support.exports import PRICE_ROW, PRODUCT_ROW, chunked, fixture, json_body
from whitemarket.errors import DecodeError
from whitemarket.exports import (
    PriceRow,
    ProductRow,
    iter_price_rows,
    iter_product_rows,
)
from whitemarket.models import Currency, DeliveryPromise, DeliveryType, ItemCategory, Money


def price_rows(rows: list[Any]) -> list[PriceRow]:
    return list(iter_price_rows(chunked(json_body(rows), 64)))


def product_rows(rows: list[Any]) -> list[ProductRow]:
    return list(iter_product_rows(chunked(json_body(rows), 64)))


def with_(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**base, **changes}


def without(base: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in base.items() if k != key}


def raw_body(row: dict[str, Any], **tokens: str) -> bytes:
    """A one-row body where some values are raw JSON text (float tokens, huge numbers)."""
    parts = [f"{json.dumps(k)}:{tokens.get(k, json.dumps(v))}" for k, v in row.items()]
    return ("[{" + ",".join(parts) + "}]").encode()


# --- prices ------------------------------------------------------------


def test_a_price_row_maps_every_field() -> None:
    (row,) = price_rows([PRICE_ROW])

    assert row == PriceRow(
        market_hash_name="AK-47 | Synthetic Redline (Field-Tested)",
        price=Money(amount=Decimal("7.060"), currency=Currency.USD),
        market_product_link="https://white.market/item?appId=730&nameHash=x",
        market_product_count=12,
        cheapest_asset_id="9007199254740993",
        cheapest_float=Decimal("0.2517"),
        paint_index="282",
        paint_seed="661",
        inspect_link="steam://synthetic",
    )
    assert str(row.price) == "7.060 USD"
    assert row.extra == {}


def test_the_prices_fixture_keeps_exact_ids_nulls_and_extras() -> None:
    rows = list(iter_price_rows(chunked(fixture("prices.json"), 4096)))

    assert [row.cheapest_asset_id for row in rows] == [
        "9007199254740993",  # 2**53 + 1
        "18446744073709551615",  # 2**64 - 1
        "30000000000000001",
        "30000000000000002",
    ]
    assert [row.cheapest_float for row in rows] == [
        Decimal("0.2517"),
        None,
        Decimal("0.0123"),
        None,
    ]
    assert [row.inspect_link for row in rows] == [
        rows[0].inspect_link,
        None,
        "steam://synthetic-415",
        "steam://synthetic-418",
    ]
    assert rows[1].extra == {"new_field": {"nested": [1, 2]}}
    assert {row.paint_index for row in rows[2:]} == {"415", "418"}  # Doppler phases, one name


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        pytest.param({"market_hash_name": None}, "market_hash_name", id="name null"),
        pytest.param({"market_hash_name": 5}, "market_hash_name", id="name a number"),
        pytest.param({"price": 7.06}, "price", id="price a JSON number"),
        pytest.param({"price": None}, "price", id="price null"),
        pytest.param({"price": ""}, "price", id="price empty"),
        pytest.param({"price": "abc"}, "price", id="price text"),
        pytest.param({"price": "1e5"}, "price", id="price exponent"),
        pytest.param({"price": "1."}, "price", id="price no fraction digits"),
        pytest.param({"price": ".5"}, "price", id="price no integer digits"),
        pytest.param({"price": " 1"}, "price", id="price leading space"),
        pytest.param({"price": "1\n"}, "price", id="price trailing line feed"),
        pytest.param({"price": "NaN"}, "price", id="price NaN"),
        pytest.param({"price": "١٢"}, "price", id="price non-ASCII digits"),
        pytest.param({"market_product_link": None}, "market_product_link", id="link null"),
        pytest.param({"market_product_count": -1}, "market_product_count", id="count negative"),
        pytest.param({"market_product_count": True}, "market_product_count", id="count bool"),
        pytest.param(
            {"market_product_count": "12"}, "market_product_count", id="count a string in JSON"
        ),
        pytest.param({"market_product_count": None}, "market_product_count", id="count null"),
        pytest.param({"cheapest_asset_id": -1}, "cheapest_asset_id", id="asset id negative"),
        pytest.param({"cheapest_asset_id": True}, "cheapest_asset_id", id="asset id bool"),
        pytest.param({"cheapest_asset_id": "12a"}, "cheapest_asset_id", id="asset id not digits"),
        pytest.param({"cheapest_asset_id": ""}, "cheapest_asset_id", id="asset id empty"),
        pytest.param({"cheapest_asset_id": None}, "cheapest_asset_id", id="asset id null"),
        pytest.param({"cheapest_float": 0.25}, "cheapest_float", id="float a JSON number"),
        pytest.param({"cheapest_float": "x"}, "cheapest_float", id="float text"),
        pytest.param({"paint_index": 282}, "paint_index", id="paint index a number"),
        pytest.param({"paint_index": None}, "paint_index", id="paint index null"),
        pytest.param({"paint_seed": None}, "paint_seed", id="paint seed null"),
        pytest.param({"inspect_link": 5}, "inspect_link", id="inspect link a number"),
    ],
)
def test_a_bad_price_field_fails_at_its_path(changes: dict[str, Any], path: str) -> None:
    body = json_body([PRICE_ROW, with_(PRICE_ROW, **changes)])

    with pytest.raises(DecodeError) as error:
        list(iter_price_rows(chunked(body, 100)))

    assert error.value.path == ("prices", 1, path)
    assert str(error.value).startswith(f"prices.1.{path}")


@pytest.mark.parametrize("key", sorted(PRICE_ROW.keys() - {"cheapest_float", "inspect_link"}))
def test_a_missing_required_price_key_fails(key: str) -> None:
    with pytest.raises(DecodeError) as error:
        price_rows([without(PRICE_ROW, key)])

    assert error.value.path == ("prices", 0, key)


@pytest.mark.parametrize("key", ["cheapest_float", "inspect_link"])
def test_a_missing_nullable_price_key_is_none(key: str) -> None:
    (row,) = price_rows([without(PRICE_ROW, key)])

    assert getattr(row, key) is None


@pytest.mark.parametrize(
    ("token", "key"),
    [
        pytest.param("1.0", "cheapest_asset_id", id="a float token"),
        pytest.param("1e3", "cheapest_asset_id", id="an exponent token"),
        pytest.param("9007199254740993.0", "cheapest_asset_id", id="a float token beyond 2^53"),
    ],
)
def test_a_float_token_in_an_id_field_is_a_decode_error(token: str, key: str) -> None:
    with pytest.raises(DecodeError) as error:
        list(iter_price_rows([raw_body(PRICE_ROW, **{key: token})]))

    assert error.value.path == ("prices", 0, key)


def test_a_digit_string_id_is_kept_as_it_is() -> None:
    (row,) = price_rows([with_(PRICE_ROW, cheapest_asset_id="18446744073709551616")])

    assert row.cheapest_asset_id == "18446744073709551616"


def test_an_id_beyond_the_integer_text_limit_is_a_decode_error_not_a_crash() -> None:
    body = raw_body(PRICE_ROW, cheapest_asset_id="9" * 5000)

    with pytest.raises(DecodeError):
        list(iter_price_rows([body]))


def test_unknown_keys_are_kept_raw_in_extra() -> None:
    row = price_rows([with_(PRICE_ROW, color="red", nested={"a": [1, 2.5]}, nothing=None)])[0]

    assert row.extra == {"color": "red", "nested": {"a": [1, Decimal("2.5")]}, "nothing": None}


def test_extra_is_read_only() -> None:
    row = price_rows([with_(PRICE_ROW, color="red")])[0]

    with pytest.raises(TypeError):
        row.extra["color"] = "blue"


@pytest.mark.parametrize("value", ["", None])
def test_an_empty_or_null_inspect_link_is_none(value: str | None) -> None:
    assert price_rows([with_(PRICE_ROW, inspect_link=value)])[0].inspect_link is None


def test_a_row_that_is_not_an_object_fails_at_its_index() -> None:
    with pytest.raises(DecodeError) as error:
        price_rows([PRICE_ROW, ["x"]])

    assert error.value.path == ("prices", 1)


def test_the_rows_before_a_bad_row_are_delivered_first() -> None:
    rows: list[PriceRow] = []
    iterator = iter_price_rows(
        chunked(json_body([PRICE_ROW, PRICE_ROW, with_(PRICE_ROW, price=1)]), 50)
    )

    with pytest.raises(DecodeError) as error:
        rows.extend(iterator)

    assert len(rows) == 2
    assert error.value.path == ("prices", 2, "price")


def test_a_value_from_the_file_is_never_put_in_a_message() -> None:
    body = json_body([with_(PRICE_ROW, price="SECRET-TEXT")])

    with pytest.raises(DecodeError) as error:
        list(iter_price_rows([body]))

    assert "SECRET-TEXT" not in str(error.value)


# --- products ------------------------------------------------------------


def test_a_product_row_maps_every_field() -> None:
    (row,) = product_rows([PRODUCT_ROW])

    assert row == ProductRow(
        product_id="00000000-0000-4000-8000-000000000001",
        market_hash_name="AK-47 | Synthetic Redline (Field-Tested)",
        price=Money(amount=Decimal("7.060"), currency=Currency.USD),
        category=ItemCategory.RIFLES,
        type="Rifle",
        subtype="AK-47",
        class_id="310776560",
        instance_id="188530139",
        asset_id="9007199254740993",
        float=Decimal("0.2517"),
        paint_index="282",
        paint_seed="661",
        phase=None,
        delivery_type=DeliveryType.AUTO,
        delivery_promise=DeliveryPromise.MINUTES10,
        inspect_link="steam://synthetic",
    )


def test_the_products_fixture_skips_the_null_category_row_but_keeps_file_indexes() -> None:
    rows = list(iter_product_rows(chunked(fixture("products.json"), 4096)))

    assert [row.product_id[-1] for row in rows] == ["1", "2", "4", "5"]  # the row "3" is skipped
    assert rows[1].class_id == "18446744073709551615"
    assert rows[1].asset_id == "18446744073709551614"
    assert rows[1].paint_index is None
    assert rows[1].inspect_link is None
    assert rows[1].extra == {"new_field": {"nested": [1, 2]}}
    assert rows[2].paint_index == "415"
    assert rows[2].phase == "Phase 2"
    assert rows[2].delivery_type is DeliveryType.SEMI


def test_a_null_category_row_is_skipped_and_still_counts_for_the_index() -> None:
    null_category = with_(PRODUCT_ROW, product_category=None, product_float=None)
    body = json_body([PRODUCT_ROW, null_category, null_category, with_(PRODUCT_ROW, price=5)])

    iterator = iter_product_rows(chunked(body, 64))
    assert next(iterator).product_id == PRODUCT_ROW["product_id"]
    with pytest.raises(DecodeError) as error:
        next(iterator)

    assert error.value.path == ("products", 3, "price")


def test_a_row_without_the_category_key_is_not_a_null_category_row() -> None:
    with pytest.raises(DecodeError) as error:
        product_rows([without(PRODUCT_ROW, "product_category")])

    assert error.value.path == ("products", 0, "product_category")


def test_an_unknown_category_and_currency_are_the_unknown_variant() -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, product_category="OTHERS", currency="EUR")])

    assert row.category.is_unknown
    assert row.category.value == "OTHERS"
    assert row.price.currency.is_unknown
    assert row.price.currency.value == "EUR"
    assert row.category != ItemCategory.OTHER


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        pytest.param("auto", DeliveryType.AUTO, id="auto"),
        pytest.param("semi", DeliveryType.SEMI, id="semi"),
        pytest.param("manual", DeliveryType.MANUAL, id="manual"),
        pytest.param("SEMI", DeliveryType.SEMI, id="already upper case"),
        pytest.param("Manual", DeliveryType.MANUAL, id="mixed case"),
        pytest.param(None, None, id="null"),
    ],
)
def test_the_delivery_type_is_compared_upper_cased(
    wire: str | None, expected: DeliveryType | None
) -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, deliveryType=wire)])

    assert row.delivery_type == expected
    assert (row.delivery_type is None) == (expected is None)


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        pytest.param("10min", DeliveryPromise.MINUTES10, id="10min"),
        pytest.param("1hour", DeliveryPromise.HOUR1, id="1hour"),
        pytest.param("12hours", DeliveryPromise.HOURS12, id="12hours"),
        pytest.param("24hours", DeliveryPromise.HOURS24, id="24hours"),
        pytest.param(None, None, id="null"),
    ],
)
def test_the_delivery_promise_maps_the_wire_names(
    wire: str | None, expected: DeliveryPromise | None
) -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, deliveryPromise=wire)])

    assert row.delivery_promise == expected
    assert (row.delivery_promise is None) == (expected is None)


@pytest.mark.parametrize(
    ("key", "wire", "raw"),
    [
        pytest.param("deliveryType", "teleport", "TELEPORT", id="unknown type, upper-cased"),
        pytest.param("deliveryPromise", "1week", "1week", id="unknown promise, raw"),
    ],
)
def test_an_unknown_delivery_value_is_the_unknown_variant(key: str, wire: str, raw: str) -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, **{key: wire})])

    value = row.delivery_type if key == "deliveryType" else row.delivery_promise
    assert value is not None
    assert value.value == raw
    assert value.is_unknown


def test_missing_delivery_keys_are_none() -> None:
    body = {k: v for k, v in PRODUCT_ROW.items() if k not in ("deliveryType", "deliveryPromise")}

    (row,) = product_rows([body])

    assert row.delivery_type is None
    assert row.delivery_promise is None


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        pytest.param({"product_id": None}, "product_id", id="product id null"),
        pytest.param({"name_hash": 1}, "name_hash", id="name hash a number"),
        pytest.param({"price": 7}, "price", id="price a number"),
        pytest.param({"price": "7,06"}, "price", id="price with a comma"),
        pytest.param({"currency": None}, "currency", id="currency null"),
        pytest.param({"product_category": 5}, "product_category", id="category a number"),
        pytest.param({"product_type": 5}, "product_type", id="type a number"),
        pytest.param({"product_subtype": []}, "product_subtype", id="subtype a list"),
        pytest.param({"product_class_id": None}, "product_class_id", id="class id null"),
        pytest.param({"product_instance_id": "x"}, "product_instance_id", id="instance id text"),
        pytest.param({"product_asset_id": -5}, "product_asset_id", id="asset id negative"),
        pytest.param({"product_float": 0.25}, "product_float", id="float a JSON number"),
        pytest.param({"product_float": "0,25"}, "product_float", id="float with a comma"),
        pytest.param({"product_paint_index": "x"}, "product_paint_index", id="paint index text"),
        pytest.param({"product_paint_index": False}, "product_paint_index", id="paint index bool"),
        pytest.param({"product_paint_seed": -1}, "product_paint_seed", id="paint seed negative"),
        pytest.param({"product_phase": 2}, "product_phase", id="phase a number"),
        pytest.param({"deliveryType": 1}, "deliveryType", id="delivery type a number"),
        pytest.param({"deliveryPromise": 1}, "deliveryPromise", id="delivery promise a number"),
        pytest.param({"inspectLink": 1}, "inspectLink", id="inspect link a number"),
    ],
)
def test_a_bad_product_field_fails_at_its_path(changes: dict[str, Any], path: str) -> None:
    with pytest.raises(DecodeError) as error:
        product_rows([PRODUCT_ROW, with_(PRODUCT_ROW, **changes)])

    assert error.value.path == ("products", 1, path)


@pytest.mark.parametrize(
    "key",
    [
        "product_class_id",
        "product_instance_id",
        "product_asset_id",
        "product_paint_index",
        "product_paint_seed",
    ],
)
@pytest.mark.parametrize("token", ["1.0", "2.5e1"], ids=["a float token", "an exponent token"])
def test_a_float_token_in_an_id_or_paint_field_is_a_decode_error(key: str, token: str) -> None:
    with pytest.raises(DecodeError) as error:
        list(iter_product_rows([raw_body(PRODUCT_ROW, **{key: token})]))

    assert error.value.path == ("products", 0, key)


@pytest.mark.parametrize(
    ("key", "attribute"),
    [
        pytest.param("product_paint_index", "paint_index", id="paint index"),
        pytest.param("product_paint_seed", "paint_seed", id="paint seed"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(0, "0", id="zero"),
        pytest.param(418, "418", id="a number becomes a string"),
        pytest.param("418", "418", id="a digit string stays"),
        pytest.param(None, None, id="null"),
        pytest.param(2**64, "18446744073709551616", id="beyond 64 bits"),
    ],
)
def test_paint_index_and_seed_are_strings_or_none(
    key: str, attribute: str, value: Any, expected: str | None
) -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, **{key: value})])

    assert getattr(row, attribute) == expected


def test_doppler_rows_sharing_a_name_keep_their_own_paint_index() -> None:
    rows = product_rows(
        [with_(PRODUCT_ROW, product_paint_index=415), with_(PRODUCT_ROW, product_paint_index=418)]
    )

    assert [row.paint_index for row in rows] == ["415", "418"]
    assert rows[0].market_hash_name == rows[1].market_hash_name


def test_wear_and_price_are_exact_decimals_never_floats() -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, product_float="0.07000000000000000001", price="0.1")])

    assert row.float == Decimal("0.07000000000000000001")
    assert row.price.amount + Decimal("0.2") == Decimal("0.3")
    assert isinstance(row.float, Decimal)


def test_unknown_product_keys_go_to_extra() -> None:
    (row,) = product_rows([with_(PRODUCT_ROW, product_stickers=[{"slot": 1}], product_id="x")])

    assert row.extra == {"product_stickers": [{"slot": 1}]}
