"""SEMI selling flow: list an item, then follow the deal until the buyer's offer is exchanged.

    WHITEMARKET_PARTNER_TOKEN=... python examples/sell_semi.py <inventory id or Steam asset id> <price USD> [--wait SECONDS] [--yes]

In SEMI delivery WhiteMarket sends the Steam trade offer and YOU confirm it in Steam Mobile.
THIS PUTS AN ITEM UP FOR SALE. Without `--yes` it only prints what it would do. `--wait` (default 0:
do not wait) polls your seller deals for that long; when the deal reaches NEED_CONFIRMATION you
confirm it in Steam Mobile, then the script waits for EXCHANGED or a final status.

Listing is a mutation: sent once, never retried. If it fails ambiguously, check
`selling.my_products()` before trying again.

ASSUMPTION, not confirmed by the API docs: the product id of a seller deal equals the id of the
listed product. The script finds your deal by that comparison.
"""

import time
from collections.abc import Sequence

from _support import make_parser, out, price_argument, print_status_changes, run, warn
from whitemarket import WhiteMarketClient
from whitemarket.deals import Until
from whitemarket.errors import DealWaitTimeoutError
from whitemarket.models import DealStatus, DeliveryType, Money

POLL_SECONDS = 15.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument(
        "item", help="inventory id or Steam asset id (a 64-bit number: kept a string)"
    )
    parser.add_argument("price", type=price_argument, help="price in USD")
    parser.add_argument("--wait", type=float, default=0.0, help="seconds to wait for a buyer")
    parser.add_argument("--yes", action="store_true", help="really list (default: dry run)")
    args = parser.parse_args(argv)
    out(f"Would list item {args.item} for {args.price} USD with SEMI delivery")
    out("(WhiteMarket sends the offer, you confirm it in Steam Mobile)")
    if not args.yes:
        out("Nothing was done. Add --yes to really list.")
        return 0
    with WhiteMarketClient.from_env() as client:
        product = client.selling.list(
            args.item, Money.usd(args.price), delivery_type=DeliveryType.SEMI
        )
        out(f"Listed product {product.id}")
        if args.wait <= 0:
            out("Not waiting. Watch your deals with `deals.list_as_seller()`.")
            return 0
        deadline = time.monotonic() + args.wait
        deal = None
        while deal is None and time.monotonic() < deadline:
            # Assumption: a seller deal carries the id of the listed product (not confirmed).
            deal = next(
                (d for d in client.deals.list_as_seller() if d.product.id == product.id), None
            )
            if deal is None:
                time.sleep(POLL_SECONDS)  # a poll of one query, not a loop of mutations
        if deal is None:
            warn("No buyer yet. The listing stays on the market until it expires or you remove it.")
            return 0
        out(f"Deal {deal.id} status {deal.status.value}")
        if deal.status == DealStatus.NEED_CONFIRMATION:
            out("Confirm the trade offer in Steam Mobile now.")
        try:
            state = client.deals.wait_for(
                deal.id,
                print_status_changes(Until.exchanged_or_completed()),
                timeout=max(0.0, deadline - time.monotonic()),
                poll_interval=POLL_SECONDS,
            )
        except DealWaitTimeoutError:
            warn("Timed out; the deal is still in progress.")
            return 1
    out(f"Deal reached {state.status.value}")
    return 0


if __name__ == "__main__":
    run(main)
