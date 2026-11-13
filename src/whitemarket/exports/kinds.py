"""What an export file is: its kind and its format (SDK_SPEC 3.10)."""

from enum import StrEnum


class ExportKind(StrEnum):
    """Which feed: the value is the path segment of the URL."""

    PRICES = "prices"
    PRODUCTS = "products"


class ExportFormat(StrEnum):
    """The file format: the value is the file extension."""

    JSON = "json"
    CSV = "csv"
