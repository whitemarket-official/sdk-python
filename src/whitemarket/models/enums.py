"""Enums shared by the high-level models, each with an unknown fallback (CLAUDE.md rule 5).

`Currency`, `DeliveryType` and `DeliveryPromise` are the generated enums of the partner schema (one
definition, no copy that could drift); `ItemCategory` has no generated twin under that name (the
schema calls it `CSGOCategory`, a schema name that must not leak into the high-level API).
"""

from whitemarket._generated.enums import Currency, DeliveryPromise, DeliveryType
from whitemarket._runtime.enums import UnknownTolerantEnum


class ItemCategory(UnknownTolerantEnum):
    """The category of an item (`product_category` of the products export).

    A value this list does not know decodes to a pseudo-member with the raw value (`is_unknown`).
    The export holds values beyond it (`OTHERS`, WHITEMARKET_API.md 8).
    """

    AGENT = "AGENT"
    CASE = "CASE"
    GLOVES = "GLOVES"
    HEAVY = "HEAVY"
    KNIVES = "KNIVES"
    OTHER = "OTHER"
    PISTOLS = "PISTOLS"
    RIFLES = "RIFLES"
    SMGS = "SMGS"
    SNIPER_RIFLES = "SNIPER_RIFLES"
    STICKERS = "STICKERS"


__all__ = ["Currency", "DeliveryPromise", "DeliveryType", "ItemCategory"]
