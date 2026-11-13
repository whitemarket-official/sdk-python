"""Known `extensions.category` values of GraphQL errors (SDK_SPEC 1.5)."""

from typing import Final


class ErrorCategory:
    """Constants, not an enum: an unknown category is still delivered as a plain string.

    Branch on these, never on an error message. The catalogue grows as the backend confirms
    categories (docs/WHITEMARKET_API.md).
    """

    MARKET_PRODUCT_NOT_FOUND: Final = "market.product.not_found"
    MARKET_PRODUCT_NOT_FOUND_IN_SPECIFIED_PRICE: Final = (
        "market.product.not_found_in_specified_price"
    )

    NOT_FOUND_SUFFIX: Final = ".not_found"

    @staticmethod
    def is_not_found(category: str | None) -> bool:
        """True for a category ending with `.not_found` (`..._in_specified_price` does not)."""
        return category is not None and category.endswith(ErrorCategory.NOT_FOUND_SUFFIX)
