"""Print five live product events over WebSocket, then exit (needs the `live` extra).

    WHITEMARKET_PARTNER_TOKEN=... python examples/ws_products_feed.py

Nothing secret is printed: the token never leaves the SDK, and only public product fields are
shown. Exit code 1 when fewer than five events arrive within two minutes.
"""

from collections.abc import Sequence

from _support import make_parser, print_product_feed, run
from whitemarket import LiveTransport


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    return print_product_feed(LiveTransport.WS, wanted=5, time_limit=120.0)


if __name__ == "__main__":
    run(main)
