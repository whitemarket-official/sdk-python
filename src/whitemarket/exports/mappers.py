"""Raw export records to row models (SDK_SPEC 3.10 rules 5 and 8).

A raw record is a mapping: from JSON (ints, `Decimal` for a float token, strings, None, lists,
dicts) or from CSV (strings and None). Every failure is a `DecodeError` with the path of the
offending value and a fixed reason; a value from the file is never put in a message.
"""

import re
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

from whitemarket.errors import DecodeError
from whitemarket.exports.rows import PriceRow, ProductRow
from whitemarket.models.enums import Currency, DeliveryPromise, DeliveryType, ItemCategory
from whitemarket.models.money import Money

Path = tuple[str | int, ...]

_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_DIGITS = re.compile(r"[0-9]+")
_MAX_INT_DIGITS = 4000  # below the interpreter limit of int(str)

_PRICE_KEYS = frozenset(
    (
        "market_hash_name",
        "price",
        "market_product_link",
        "market_product_count",
        "cheapest_asset_id",
        "cheapest_float",
        "paint_index",
        "paint_seed",
        "inspect_link",
    )
)
_PRODUCT_KEYS = frozenset(
    (
        "product_id",
        "product_category",
        "product_type",
        "product_subtype",
        "product_class_id",
        "product_instance_id",
        "product_asset_id",
        "product_float",
        "product_paint_index",
        "product_phase",
        "name_hash",
        "price",
        "currency",
        "product_paint_seed",
        "deliveryType",
        "deliveryPromise",
        "inspectLink",
    )
)
_PROMISES = {
    "10min": DeliveryPromise.MINUTES10.value,
    "1hour": DeliveryPromise.HOUR1.value,
    "12hours": DeliveryPromise.HOURS12.value,
    "24hours": DeliveryPromise.HOURS24.value,
}


def map_price_row(raw: Any, path: Path, *, text: bool = False) -> PriceRow:
    """One price row. `text`: the values come from CSV (every value is a string)."""
    row = _object(raw, path)
    return PriceRow(
        market_hash_name=_string(row, "market_hash_name", path),
        price=Money(amount=_decimal(row, "price", path), currency=Currency.USD),
        market_product_link=_string(row, "market_product_link", path),
        market_product_count=_count(row, "market_product_count", path, text=text),
        cheapest_asset_id=_id(row, "cheapest_asset_id", path),
        cheapest_float=_nullable_decimal(row, "cheapest_float", path),
        paint_index=_string(row, "paint_index", path),
        paint_seed=_string(row, "paint_seed", path),
        inspect_link=_non_empty(row, "inspect_link", path),
        extra=_extra(row, _PRICE_KEYS),
    )


def map_product_row(raw: Any, path: Path) -> ProductRow | None:
    """One product row, or None for a row whose `product_category` is present and null (rule 8)."""
    row = _object(raw, path)
    if "product_category" in row and row["product_category"] is None:
        return None
    delivery_type = _nullable_string(row, "deliveryType", path)
    delivery_promise = _nullable_string(row, "deliveryPromise", path)
    return ProductRow(
        product_id=_string(row, "product_id", path),
        market_hash_name=_string(row, "name_hash", path),
        price=Money(
            amount=_decimal(row, "price", path),
            currency=Currency(_string(row, "currency", path)),
        ),
        category=ItemCategory(_string(row, "product_category", path)),
        type=_nullable_string(row, "product_type", path),
        subtype=_nullable_string(row, "product_subtype", path),
        class_id=_id(row, "product_class_id", path),
        instance_id=_id(row, "product_instance_id", path),
        asset_id=_id(row, "product_asset_id", path),
        float=_nullable_decimal(row, "product_float", path),
        paint_index=_nullable_id(row, "product_paint_index", path),
        paint_seed=_nullable_id(row, "product_paint_seed", path),
        phase=_nullable_string(row, "product_phase", path),
        delivery_type=None if delivery_type is None else DeliveryType(delivery_type.upper()),
        delivery_promise=None
        if delivery_promise is None
        else DeliveryPromise(_PROMISES.get(delivery_promise, delivery_promise)),
        inspect_link=_non_empty(row, "inspectLink", path),
        extra=_extra(row, _PRODUCT_KEYS),
    )


def _fail(reason: str, path: Path, key: str | None = None) -> DecodeError:
    return DecodeError(reason, path if key is None else (*path, key))


def _object(raw: Any, path: Path) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise _fail("not an object", path)
    return cast("dict[str, Any]", raw)


def _string(row: Mapping[str, Any], key: str, path: Path) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise _fail("missing or not a string", path, key)
    return value


def _nullable_string(row: Mapping[str, Any], key: str, path: Path) -> str | None:
    value = row.get(key)
    if value is not None and not isinstance(value, str):
        raise _fail("not a string or null", path, key)
    return value


def _non_empty(row: Mapping[str, Any], key: str, path: Path) -> str | None:
    return _nullable_string(row, key, path) or None


def _to_decimal(text: str) -> Decimal | None:
    return Decimal(text) if _DECIMAL.fullmatch(text) else None


def _decimal(row: Mapping[str, Any], key: str, path: Path) -> Decimal:
    value = _to_decimal(_string(row, key, path))
    if value is None:
        raise _fail("not a decimal number", path, key)
    return value


def _nullable_decimal(row: Mapping[str, Any], key: str, path: Path) -> Decimal | None:
    text = _nullable_string(row, key, path)
    if text is None:
        return None
    value = _to_decimal(text)
    if value is None:
        raise _fail("not a decimal number", path, key)
    return value


def _digits(value: Any) -> str | None:
    """The digit string of a non-negative integer token or digit string; None for anything else.

    A float token (`Decimal` from the parser, no precision left) and a bool are not integers.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return str(value) if value >= 0 else None
        except ValueError:  # beyond the interpreter's integer-to-text digit limit
            return None
    if isinstance(value, str) and _DIGITS.fullmatch(value):
        return value
    return None


def _id(row: Mapping[str, Any], key: str, path: Path) -> str:
    digits = _digits(row.get(key))
    if digits is None:
        raise _fail("missing or not an integer", path, key)
    return digits


def _nullable_id(row: Mapping[str, Any], key: str, path: Path) -> str | None:
    if row.get(key) is None:
        return None
    return _id(row, key, path)


def _count(row: Mapping[str, Any], key: str, path: Path, *, text: bool) -> int:
    value = row.get(key)
    if text and isinstance(value, str):
        digits = _digits(value)
        if digits is not None and len(digits) <= _MAX_INT_DIGITS:
            return int(digits)
    elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise _fail("missing or not a non-negative integer", path, key)


def _extra(row: Mapping[str, Any], known: frozenset[str]) -> Mapping[str, Any]:
    return MappingProxyType({key: value for key, value in row.items() if key not in known})
