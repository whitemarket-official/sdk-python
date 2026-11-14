# 0004. High-level models: frozen slotted dataclasses, mappers over protocols

- Status: accepted (implementation 2026-11-13, T3.1 and T3.2)
- Date: 2026-11-13
- Port of: the model rules of `../whitemarket_sdk_php/src/Models/` (final readonly classes, one `ModelMapper`)

## Context

SDK_SPEC 4: idiomatic immutable value objects for every model the high-level API returns, mapped from generated
types in one place per model; enums with an unknown fallback; `Money` and wear values exact decimals; aware
datetimes. CLAUDE.md language rules: "high-level models are frozen dataclasses or frozen pydantic models (ADR, be
consistent)". Rules 3 (exact decimals, 64-bit ids), 5 (unknown is not an error), 11 (one mapper per model), 12 (API
names only at the boundary).

## Options

1. Frozen pydantic models, validated on construction: a second validation pass over data the generated layer
   already validated; pydantic would then be part of the public model API (`model_dump`, `model_copy`) and its
   `ValidationError` could leak where the SDK promises `DecodeError`; a model built by a user needs pydantic too.
2. Re-export the generated pydantic models: leaks schema names and shapes (`MarketListMarketListEdgesNode`,
   `float_`), one class per operation for the same listing, and no place for helpers such as
   `DealStatus.is_final()`.
3. Frozen, slotted, keyword-only standard-library dataclasses (`@dataclass(frozen=True, slots=True, kw_only=True)`)
   built by mappers. `Money` already is one.

## Decision

Option 3.

- Models: `Page[T]`, `PageRequest`, `Product`, `ProductHistory`, `InventoryItem`, `Sticker`, `StickerSuggestion(s)`,
  `Deal`, `DealState`, `BuyResult` (`whitemarket.models`). Collections are tuples (a frozen model must not hold a
  mutable list); `Page` is covariant so a page of a subtype is a page of the base. Ids that are 64-bit numbers
  (`asset_id`, `class_id`, `instance_id`) stay `str`; money and wear (`InventoryItem.float`, `Sticker.wear`) are
  `Decimal` parsed from the wire text by one function (`_runtime/decimals.py`: plain decimal text only, a malformed
  value is a `DecodeError` with the JSON path and a fixed reason that never carries the value).
- The receiver trade URL of a deal is a `Secret` and is left out of `repr()` (SDK_SPEC 3.4 rule 11).
- Enums: every enum a high-level model or filter uses is a `UnknownTolerantEnum` (value-compared `StrEnum` with an
  unknown pseudo-member). `Currency`, `DeliveryType`, `DeliveryPromise` are the generated enums themselves (same
  names as the schema, no drift). The others are written under SDK names (`Exterior`, not `CSGOExterior`) and
  mirror wire values; `tests/unit/models/test_enum_parity.py` fails when a high-level value is missing in the
  generated enum it is sent as, and for the deal and wallet enums (where a new value needs a classification) also
  when the schema has a value the high-level enum lacks. `DealStatus` carries the classification of
  WHITEMARKET_API.md 4 (`is_in_progress`, `is_exchanged`, `is_successful`, `is_failed`, `is_reversed`, `is_final`,
  plus `awaiting_trade_protection(deal)`); an unknown status belongs to no group.
- Mappers: package `whitemarket._mappers` (private, pure, no IO, shared by the async and sync clients), one function
  per model (`map_product`, `map_product_history`, `map_inventory_item`, `map_deal`, `map_archived_deal`,
  `map_deal_state`, `map_page`). Every operation has its own generated classes with the same fields, so the mappers
  take structural types (`typing.Protocol` with read-only properties) instead of class lists; a new operation needs
  no change here and mypy/pyright strict check each call site. Interface fields (`item`, `description`, `params`)
  are typed `object` and recognised at run time by the fields of the one implementation this SDK knows
  (`runtime_checkable` protocol, like the PHP `property_exists` shape check); anything else maps to `None`.
- A null edge or node is skipped in a page; a missing `page_info` means no next page. A product whose `item` is of
  an unknown type is kept with `item=None` (as PHP; only inventory pages skip such items, SDK_SPEC 3.6 rule 3).
- Input side (`_mappers/wire.py`): high-level enums and `Money` convert to generated inputs by value; a value the
  wire enum does not accept (or an unknown pseudo-member) is a `ValueError` before the request. `ProductFilter` is a
  frozen keyword-only dataclass (copy with `dataclasses.replace`), validating at construction (`Decimal` bounds, aware
  datetimes, known price currency).
- Pagination: one lazy helper (`_async/pagination.py`, sync twin generated) used by every `iterate*`; a next page
  without a new cursor is a `DecodeError`.

## Consequences

- A new model field is one dataclass field plus one mapper line; a new operation selecting `MarketProduct` needs
  nothing.
- Protocol properties are checked structurally: renaming a field in the generated layer (schema or override change)
  fails type checking at the mapper call site, not at run time.
- Users who want serialisation use `dataclasses.asdict`; there is no pydantic in the public models.
- Enum mirrors can lag the schema: unknown values are safe (rule 5) and the parity test names the lag.

## Sources

- docs/SDK_SPEC.md 3, 3.4, 4; docs/WHITEMARKET_API.md 4.
- Python `dataclasses` (frozen, slots, kw_only): https://docs.python.org/3/library/dataclasses.html
- Python `typing.Protocol`, `runtime_checkable`: https://docs.python.org/3/library/typing.html#typing.Protocol
