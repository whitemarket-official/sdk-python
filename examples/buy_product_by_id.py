"""Buy one listing by its product id, with an idempotent `custom_id`.

    WHITEMARKET_PARTNER_TOKEN=... python examples/buy_product_by_id.py <product id> <max price USD> [--custom-id ID] [--yes]

THIS SPENDS MONEY. Without `--yes` it only reads the listing and prints what it would do.

The listing is read first and refused above the max price. `buy_product()` also sends the max price
to the server, which caps the price at the moment of the purchase: a seller who raises it between
the read and the buy is refused and no deal is created. The purchase mutation is sent once and never
retried; an ambiguous failure is reconciled by `custom_id` and may end in `PurchaseOutcomeUnknownError`
(do not buy again, look the deal up with `deals.get(<custom_id>)` later). The id is printed BEFORE
the call: a real program stores it in its own database first.
"""

from collections.abc import Sequence

from _support import (
    EXIT_REJECTED,
    buy_guarded,
    make_parser,
    new_custom_id,
    out,
    price_argument,
    run,
    warn,
)
from whitemarket import WhiteMarketClient
from whitemarket.errors import NotFoundError
from whitemarket.models import Currency, Money


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument("product_id", help="id of the listing (`Product.id`)")
    parser.add_argument("max_price", type=price_argument, help="maximum price in USD")
    parser.add_argument("--custom-id", default=None, help="reuse it to retry the SAME purchase")
    parser.add_argument("--yes", action="store_true", help="really buy (default: dry run)")
    args = parser.parse_args(argv)
    custom_id = args.custom_id or new_custom_id()
    max_price = Money.usd(args.max_price)
    with WhiteMarketClient.from_env() as client:
        try:
            product = client.market.get(args.product_id)
        except NotFoundError:
            warn("No listing with this id.")
            return EXIT_REJECTED
        name = product.item.name_hash if product.item else None
        out(f"Listing {product.id}: {name or 'unknown item'} for {product.price}")
        if product.is_owner:
            warn("This is your own listing.")
            return EXIT_REJECTED
        # Money is an exact Decimal; ordering across currencies raises, so check the currency first.
        if product.price.currency != Currency.USD or product.price > max_price:
            warn(f"The price is above {max_price}: nothing was bought.")
            return EXIT_REJECTED
        out(f"Would buy it, custom_id {custom_id}")
        if not args.yes:
            out("Nothing was done. Add --yes to really buy.")
            return 0
        # Persist custom_id in your own storage here, BEFORE the call.
        return buy_guarded(
            client,
            custom_id,
            lambda: client.buying.buy_product(product.id, max_price, custom_id=custom_id),
        )


if __name__ == "__main__":
    run(main)
