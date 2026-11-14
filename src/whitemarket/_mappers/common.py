"""Pieces shared by the model mappers: paths, money, enums, pages."""

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

from whitemarket._runtime.decimals import parse_decimal
from whitemarket._runtime.decode import DecodePath
from whitemarket._runtime.enums import UnknownTolerantEnum
from whitemarket._runtime.secret import Secret
from whitemarket.models.enums import Currency
from whitemarket.models.money import Money
from whitemarket.models.page import Page

Path = DecodePath

_E = TypeVar("_E", bound=UnknownTolerantEnum)
_N = TypeVar("_N")
_R = TypeVar("_R")
_T_co = TypeVar("_T_co", covariant=True)


class MoneySource(Protocol):
    @property
    def currency(self) -> Currency: ...
    @property
    def value(self) -> str: ...


class PageInfoSource(Protocol):
    @property
    def end_cursor(self) -> str | None: ...
    @property
    def has_next_page(self) -> bool: ...


class EdgeSource(Protocol[_T_co]):
    @property
    def node(self) -> _T_co | None: ...


class ConnectionSource(Protocol[_T_co]):
    @property
    def edges(self) -> Sequence[EdgeSource[_T_co] | None] | None: ...
    @property
    def page_info(self) -> PageInfoSource | None: ...
    @property
    def total_count(self) -> int | None: ...


def money(source: MoneySource, path: Path) -> Money:
    """`Money` from a generated money fragment; a malformed amount is a `DecodeError` at `path`."""
    return Money(amount=parse_decimal(source.value, (*path, "value")), currency=source.currency)


def optional_money(source: MoneySource | None, path: Path) -> Money | None:
    return None if source is None else money(source, path)


def convert_enum(target: type[_E], wire: str) -> _E:
    """The high-level enum for the value of a generated enum member; unknown stays unknown."""
    return target(str(wire))


def optional_secret(value: str | None) -> Secret | None:
    """A secret for a value; `None` for null and for an empty value (no secret is set)."""
    return Secret(value) if value else None


def optional_enum(target: type[_E], wire: str | None) -> _E | None:
    return None if wire is None else convert_enum(target, wire)


def map_list(rows: Sequence[_N], map_row: Callable[[_N, Path], _R], path: Path) -> list[_R]:
    """Every row of a list answer mapped; a failing row is reported at `(*path, row index)`."""
    return [map_row(row, (*path, index)) for index, row in enumerate(rows)]


def map_page(
    connection: ConnectionSource[_N], map_node: Callable[[_N, Path], _R | None], path: Path
) -> Page[_R]:
    """A page of a connection. A null edge, a null node and a node `map_node` turns into None
    (a type this SDK does not know) carry no item and are skipped; a missing `page_info` means
    there is no next page (the schema allows both)."""
    items: list[_R] = []
    for index, edge in enumerate(connection.edges or ()):
        if edge is None or edge.node is None:
            continue
        item = map_node(edge.node, (*path, "edges", index, "node"))
        if item is not None:
            items.append(item)
    info = connection.page_info
    return Page(
        items=tuple(items),
        end_cursor=None if info is None else info.end_cursor,
        has_next_page=False if info is None else info.has_next_page,
        total_count=connection.total_count,
    )
