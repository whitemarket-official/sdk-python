"""The pure half of a `*_many` call: matching the rows of one answer to the items sent (SDK_SPEC 3.5
rules 3, 4 and 7). The chunk loop that sends the requests is in `_async/selling.py`."""

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from whitemarket._generated.input_types import MarketProductEditInput, MarketProductNewInput
from whitemarket._mappers.products import BatchIdentity, batch_identity, map_batch_product
from whitemarket.errors import DecodeError
from whitemarket.selling.results import BatchItemResult, BatchOutcome

_T = TypeVar("_T")

SameItem = Callable[[_T, BatchIdentity], bool]


class BatchRow(Protocol):
    """A `MarketProductResult` of a `*_multiple` answer."""

    @property
    def index(self) -> int: ...
    @property
    def is_created(self) -> bool: ...
    @property
    def error_category(self) -> str | None: ...
    @property
    def error_message(self) -> str | None: ...
    @property
    def product(self) -> object: ...


def with_outcome(
    results: Sequence[BatchItemResult], offset: int, size: int, outcome: BatchOutcome
) -> list[BatchItemResult]:
    """`results` with the items `offset .. offset + size - 1` replaced by a bare `outcome`."""
    replaced = list(results)
    for index in range(offset, offset + size):
        replaced[index] = BatchItemResult(index=index, outcome=outcome)
    return replaced


def match_rows(
    rows: Sequence[BatchRow],
    chunk: Sequence[_T],
    offset: int,
    field: str,
    same_item: SameItem[_T],
) -> list[BatchItemResult]:
    """The results of one chunk: each row is matched to its item by `index`, read as the 0-based
    position within the chunk (SDK_SPEC 3.5 rule 4). An item without a row is `UNKNOWN`.

    A row whose product carries the identity of an item is also checked against the item requested
    at that position (`same_item`; a row without a product, or a product without the identity,
    passes): `index` is unconfirmed, and a server counting from 1 that answers only some rows
    would otherwise attach rows to the wrong items. The identity is read from the raw row before
    any money or wear is decoded, so a product that cannot be decoded is still checked.

    Raises `DecodeError` when an `index` is outside the chunk or repeated, or a row's product is
    not the requested item: the mutation already ran, so the caller marks the chunk `UNKNOWN`.
    """
    by_position = _by_position(rows, len(chunk), field)
    results: list[BatchItemResult] = []
    for position, item in enumerate(chunk):
        row = by_position.get(position)
        index = offset + position
        if row is None:
            results.append(BatchItemResult(index=index, outcome=BatchOutcome.UNKNOWN))
            continue
        path = (field, position)
        identity = batch_identity(row.product)
        if identity is not None and not same_item(item, identity):
            raise DecodeError(
                "the product is not the item requested at this position", (*path, "product", "id")
            )
        product = map_batch_product(row.product, (*path, "product"))
        results.append(
            BatchItemResult(
                index=index,
                outcome=BatchOutcome.SUCCEEDED if row.is_created else BatchOutcome.FAILED,
                product=product,
                error_category=row.error_category,
                error_message=row.error_message,
            )
        )
    return results


def _by_position(rows: Sequence[BatchRow], size: int, field: str) -> dict[int, BatchRow]:
    by_position: dict[int, BatchRow] = {}
    for i, row in enumerate(rows):
        if not 0 <= row.index < size:
            raise DecodeError(f"{row.index} is outside the {size} items sent", (field, i, "index"))
        if row.index in by_position:
            raise DecodeError(f"{row.index} is reported twice", (field, i, "index"))
        by_position[row.index] = row
    return by_position


def same_uuid(requested: str | None, returned: str) -> bool:
    return requested is not None and requested.lower() == returned.lower()


def same_listed_item(requested: MarketProductNewInput, product: BatchIdentity) -> bool:
    if product.archived or product.asset_id is None or product.item_id is None:
        return True
    if requested.asset_id is not None:
        return product.asset_id == requested.asset_id
    return same_uuid(requested.inventory_id, product.item_id)


def same_repriced_listing(requested: MarketProductEditInput, product: BatchIdentity) -> bool:
    if product.archived:
        return True
    if requested.product_id is not None:
        return same_uuid(requested.product_id, product.listing_id)
    return product.asset_id is None or product.asset_id == requested.asset_id


def same_removed_listing(requested: str, product: BatchIdentity) -> bool:
    return not product.archived or same_uuid(requested, product.listing_id)
