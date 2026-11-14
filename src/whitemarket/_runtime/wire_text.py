"""Wire-text facts shared by the live and the export mappers (SDK_SPEC 3.10, 3.11)."""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from whitemarket.models.enums import DeliveryPromise

DIGITS: Final = re.compile(r"[0-9]+")

# Live messages and export rows write the promise as the export window suffix (`10min`), the schema
# as an enum name.
DELIVERY_PROMISES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "10min": DeliveryPromise.MINUTES10.value,
        "1hour": DeliveryPromise.HOUR1.value,
        "12hours": DeliveryPromise.HOURS12.value,
        "24hours": DeliveryPromise.HOURS24.value,
    }
)


def delivery_promise(text: str) -> DeliveryPromise:
    """The promise of its wire text; a value this SDK does not know becomes a pseudo-member."""
    return DeliveryPromise(DELIVERY_PROMISES.get(text, text))


def unmapped(row: Mapping[str, Any], known: frozenset[str]) -> Mapping[str, Any]:
    """The keys of a record that the SDK does not map, read-only."""
    return MappingProxyType({key: value for key, value in row.items() if key not in known})
