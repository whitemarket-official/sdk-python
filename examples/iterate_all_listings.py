"""Walk the market listings lazily with `market.iterate()`, bounded.

    WHITEMARKET_PARTNER_TOKEN=... python examples/iterate_all_listings.py [--limit 200]

One request per page; the next page is fetched only when the loop needs it. The walk stops after
`--limit` listings (default 200), because the whole market holds millions of lots: leaving the loop
stops the requests. For the whole market use the products export instead
(`examples/export_products_stream.py`): one file, not millions of requests. Read-only.
"""

from collections.abc import Sequence

from _support import make_parser, out, run
from whitemarket import WhiteMarketClient
from whitemarket.market import ProductFilter
from whitemarket.models import App, Money


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument("--limit", type=int, default=200, help="maximum listings (at least 1)")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    count = 0
    with WhiteMarketClient.from_env() as client:
        listings = client.market.iterate(
            ProductFilter(app=App.CSGO, price_to=Money.usd("5.00")), page_size=50
        )
        for product in listings:
            out(f"{product.id} {product.price}")
            count += 1
            if count >= args.limit:
                break  # no further page is requested
    out(f"Listed {count} listings")
    return 0


if __name__ == "__main__":
    run(main)
