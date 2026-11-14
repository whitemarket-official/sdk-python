"""List the first page of cheap CS2 listings of the market.

    WHITEMARKET_PARTNER_TOKEN=... python examples/search_market.py

Read-only: no order, purchase or listing is made.
"""

from collections.abc import Sequence

from _support import make_parser, out, run
from whitemarket import WhiteMarketClient
from whitemarket.market import ProductFilter
from whitemarket.models import App, Money, PageRequest


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    with WhiteMarketClient.from_env() as client:
        page = client.market.search(
            ProductFilter(app=App.CSGO, price_to=Money.usd("5.00")), PageRequest(first=10)
        )
        for product in page:
            out(f"{product.id} {product.price}")
        out(f"More pages: {'yes' if page.has_next_page else 'no'}")
    return 0


if __name__ == "__main__":
    run(main)
