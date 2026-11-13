"""`Page` and `PageRequest`: one page of a paginated list (SDK_SPEC 3)."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class Page(Generic[T_co]):
    """One page of a list. Pass `end_cursor` as `after` to the next call while `has_next_page` is
    true, or use the matching `iterate*` method, which does that lazily.

    `total_count` is the server's count of all matching items, when it reports one. Iterating a
    page yields its items.
    """

    items: tuple[T_co, ...]
    end_cursor: str | None
    has_next_page: bool
    total_count: int | None

    def __iter__(self) -> Iterator[T_co]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    """Which page a `search`/`list` call reads: how many items and where to continue.

    Both parts are optional; the server's defaults apply to what is `None`. `after` is the
    `end_cursor` of the previous `Page`.
    """

    first: int | None = None
    after: str | None = None
