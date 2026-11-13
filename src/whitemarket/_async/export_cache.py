"""Where the validators of conditional export downloads are kept (SDK_SPEC 3.10 rule 3)."""

from typing import Protocol

from whitemarket.exports.conditional import ExportValidators


class AsyncExportCache(Protocol):
    """Keeps the `ETag` and `Last-Modified` of an export file, by its URL; never the body.

    Workers that share a cache share the "already seen" state. A cache that fails is not an error of
    the export: the request then goes out without validators.
    """

    async def get(self, url: str) -> ExportValidators | None: ...

    async def set(self, url: str, validators: ExportValidators) -> None: ...


class AsyncInMemoryExportCache:
    """The simple cache: a dict in this object."""

    def __init__(self) -> None:
        self._entries: dict[str, ExportValidators] = {}

    async def get(self, url: str) -> ExportValidators | None:
        return self._entries.get(url)

    async def set(self, url: str, validators: ExportValidators) -> None:
        self._entries[url] = validators
