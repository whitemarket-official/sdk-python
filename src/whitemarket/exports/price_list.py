"""`PriceList`: the prices file in memory, keyed by `(market_hash_name, paint_index)` (SDK_SPEC
3.10)."""

from collections.abc import Iterable, Iterator
from typing import Final

from whitemarket.exports.rows import PriceRow

_NOT_APPLICABLE: Final = "0"


class PriceList:
    """The rows of a prices file with lookups.

    The record key is the pair `(market_hash_name, paint_index)`, never the name alone: Doppler and
    Gamma Doppler phases share a name hash and differ by `paint_index` (WHITEMARKET_API.md 8). When
    the file repeats a pair, the first row wins `get`; `all_phases` and iteration keep every row,
    in file order.
    """

    __slots__ = ("_by_key", "_by_name", "_rows")

    def __init__(self, rows: Iterable[PriceRow]) -> None:
        self._rows: tuple[PriceRow, ...] = tuple(rows)
        self._by_key: dict[tuple[str, str], PriceRow] = {}
        by_name: dict[str, list[PriceRow]] = {}
        for row in self._rows:
            self._by_key.setdefault((row.market_hash_name, row.paint_index), row)
            by_name.setdefault(row.market_hash_name, []).append(row)
        self._by_name: dict[str, tuple[PriceRow, ...]] = {
            name: tuple(group) for name, group in by_name.items()
        }

    def get(self, market_hash_name: str, paint_index: str = _NOT_APPLICABLE) -> PriceRow | None:
        """The row of one item and paint index (`"0"` for items without one), or None."""
        return self._by_key.get((market_hash_name, paint_index))

    def all_phases(self, market_hash_name: str) -> tuple[PriceRow, ...]:
        """Every row of an item name, one per paint index (the Doppler phases); empty if unknown."""
        return self._by_name.get(market_hash_name, ())

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[PriceRow]:
        return iter(self._rows)
