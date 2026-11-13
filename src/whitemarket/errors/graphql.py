"""A 200 answer that carries GraphQL errors (SDK_SPEC 1.5)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from whitemarket.errors.base import WhiteMarketError
from whitemarket.errors.category import ErrorCategory


@dataclass(frozen=True, slots=True)
class SourceLocation:
    line: int
    column: int


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _items(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


@dataclass(frozen=True, slots=True)
class GraphQLErrorEntry:
    """One element of the `errors` array. Branch on `category`, never on `message`."""

    message: str
    path: tuple[str | int, ...] = ()
    locations: tuple[SourceLocation, ...] = ()
    category: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=lambda: {})

    @classmethod
    def from_payload(cls, payload: object) -> "GraphQLErrorEntry":
        """Tolerant parse of one JSON error: a missing or oddly typed part becomes empty."""
        raw = _mapping(payload)
        message = raw.get("message")
        extensions = _mapping(raw.get("extensions"))
        category = extensions.get("category")
        locations: list[SourceLocation] = []
        for item in _items(raw.get("locations")):
            location = _mapping(item)
            line, column = location.get("line"), location.get("column")
            if isinstance(line, int) and isinstance(column, int):
                locations.append(SourceLocation(line, column))
        return cls(
            message=message if isinstance(message, str) else "",
            path=tuple(p for p in _items(raw.get("path")) if isinstance(p, str | int)),
            locations=tuple(locations),
            category=category if isinstance(category, str) else None,
            extensions=extensions,
        )


class GraphQLError(WhiteMarketError):
    """A 200 answer with `errors`; `partial_data` is the `data` that came with them, if any.

    The exception text, every entry's `message` and `extensions`, and `partial_data` are raw
    server data: not redacted (an accepted limitation, docs/DEVIATIONS.md, as in the PHP SDK), so
    do not log them blindly. The one exception: the root fields that carry a credential
    (`auth_token`, `auth_steam_jwt`, `profile_steam_proxy_get`) never reach `partial_data`.
    """

    def __init__(
        self,
        errors: Sequence[GraphQLErrorEntry],
        partial_data: Mapping[str, Any] | None = None,
    ) -> None:
        self.errors: tuple[GraphQLErrorEntry, ...] = tuple(errors)
        self.partial_data = partial_data
        # The server's own message, verbatim, as in the PHP SDK: callers act on it.
        super().__init__(self.errors[0].message if self.errors else "GraphQL error")

    @classmethod
    def from_payload(
        cls, errors: Sequence[object], partial_data: Mapping[str, Any] | None = None
    ) -> "GraphQLError":
        """Build the right class for a raw `errors` array.

        `NotFoundError` only when EVERY error is a not-found: a mixed answer is a plain
        `GraphQLError`, because the spec does not say which error of several decides
        (docs/DEVIATIONS.md).
        """
        entries = [GraphQLErrorEntry.from_payload(e) for e in errors]
        if entries and all(ErrorCategory.is_not_found(e.category) for e in entries):
            return NotFoundError(entries, partial_data)
        return cls(entries, partial_data)

    def has_category(self, category: str) -> bool:
        """True if any error carries exactly this category."""
        return any(e.category == category for e in self.errors)


class NotFoundError(GraphQLError):
    """Every error's category ends with `.not_found`; raised at once, never retried (2026-10-31)."""
