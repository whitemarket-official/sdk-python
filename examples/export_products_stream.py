"""Stream the public products export (millions of lots) and find the cheapest of the first 10,000 rows.

    python examples/export_products_stream.py

The export needs no authentication, so no token is used. Read-only. Leaving the loop closes the
stream; the `with` block makes that explicit.
"""

from collections.abc import Sequence

from _support import make_parser, out, run
from whitemarket import ExportClient
from whitemarket.exports import ExportWindow, ProductRow

ROW_LIMIT = 10_000


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    cheapest: ProductRow | None = None
    with ExportClient() as exports, exports.stream_products(window=ExportWindow.MINUTES10) as rows:
        for index, row in enumerate(rows):
            if cheapest is None or row.price.amount < cheapest.price.amount:
                cheapest = row
            if index + 1 >= ROW_LIMIT:
                break
    out(f"{cheapest.market_hash_name}: {cheapest.price}" if cheapest else "No rows")
    return 0


if __name__ == "__main__":
    run(main)
