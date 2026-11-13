"""Manual live check of the export client against https://export.white.market (read-only GETs).

Not part of the test suite and not run in CI: it talks to the public network. Run it by hand:

    .venv/bin/python tools/export_live_check.py

It fetches the two `.meta.json` sidecars, the (small) prices file through `stream_prices`, and only
the first rows of the (huge) products file through `stream_products`, then stops the stream, which
closes the connection. It prints counts, dates and a few item names and prices; no credential is
involved and none is read from the environment.
"""

import sys
import time

from whitemarket import ExportClient
from whitemarket.errors import WhiteMarketError
from whitemarket.exports import ExportKind

FIRST_ROWS = 5


def say(text: str) -> None:
    sys.stdout.write(text + "\n")


def main() -> int:
    with ExportClient() as exports:
        for kind in (ExportKind.PRICES, ExportKind.PRODUCTS):
            meta = exports.meta(kind)
            say(
                f"meta {kind.value}: file={meta.file} items={meta.items} "
                f"data_as_of={meta.data_as_of.isoformat()} "
                f"generated_at={meta.generated_at.isoformat()}"
            )

        started = time.monotonic()
        prices = exports.stream_prices()
        rows = list(prices)
        say(f"stream_prices: {len(rows)} rows in {time.monotonic() - started:.1f}s")
        for price in rows[:FIRST_ROWS]:
            say(
                f"  price: {price.market_hash_name!r} {price.price} "
                f"count={price.market_product_count} paint_index={price.paint_index}"
            )

        started = time.monotonic()
        products = exports.stream_products()
        say(f"stream_products: connected in {time.monotonic() - started:.1f}s")
        taken = 0
        for product in products:
            say(
                f"  product: {product.market_hash_name!r} {product.price} "
                f"category={product.category} delivery={product.delivery_type}"
            )
            taken += 1
            if taken == FIRST_ROWS:
                break
        started = time.monotonic()
        products.close()
        say(f"stopped after {taken} rows; connection closed in {time.monotonic() - started:.3f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WhiteMarketError as error:
        say(f"FAILED: {type(error).__name__}: {error}")
        sys.exit(1)
