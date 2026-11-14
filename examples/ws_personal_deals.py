"""Print the personal deal events of the account (your deals only) over WebSocket for a while.

    WHITEMARKET_PARTNER_TOKEN=... python examples/ws_personal_deals.py [--seconds 120]

Needs the `live` extra. This example uses the async client. Read-only: it only listens. A deal event
is a hint: read the authoritative state with `deals.get()`. The counterparty's Steam id on the event
is personal data and is not printed.
"""

import asyncio
from collections.abc import Sequence

from _support import make_parser, out, run, warn
from whitemarket import AsyncWhiteMarketClient, LiveTransport
from whitemarket.errors import LiveConnectionError
from whitemarket.live import DealEvent


async def listen(seconds: float) -> int:
    async with AsyncWhiteMarketClient.from_env() as client, client.live(LiveTransport.WS) as live:
        live.on_connected(
            lambda reconnected: out(
                "reconnected: events of the gap are lost, re-read your deals"
                if reconnected
                else "connected"
            )
        )
        live.on(
            DealEvent,
            lambda event: out(f"{type(event).__name__} deal {event.deal_id} {event.action.value}"),
        )
        live.subscribe_personal()
        try:
            await live.run(seconds)
        except LiveConnectionError as error:
            warn(f"Live connection ended: close code {error.code}")
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument("--seconds", type=float, default=120.0, help="how long to listen")
    return asyncio.run(listen(parser.parse_args(argv).seconds))


if __name__ == "__main__":
    run(main)
