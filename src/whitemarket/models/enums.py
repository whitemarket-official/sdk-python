"""Enums shared by the high-level models, each with an unknown fallback (CLAUDE.md rule 5).

`Currency`, `DeliveryType` and `DeliveryPromise` are the generated enums of the partner schema (one
definition, no copy that could drift). Every other enum is written here under its SDK name (the
schema's `CSGOExterior` is `Exterior`: a schema name must not leak into the high-level API) and
mirrors the wire values; `tests/unit/models/test_enum_parity.py` fails when a value is missing in
the generated enum a high-level one is sent as, or (for the deal and wallet enums, where a new
value needs a classification) the other way round.
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


class App(UnknownTolerantEnum):
    """The game (Steam app) a listing belongs to. The schema's `UNKNOWN` is not a filter value.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    CSGO = "CSGO"
    DOTA2 = "DOTA2"
    TF2 = "TF2"


class Color(UnknownTolerantEnum):
    """Skin color of the catalog. The schema's `UNKNOWN` is not a filter value.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BLACK = "BLACK"
    BLUE = "BLUE"
    BROWN = "BROWN"
    CYAN = "CYAN"
    GRAY = "GRAY"
    GREEN = "GREEN"
    ORANGE = "ORANGE"
    PINK = "PINK"
    PURPLE = "PURPLE"
    RED = "RED"
    WHITE = "WHITE"
    YELLOW = "YELLOW"


class Exterior(UnknownTolerantEnum):
    """CS2 item wear category.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BATTLE_SCARED = "BATTLE_SCARED"
    FACTORY_NEW = "FACTORY_NEW"
    FIELD_TESTED = "FIELD_TESTED"
    MINIMAL_WEAR = "MINIMAL_WEAR"
    NOT_PAINTED = "NOT_PAINTED"
    WELL_WORN = "WELL_WORN"


class ItemSubcategory(UnknownTolerantEnum):
    """CS2 item subcategory (weapon, knife, agent, ...).

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    AK47 = "AK47"
    AUG = "AUG"
    AWP = "AWP"
    BIZON = "BIZON"
    C4 = "C4"
    COLLECTIBLE = "COLLECTIBLE"
    CUSTOM_PLAYER_BRAZILIAN_1ST_BATTALION = "CUSTOM_PLAYER_BRAZILIAN_1ST_BATTALION"
    CUSTOM_PLAYER_ELITE_CREW = "CUSTOM_PLAYER_ELITE_CREW"
    CUSTOM_PLAYER_FBI = "CUSTOM_PLAYER_FBI"
    CUSTOM_PLAYER_FBI_HRT = "CUSTOM_PLAYER_FBI_HRT"
    CUSTOM_PLAYER_FBI_SNIPER = "CUSTOM_PLAYER_FBI_SNIPER"
    CUSTOM_PLAYER_FBI_SWAT = "CUSTOM_PLAYER_FBI_SWAT"
    CUSTOM_PLAYER_GENDARMERIE_NATIONALE = "CUSTOM_PLAYER_GENDARMERIE_NATIONALE"
    CUSTOM_PLAYER_GUERRILLA_WARFARE = "CUSTOM_PLAYER_GUERRILLA_WARFARE"
    CUSTOM_PLAYER_KSK = "CUSTOM_PLAYER_KSK"
    CUSTOM_PLAYER_NSWC_SEAL = "CUSTOM_PLAYER_NSWC_SEAL"
    CUSTOM_PLAYER_NZSAS = "CUSTOM_PLAYER_NZSAS"
    CUSTOM_PLAYER_PHOENIX = "CUSTOM_PLAYER_PHOENIX"
    CUSTOM_PLAYER_SABRE = "CUSTOM_PLAYER_SABRE"
    CUSTOM_PLAYER_SABRE_FOOTSOLDIER = "CUSTOM_PLAYER_SABRE_FOOTSOLDIER"
    CUSTOM_PLAYER_SAS = "CUSTOM_PLAYER_SAS"
    CUSTOM_PLAYER_SEAL_FROGMAN = "CUSTOM_PLAYER_SEAL_FROGMAN"
    CUSTOM_PLAYER_SWAT = "CUSTOM_PLAYER_SWAT"
    CUSTOM_PLAYER_TACP_CAVALRY = "CUSTOM_PLAYER_TACP_CAVALRY"
    CUSTOM_PLAYER_THE_PROFESSIONALS = "CUSTOM_PLAYER_THE_PROFESSIONALS"
    CUSTOM_PLAYER_USAF_TACP = "CUSTOM_PLAYER_USAF_TACP"
    CZ75A = "CZ75A"
    DEAGLE = "DEAGLE"
    ELITE = "ELITE"
    FAMAS = "FAMAS"
    FIVESEVEN = "FIVESEVEN"
    G3SG1 = "G3SG1"
    GALILAR = "GALILAR"
    GLOCK = "GLOCK"
    GLOVE_BLOODHOUND = "GLOVE_BLOODHOUND"
    GLOVE_BROKEN_FANG = "GLOVE_BROKEN_FANG"
    GLOVE_FINGERLESS = "GLOVE_FINGERLESS"
    GLOVE_HAND_WRAPS = "GLOVE_HAND_WRAPS"
    GLOVE_HARDKNUCKLE = "GLOVE_HARDKNUCKLE"
    GLOVE_HYDRA = "GLOVE_HYDRA"
    GLOVE_MOTORCYCLE = "GLOVE_MOTORCYCLE"
    GLOVE_SLICK = "GLOVE_SLICK"
    GLOVE_SPECIALIST = "GLOVE_SPECIALIST"
    GLOVE_SPORT = "GLOVE_SPORT"
    HKP2000 = "HKP2000"
    KNIFE = "KNIFE"
    KNIFE_BAYONET = "KNIFE_BAYONET"
    KNIFE_BOWIE = "KNIFE_BOWIE"
    KNIFE_BUTTERFLY = "KNIFE_BUTTERFLY"
    KNIFE_CLASSIC = "KNIFE_CLASSIC"
    KNIFE_CORD = "KNIFE_CORD"
    KNIFE_FALCHION = "KNIFE_FALCHION"
    KNIFE_FLIP = "KNIFE_FLIP"
    KNIFE_GUT = "KNIFE_GUT"
    KNIFE_KARAMBIT = "KNIFE_KARAMBIT"
    KNIFE_KUKRI = "KNIFE_KUKRI"
    KNIFE_M9_BAYONET = "KNIFE_M9_BAYONET"
    KNIFE_NAVAJA = "KNIFE_NAVAJA"
    KNIFE_NOMAD = "KNIFE_NOMAD"
    KNIFE_SHADOW_DAGGER = "KNIFE_SHADOW_DAGGER"
    KNIFE_SKELETON = "KNIFE_SKELETON"
    KNIFE_STILETTO = "KNIFE_STILETTO"
    KNIFE_SURVIVAL = "KNIFE_SURVIVAL"
    KNIFE_TACTICAL = "KNIFE_TACTICAL"
    KNIFE_TALON = "KNIFE_TALON"
    KNIFE_URSUS = "KNIFE_URSUS"
    M4A1 = "M4A1"
    M4A1S = "M4A1S"
    M249 = "M249"
    MAC10 = "MAC10"
    MAG7 = "MAG7"
    MP5SD = "MP5SD"
    MP7 = "MP7"
    MP9 = "MP9"
    MUSIC_KIT = "MUSIC_KIT"
    NEGEV = "NEGEV"
    NOVA = "NOVA"
    P90 = "P90"
    P250 = "P250"
    REVOLVER = "REVOLVER"
    SAWEDOFF = "SAWEDOFF"
    SCAR20 = "SCAR20"
    SG556 = "SG556"
    SPRAY = "SPRAY"
    SSG08 = "SSG08"
    STICKER = "STICKER"
    STICKER_SLAB = "STICKER_SLAB"
    TASER = "TASER"
    TEC9 = "TEC9"
    TICKET = "TICKET"
    TOOL = "TOOL"
    TOOL_GIFT_TAG = "TOOL_GIFT_TAG"
    TOOL_KEY_CHAIN = "TOOL_KEY_CHAIN"
    TOOL_NAME_TAGTAG = "TOOL_NAME_TAGTAG"
    TOOL_NAME_TAG_TAG = "TOOL_NAME_TAG_TAG"
    TOOL_PATCH = "TOOL_PATCH"
    TOOL_WEAPON_CASE_KEY_TAG = "TOOL_WEAPON_CASE_KEY_TAG"
    UMP45 = "UMP45"
    USP_SILENCER = "USP_SILENCER"
    WEAPON_CASE = "WEAPON_CASE"
    WEAPON_CASE_CAPSULE = "WEAPON_CASE_CAPSULE"
    WEAPON_CASE_OTHER = "WEAPON_CASE_OTHER"
    WEAPON_CASE_PATCH_PACK = "WEAPON_CASE_PATCH_PACK"
    WEAPON_CASE_SOUVENIR_PACKAGE = "WEAPON_CASE_SOUVENIR_PACKAGE"
    WEAPON_CASE_WEAPON_CASE = "WEAPON_CASE_WEAPON_CASE"
    XM1014 = "XM1014"


class LogicOperand(UnknownTolerantEnum):
    """How a list of conditions combines.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    AND = "AND"
    OR = "OR"


class OfferType(UnknownTolerantEnum):
    """Market product offer type.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BARGAIN = "BARGAIN"


class Phase(UnknownTolerantEnum):
    """CS2 Doppler/Gamma Doppler phase.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BLACK_PEARL = "BLACK_PEARL"
    EMERALD = "EMERALD"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"
    RUBY = "RUBY"
    SAPPHIRE = "SAPPHIRE"


class ProductSortField(UnknownTolerantEnum):
    """What a product search or inventory list is ordered by.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    CREATED = "CREATED"
    DISTINCT_VALUES_COUNT = "DISTINCT_VALUES_COUNT"
    FLOAT = "FLOAT"
    NAME = "NAME"
    ON_SALE = "ON_SALE"
    POPULARITY = "POPULARITY"
    PRICE = "PRICE"
    PRICE_ABS_DIFF = "PRICE_ABS_DIFF"
    PRICE_DIFF = "PRICE_DIFF"
    PRICE_RATIO_DIFF = "PRICE_RATIO_DIFF"
    PRODUCT_PRICE = "PRODUCT_PRICE"


class Rarity(UnknownTolerantEnum):
    """CS2 item rarity.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    ANCIENT = "ANCIENT"
    ANCIENT_CHARACTER = "ANCIENT_CHARACTER"
    ANCIENT_WEAPON = "ANCIENT_WEAPON"
    COMMON = "COMMON"
    COMMON_WEAPON = "COMMON_WEAPON"
    CONTRABAND = "CONTRABAND"
    DEFAULT_WEAPON = "DEFAULT_WEAPON"
    LEGENDARY = "LEGENDARY"
    LEGENDARY_CHARACTER = "LEGENDARY_CHARACTER"
    LEGENDARY_WEAPON = "LEGENDARY_WEAPON"
    MYTHICAL = "MYTHICAL"
    MYTHICAL_CHARACTER = "MYTHICAL_CHARACTER"
    MYTHICAL_WEAPON = "MYTHICAL_WEAPON"
    RARE = "RARE"
    RARE_CHARACTER = "RARE_CHARACTER"
    RARE_WEAPON = "RARE_WEAPON"
    UNCOMMON_WEAPON = "UNCOMMON_WEAPON"


class SortDirection(UnknownTolerantEnum):
    """Sort direction.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    ASC = "ASC"
    DESC = "DESC"


class StickerFilm(UnknownTolerantEnum):
    """Sticker finish.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    FOIL = "FOIL"
    GLITTER = "GLITTER"
    GOLD = "GOLD"
    HOLO = "HOLO"
    LENTICULAR = "LENTICULAR"


class ProductStatus(UnknownTolerantEnum):
    """Why a listing left the market (`ProductHistory`). `DEAL` means sold.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    DEAL = "DEAL"
    DELETED = "DELETED"
    EXPIRED = "EXPIRED"
    GONE = "GONE"


class DealCancelReason(UnknownTolerantEnum):
    """Why a deal was cancelled. `UNKNOWN` is a value the server sends itself.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BUYER_INVENTORY_PRIVATE = "BUYER_INVENTORY_PRIVATE"
    BUYER_NOT_TRADEABLE = "BUYER_NOT_TRADEABLE"
    BUYER_OR_SELLER_NOT_TRADEABLE = "BUYER_OR_SELLER_NOT_TRADEABLE"
    BUYER_STEAM_CANCELLED = "BUYER_STEAM_CANCELLED"
    BUYER_STEAM_FAMILY_VIEW = "BUYER_STEAM_FAMILY_VIEW"
    BUYER_TOO_MANY_FAILED_ATTEMPTS = "BUYER_TOO_MANY_FAILED_ATTEMPTS"
    BUYER_TRADE_URL_INVALID = "BUYER_TRADE_URL_INVALID"
    CANCEL_BY_ADMIN = "CANCEL_BY_ADMIN"
    INSTANT_EXCHANGE_FAILED = "INSTANT_EXCHANGE_FAILED"
    INTERNAL = "INTERNAL"
    NO_FUNDS = "NO_FUNDS"
    SELLER_APIKEY_INVALID = "SELLER_APIKEY_INVALID"
    SELLER_NOT_TRADEABLE = "SELLER_NOT_TRADEABLE"
    SELLER_STEAM_CANCELLED = "SELLER_STEAM_CANCELLED"
    SELLER_STEAM_FAMILY_VIEW = "SELLER_STEAM_FAMILY_VIEW"
    SELLER_TRADE_URL_INVALID = "SELLER_TRADE_URL_INVALID"
    SKIN_UNAVAILABLE = "SKIN_UNAVAILABLE"
    STEAM_ISSUES = "STEAM_ISSUES"
    STEAM_SENDING_LIMIT_EXCEED = "STEAM_SENDING_LIMIT_EXCEED"
    STEAM_VAC_BAN = "STEAM_VAC_BAN"
    UNKNOWN = "UNKNOWN"


class DealAction(UnknownTolerantEnum):
    """Which side of the deal history to read: deals the caller bought or sold.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BUY = "BUY"
    SELL = "SELL"


class TransactionReason(UnknownTolerantEnum):
    """Why a wallet transaction happened.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BONUS = "BONUS"
    DEPOSIT = "DEPOSIT"
    GIFT_CARD_PURCHASE = "GIFT_CARD_PURCHASE"
    INSTANT_EXCHANGE = "INSTANT_EXCHANGE"
    INSTANT_EXCHANGE_HOLD_RELEASE_IN = "INSTANT_EXCHANGE_HOLD_RELEASE_IN"
    INSTANT_EXCHANGE_HOLD_RELEASE_OUT = "INSTANT_EXCHANGE_HOLD_RELEASE_OUT"
    INSTANT_EXCHANGE_REFUND_IN = "INSTANT_EXCHANGE_REFUND_IN"
    INSTANT_EXCHANGE_REFUND_OUT = "INSTANT_EXCHANGE_REFUND_OUT"
    INSTANT_EXCHANGE_TRANSFER_IN = "INSTANT_EXCHANGE_TRANSFER_IN"
    INSTANT_EXCHANGE_TRANSFER_OUT = "INSTANT_EXCHANGE_TRANSFER_OUT"
    INTERNAL = "INTERNAL"
    MARKET_OFFER_HOLD = "MARKET_OFFER_HOLD"
    MARKET_PRODUCT = "MARKET_PRODUCT"
    REVERSE_PENALTY = "REVERSE_PENALTY"
    REVERSE_REFUND = "REVERSE_REFUND"
    TRANSFER = "TRANSFER"
    WITHDRAWAL = "WITHDRAWAL"
    WRITE_OFF = "WRITE_OFF"


__all__ = [
    "App",
    "Color",
    "Currency",
    "DealAction",
    "DealCancelReason",
    "DeliveryPromise",
    "DeliveryType",
    "Exterior",
    "ItemCategory",
    "ItemSubcategory",
    "LogicOperand",
    "OfferType",
    "Phase",
    "ProductSortField",
    "ProductStatus",
    "Rarity",
    "SortDirection",
    "StickerFilm",
    "TransactionReason",
]
