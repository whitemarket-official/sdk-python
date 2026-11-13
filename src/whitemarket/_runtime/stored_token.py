"""An access token and the moment it expires, as a `TokenStore` keeps it."""

from datetime import datetime
from typing import NamedTuple

from whitemarket._runtime.secret import Secret


class StoredToken(NamedTuple):
    """`(token, expires_at)`; `expires_at` is timezone-aware."""

    token: Secret
    expires_at: datetime
