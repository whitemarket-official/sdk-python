"""Error hierarchy of the SDK (SDK_SPEC 1.5)."""

from whitemarket.errors.base import (
    BatchIncompleteError,
    DealWaitTimeoutError,
    DecodeError,
    ExportError,
    GeneralExportError,
    LiveConnectionError,
    MutationOutcomeUnknownError,
    PurchaseOutcomeUnknownError,
    StaleExportError,
    TransportError,
    WhiteMarketError,
)
from whitemarket.errors.category import ErrorCategory
from whitemarket.errors.graphql import (
    GraphQLError,
    GraphQLErrorEntry,
    NotFoundError,
    SourceLocation,
)
from whitemarket.errors.http import (
    AuthenticationError,
    BadRequestError,
    HttpError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)

__all__ = [
    "AuthenticationError",
    "BadRequestError",
    "BatchIncompleteError",
    "DealWaitTimeoutError",
    "DecodeError",
    "ErrorCategory",
    "ExportError",
    "GeneralExportError",
    "GraphQLError",
    "GraphQLErrorEntry",
    "HttpError",
    "LiveConnectionError",
    "MutationOutcomeUnknownError",
    "NotFoundError",
    "PurchaseOutcomeUnknownError",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "SourceLocation",
    "StaleExportError",
    "TransportError",
    "WhiteMarketError",
]
