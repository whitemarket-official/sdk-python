"""Export files: row models, the price list, options, meta and affiliate links (SDK_SPEC 3.10).

Everything here is pure: no network and no files. `iter_price_rows` and its siblings decode the
already decompressed chunks of an export body, for a caller that downloaded a file by itself.
The HTTP side is `whitemarket.ExportClient`.
"""

from whitemarket.exports._stream import (
    aiter_price_rows,
    aiter_product_rows,
    iter_price_rows,
    iter_product_rows,
)
from whitemarket.exports.conditional import ExportValidators, NotModified
from whitemarket.exports.kinds import ExportFormat, ExportKind
from whitemarket.exports.links import affiliate_link
from whitemarket.exports.meta import ExportMeta
from whitemarket.exports.options import ExportOptions
from whitemarket.exports.price_list import PriceList
from whitemarket.exports.rows import PriceRow, ProductRow
from whitemarket.exports.window import ExportWindow

__all__ = [
    "ExportFormat",
    "ExportKind",
    "ExportMeta",
    "ExportOptions",
    "ExportValidators",
    "ExportWindow",
    "NotModified",
    "PriceList",
    "PriceRow",
    "ProductRow",
    "affiliate_link",
    "aiter_price_rows",
    "aiter_product_rows",
    "iter_price_rows",
    "iter_product_rows",
]
