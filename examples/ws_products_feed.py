"""Print five live product events over WS, then exit (needs WHITEMARKET_PARTNER_TOKEN).

    WHITEMARKET_PARTNER_TOKEN=... make example NAME=ws_products_feed

Nothing secret is printed: the token never leaves the SDK, and only public product fields are
shown. Stops with exit code 1 when fewer than five events arrive within the time limit.
"""

import sys
import time

from whitemarket import LiveTransport, WhiteMarketClient
from whitemarket.live import LiveEvent, ProductAdded, ProductEdited, ProductRemoved

WANTED = 5
TIME_LIMIT_SECONDS = 120.0


def describe(event: LiveEvent) -> str:
    """One line per event, public fields only."""
    if isinstance(event, ProductAdded):
        return f"added   {event.id} {event.market_hash_name} {event.price}"
    if isinstance(event, ProductEdited):
        return f"edited  {event.id} price={event.price}"
    if isinstance(event, ProductRemoved):
        return f"removed {event.id} {event.market_hash_name}"
    return f"other   {type(event).__name__} on {event.channel}"


def main() -> int:
    seen = 0
    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    with WhiteMarketClient.from_env() as client, client.live(LiveTransport.WS) as live:
        live.on_connected(
            lambda reconnected: sys.stdout.write(f"connected (reconnected={reconnected})\n")
        )
        live.on_error(
            lambda error: sys.stdout.write(f"non-fatal problem: {type(error).__name__}\n")
        )
        live.subscribe_products()
        while seen < WANTED and time.monotonic() < deadline:
            event = live.poll(5.0)
            if event is not None:
                seen += 1
                sys.stdout.write(f"{seen}: {describe(event)}\n")
    if seen < WANTED:
        sys.stderr.write(f"only {seen} of {WANTED} events arrived\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
