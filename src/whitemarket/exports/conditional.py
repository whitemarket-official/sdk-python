"""Conditional export downloads: what a cache keeps and what a 304 answers (SDK_SPEC 3.10 r. 3)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportValidators:
    """The `ETag` and `Last-Modified` of one export file, as the server sent them.

    The cache keeps these two values, never the body. Either may be `None` (the server did not
    send it).
    """

    etag: str | None = None
    last_modified: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.etag is None and self.last_modified is None


@dataclass(frozen=True, slots=True)
class NotModified:
    """The server answered 304 to a conditional call: the file at `url` is the one the caller has,
    so nothing was downloaded."""

    url: str
