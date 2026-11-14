"""Enums of the wallet, profile and store models, each with an unknown fallback (CLAUDE.md rule 5).

`Locale`, `PaymentProvider`, `CryptoCurrency` and `CryptoNetwork` are the generated enums of the
partner schema (one definition, as `Currency` in `enums.py`). The others are written here under
their SDK names, because a schema name (`WalletMethodEnum`, `AvatarType`, `AchievementTypeType`)
must not leak into the high-level API. `tests/unit/models/test_enum_parity.py` fails when one of
them misses a value of the generated enum it mirrors, or the other way round.
"""

from whitemarket._generated.enums import CryptoCurrency, CryptoNetwork, Locale, PaymentProvider
from whitemarket._runtime.enums import UnknownTolerantEnum


class WalletMethod(UnknownTolerantEnum):
    """The payment method of a wallet transaction.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    AIRWALLEX = "AIRWALLEX"
    BANK_CARD = "BANK_CARD"
    C4S = "C4S"
    DIFMARK = "DIFMARK"
    DRIFFLE = "DRIFFLE"
    ENEBA = "ENEBA"
    ESEA = "ESEA"
    G2A = "G2A"
    GAMESEAL = "GAMESEAL"
    INTERNAL = "INTERNAL"
    KINGUIN = "KINGUIN"
    LIKECARD = "LIKECARD"
    MERCURYO = "MERCURYO"
    NUVEI = "NUVEI"
    OFFGAMERS = "OFFGAMERS"
    PAYOP = "PAYOP"
    PAYPAL = "PAYPAL"
    PAYSERA = "PAYSERA"
    SEAGM = "SEAGM"
    SEPA = "SEPA"
    SKINSBACK = "SKINSBACK"
    SOLIDGATE = "SOLIDGATE"
    TIPALTI = "TIPALTI"
    WHITEBIT = "WHITEBIT"
    WHITEBIT_CODE = "WHITEBIT_CODE"
    WHITEPAY = "WHITEPAY"
    ZEN = "ZEN"


class DepositStatus(UnknownTolerantEnum):
    """The state of a deposit.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    UNCREDITED = "UNCREDITED"


class WithdrawalStatus(UnknownTolerantEnum):
    """The state of a withdrawal.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"


class TransferStatus(UnknownTolerantEnum):
    """The state of a transfer between partners.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    CANCELLED = "CANCELLED"
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"


class TransactionStatus(UnknownTolerantEnum):
    """The state of a wallet transaction.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    CANCELED = "CANCELED"
    HOLD_INCOME = "HOLD_INCOME"
    HOLD_OUTCOME = "HOLD_OUTCOME"
    SUCCESS = "SUCCESS"
    SUCCESS_HOLD = "SUCCESS_HOLD"


class TransactionFeeType(UnknownTolerantEnum):
    """The kind of fee a wallet transaction list is filtered by.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BONUS = "BONUS"
    DEPOSIT = "DEPOSIT"
    INTERNAL = "INTERNAL"
    MARKET_PRODUCT = "MARKET_PRODUCT"
    WITHDRAWAL = "WITHDRAWAL"


class TransactionSortField(UnknownTolerantEnum):
    """What the wallet transactions are ordered by.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    AMOUNT = "AMOUNT"
    CREATED_AT = "CREATED_AT"


class StoreAvatar(UnknownTolerantEnum):
    """The avatar a store shows.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    AVATAR_1 = "AVATAR_1"
    AVATAR_2 = "AVATAR_2"
    AVATAR_3 = "AVATAR_3"
    AVATAR_4 = "AVATAR_4"
    AVATAR_5 = "AVATAR_5"
    AVATAR_6 = "AVATAR_6"
    AVATAR_7 = "AVATAR_7"
    AVATAR_8 = "AVATAR_8"
    AVATAR_9 = "AVATAR_9"
    AVATAR_10 = "AVATAR_10"
    AVATAR_11 = "AVATAR_11"
    AVATAR_12 = "AVATAR_12"
    CUSTOM = "CUSTOM"
    STEAM = "STEAM"


class StoreBanner(UnknownTolerantEnum):
    """The banner a store shows.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    BANNER_1 = "BANNER_1"
    BANNER_2 = "BANNER_2"
    BANNER_3 = "BANNER_3"
    BANNER_4 = "BANNER_4"
    BANNER_5 = "BANNER_5"
    BANNER_6 = "BANNER_6"
    BANNER_7 = "BANNER_7"
    BANNER_8 = "BANNER_8"


class AchievementCondition(UnknownTolerantEnum):
    """The condition an achievement parameter names.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    CONDITION_BUY_GLOVES = "CONDITION_BUY_GLOVES"
    CONDITION_BUY_KNIFE = "CONDITION_BUY_KNIFE"
    CONDITION_BUY_PISTOL = "CONDITION_BUY_PISTOL"
    CONDITION_BUY_SMG_OR_RIFLE = "CONDITION_BUY_SMG_OR_RIFLE"
    CONDITION_FULFILLED_TRADE_AMOUNT = "CONDITION_FULFILLED_TRADE_AMOUNT"
    CONDITION_TRADE_AMOUNT = "CONDITION_TRADE_AMOUNT"


class AchievementName(UnknownTolerantEnum):
    """Which achievement a store entry is.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    COMBO_WOMBO = "COMBO_WOMBO"
    ENTRY_FRAG = "ENTRY_FRAG"
    FEBRUARY_MARCH_24_ELITE_TRADER = "FEBRUARY_MARCH_24_ELITE_TRADER"
    FIRST_SELL = "FIRST_SELL"
    FIRST_STEPS = "FIRST_STEPS"
    FORCE_BUY = "FORCE_BUY"
    FULL_BUY = "FULL_BUY"
    JUNE_23_ELITE_TRADER = "JUNE_23_ELITE_TRADER"
    KNIFE_KILL = "KNIFE_KILL"
    MOBILE_DEFUSE_KIT = "MOBILE_DEFUSE_KIT"
    PRO_TRADER = "PRO_TRADER"
    SAFE_HANDS = "SAFE_HANDS"
    SEPTEMBER_23_ELITE_TRADER = "SEPTEMBER_23_ELITE_TRADER"
    VERIFIED_USER = "VERIFIED_USER"


class AchievementStatus(UnknownTolerantEnum):
    """The progress of a store achievement.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    MISSED = "MISSED"
    NOT_STARTED = "NOT_STARTED"


class AchievementKind(UnknownTolerantEnum):
    """How a store achievement is earned.

    A value the schema adds later decodes to a pseudo-member with the raw value
    (`is_unknown`) and is reachable through a raw input until this enum learns it.
    """

    ACTION = "ACTION"
    CHECKLIST = "CHECKLIST"
    LIMIT = "LIMIT"
    PROGRESS = "PROGRESS"


__all__ = [
    "AchievementCondition",
    "AchievementKind",
    "AchievementName",
    "AchievementStatus",
    "CryptoCurrency",
    "CryptoNetwork",
    "DepositStatus",
    "Locale",
    "PaymentProvider",
    "StoreAvatar",
    "StoreBanner",
    "TransactionFeeType",
    "TransactionSortField",
    "TransactionStatus",
    "TransferStatus",
    "WalletMethod",
    "WithdrawalStatus",
]
