"""The delivery-time window of an export file (SDK_SPEC 3.10)."""

from enum import Enum


class ExportWindow(Enum):
    """Sellers' delivery promise a file is limited to; the value is the URL suffix of the file
    name."""

    ALL = ""
    MINUTES10 = ".10min"
    HOUR1 = ".1hour"
    HOURS12 = ".12hours"
    HOURS24 = ".24hours"

    @property
    def suffix(self) -> str:
        """The text between the app id and the extension (`730` + `.1hour` + `.json`)."""
        return str(self.value)
