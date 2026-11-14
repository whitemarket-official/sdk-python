"""Buy the cheapest listing of an item by its market hash name, with an idempotent `custom_id`.

    WHITEMARKET_PARTNER_TOKEN=... python examples/buy_cheapest_by_name.py "<market hash name>" <max price USD> [--custom-id ID] [--yes]

THIS SPENDS MONEY. Without `--yes` it only prints what it would do.

The purchase mutation is sent once and never retried. If the answer is lost (timeout, 5xx), the SDK
waits and looks the deal up by `custom_id`; if it still finds nothing it raises
`PurchaseOutcomeUnknownError` and the outcome is UNKNOWN: do not buy again, look the deal up with
`deals.get(<custom_id>)` later. The id is printed BEFORE the call: a real program stores it in its
own database first, so it survives a crash.
"""

from collections.abc import Sequence

from _support import buy_guarded, make_parser, new_custom_id, out, price_argument, run
from whitemarket import WhiteMarketClient
from whitemarket.models import App, Money


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser(__doc__)
    parser.add_argument(
        "name_hash", help="market hash name, for example 'AK-47 | Redline (Field-Tested)'"
    )
    parser.add_argument("max_price", type=price_argument, help="maximum price in USD")
    parser.add_argument("--custom-id", default=None, help="reuse it to retry the SAME purchase")
    parser.add_argument("--yes", action="store_true", help="really buy (default: dry run)")
    args = parser.parse_args(argv)
    custom_id = args.custom_id or new_custom_id()
    out(
        f"Would buy the cheapest {args.name_hash!r} for at most {args.max_price} USD, custom_id {custom_id}"
    )
    if not args.yes:
        out("Nothing was done. Add --yes to really buy.")
        return 0
    with WhiteMarketClient.from_env() as client:
        # Persist custom_id in your own storage here, BEFORE the call.
        return buy_guarded(
            client,
            custom_id,
            lambda: client.buying.buy_cheapest(
                App.CSGO,
                args.name_hash,
                max_price=Money.usd(args.max_price),
                custom_id=custom_id,
            ),
        )


if __name__ == "__main__":
    run(main)
