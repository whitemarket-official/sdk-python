"""MANUAL selling flow: list an item, wait for a buyer, then YOU send the Steam trade offer and report its id.

Step 1, list and wait for a buyer:
    python examples/sell_manual.py list <inventory id or Steam asset id> <price USD> [--wait SECONDS] [--yes]
When a buyer appears it prints what to send and to whom. For a deal that already waits for your offer:
    python examples/sell_manual.py show <deal id>
Step 2, after you sent the item in Steam (the SDK does not send Steam offers), report the offer:
    python examples/sell_manual.py report <deal id> <Steam offer id> [--yes]

WHITEMARKET_PARTNER_TOKEN is read from the environment. THIS PUTS AN ITEM UP FOR SALE and changes a
deal. Without `--yes` it only prints what it would do. `--wait` (default 0: do not wait) polls your
seller deals until the deal reaches SELLER_SENDING_STEAM_OFFER. If you cannot send the item, use
`deals.cancel_sending_offer()` with the TRUE reason: a wrong one can lead to sanctions. Mutations are
sent once and never retried; after an ambiguous failure of `list` check `selling.my_products()`,
after one of `report` check the deal with `deals.get()`.

ASSUMPTION, not confirmed by the API docs: the product id of a seller deal equals the id of the
listed product. `list` finds your deal by that comparison.
"""

import time
from collections.abc import Sequence

from _support import make_parser, out, price_argument, run
from whitemarket import WhiteMarketClient
from whitemarket.models import Deal, DealStatus, DeliveryType, Money

POLL_SECONDS = 15.0


def print_send_instructions(deal: Deal) -> None:
    """What to send and to whom: the item's asset id to the buyer's trade URL."""
    sold = deal.item or deal.product.item
    out(f"Deal {deal.id} status {deal.status.value}")
    out(f"  item:      {(sold.name_hash if sold else None) or 'unknown item'}")
    out(f"  asset id:  {sold.asset_id if sold else 'unknown'}")
    # The trade URL carries the buyer's trade token: printed because you need it, never log it.
    url = (
        deal.receiver_trade_url.reveal() if deal.receiver_trade_url else "no trade URL in the deal"
    )
    out(f"  send to:   {url}")
    out("Send exactly this item to this trade URL in Steam, then report the offer id:")
    out(f"  python examples/sell_manual.py report {deal.id} <Steam offer id> --yes")


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    listing = modes.add_parser("list", help="list an item and wait for a buyer")
    listing.add_argument("item", help="inventory id or Steam asset id (kept a string)")
    listing.add_argument("price", type=price_argument, help="price in USD")
    listing.add_argument("--wait", type=float, default=0.0, help="seconds to wait for a buyer")
    show = modes.add_parser("show", help="print what to send for a deal")
    show.add_argument("deal_id")
    report = modes.add_parser("report", help="report the Steam offer you sent")
    report.add_argument("deal_id")
    report.add_argument("offer_id", help="id of the Steam trade offer")
    for sub in (listing, report):
        sub.add_argument("--yes", action="store_true", help="really do it (default: dry run)")
    args = parser.parse_args(argv)

    if args.mode == "show":
        with WhiteMarketClient.from_env() as client:
            print_send_instructions(client.deals.get(args.deal_id))
        return 0
    if args.mode == "report":
        out(f"Would report Steam offer {args.offer_id} for deal {args.deal_id}")
        if not args.yes:
            out("Nothing was done. Add --yes to really report.")
            return 0
        with WhiteMarketClient.from_env() as client:
            reported = client.deals.report_offer_sent(args.deal_id, args.offer_id)
        out(f"Reported. Deal status {reported.status.value}")
        return 0

    out(
        f"Would list item {args.item} for {args.price} USD with MANUAL delivery (you send the Steam offer)"
    )
    if not args.yes:
        out("Nothing was done. Add --yes to really list.")
        return 0
    with WhiteMarketClient.from_env() as client:
        product = client.selling.list(
            args.item, Money.usd(args.price), delivery_type=DeliveryType.MANUAL
        )
        out(f"Listed product {product.id}")
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            waiting = client.deals.list_as_seller([DealStatus.SELLER_SENDING_STEAM_OFFER])
            # Assumption: a seller deal carries the id of the listed product (not confirmed).
            deal = next((d for d in waiting if d.product.id == product.id), None)
            if deal is not None:
                print_send_instructions(deal)
                return 0
            time.sleep(POLL_SECONDS)  # a poll of one query until a buyer appears
    out(
        "No buyer yet. The listing stays on the market until it expires or you remove it."
        if args.wait > 0
        else "Not waiting."
    )
    return 0


if __name__ == "__main__":
    run(main)
