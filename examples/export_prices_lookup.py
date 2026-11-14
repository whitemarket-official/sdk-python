"""Download the public prices export and look one item up by (market_hash_name, paint_index).

    python examples/export_prices_lookup.py

The export needs no authentication, so no token is used. Read-only. (`conditional=True` would return `NotModified` for an unchanged file.)
"""

from collections.abc import Sequence

from _support import make_parser, out, run, warn
from whitemarket import ExportClient
from whitemarket.errors import StaleExportError
from whitemarket.exports import ExportWindow


def main(argv: Sequence[str] | None = None) -> int:
    make_parser(__doc__).parse_args(argv)
    with ExportClient() as exports:
        try:
            # Refuse data older than 15 minutes before the file is downloaded.
            prices = exports.prices(window=ExportWindow.MINUTES10, max_age=900)
        except StaleExportError as error:
            warn(f"The export is stale: {error}")
            return 1
        out(f"Rows: {len(prices)}")
        row = prices.get("AK-47 | Redline (Field-Tested)", "282")
        out(f"{row.market_hash_name}: {row.price}" if row else "Not listed")
    return 0


if __name__ == "__main__":
    run(main)
