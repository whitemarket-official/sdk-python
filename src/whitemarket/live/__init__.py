"""Live updates (SDK_SPEC 3.11): SSE and WebSocket (Centrifugo).

`client.live(transport, options)` returns a `LiveSession` (sync client) or an `AsyncLiveSession`
(async client). Events are frozen dataclasses; a type this SDK does not know is an `UnknownEvent`.
"""

from whitemarket.live._handlers import LiveDisconnected
from whitemarket.live.async_session import AsyncLiveSession
from whitemarket.live.events import (
    DealCancelled,
    DealCompleted,
    DealEvent,
    DealExchanged,
    DealExpired,
    DealHold,
    DealInitiated,
    DealNeedConfirmation,
    DealOffered,
    LiveEvent,
    ProductAdded,
    ProductEdited,
    ProductRemoved,
    UnknownEvent,
)
from whitemarket.live.options import LiveOptions, LiveTransport
from whitemarket.live.session import LiveSession

__all__ = [
    "AsyncLiveSession",
    "DealCancelled",
    "DealCompleted",
    "DealEvent",
    "DealExchanged",
    "DealExpired",
    "DealHold",
    "DealInitiated",
    "DealNeedConfirmation",
    "DealOffered",
    "LiveDisconnected",
    "LiveEvent",
    "LiveOptions",
    "LiveSession",
    "LiveTransport",
    "ProductAdded",
    "ProductEdited",
    "ProductRemoved",
    "UnknownEvent",
]
