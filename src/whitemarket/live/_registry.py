"""Handler registration shared by the async and the threaded session."""

from collections.abc import Callable
from typing import Any, TypeVar

from whitemarket.live import _policy as policy
from whitemarket.live._handlers import EventHandler, LiveDisconnected, LiveHandlers
from whitemarket.live.events import LiveEvent

_E = TypeVar("_E", bound=LiveEvent)


class Registry:
    """`subscribe_*`, `on` and the lifecycle callbacks. A handler may be a plain function (any
    session) or, on the async session, a coroutine function. An exception from a handler
    propagates out of the call that dispatched it; the connection stays open."""

    def __init__(self, handlers: LiveHandlers, subscribe: Callable[[str], None]) -> None:
        self._handlers = handlers
        self._subscribe = subscribe

    def subscribe_products(self, handler: EventHandler | None = None) -> None:
        """Subscribe to `market_products_updates`; `handler` gets the events of that channel."""
        self._subscribe(policy.PRODUCTS_CHANNEL)
        if handler is not None:
            self._handlers.add_event(handler, lambda channel: channel == policy.PRODUCTS_CHANNEL)

    def subscribe_personal(self, handler: EventHandler | None = None) -> None:
        """Handle the events of the personal channel (`#<personId>`). No subscribe is sent: the
        server subscribes it on connect. Channels are recognised by the leading `#`."""
        if handler is not None:
            self._handlers.add_event(handler, policy.is_personal)

    def on(self, event_type: type[_E], handler: Callable[[_E], Any]) -> None:
        """`handler` gets every event that is an instance of `event_type` (any channel)."""

        def accepts(event: Any) -> Any:
            return handler(event) if isinstance(event, event_type) else None

        self._handlers.add_event(accepts)

    def on_connecting(self, handler: Callable[[], Any]) -> None:
        self._handlers.add_connecting(handler)

    def on_connected(self, handler: Callable[[bool], Any]) -> None:
        """`handler(reconnected)`: True after a reconnect. Messages sent while disconnected are
        lost (no offsets): resync through GraphQL."""
        self._handlers.add_connected(handler)

    def on_disconnected(self, handler: Callable[[LiveDisconnected], Any]) -> None:
        self._handlers.add_disconnected(handler)

    def on_error(self, handler: Callable[[Exception], Any]) -> None:
        """Non-fatal problems: a malformed message, a failed connect attempt, a server error."""
        self._handlers.add_error(handler)
