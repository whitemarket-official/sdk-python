"""Affiliate links (SDK_SPEC 3.10 rule 6, WHITEMARKET_API.md 10)."""

import re
from urllib.parse import quote

_DOMAIN = "white.market"
# scheme, host (up to the first / ? #), path, query, fragment; the whole link is printable ASCII
# without spaces
_LINK = re.compile(r"https://([^/?#]+)([^?#]*)(?:\?([^#]*))?(?:#(.*))?", re.IGNORECASE)
_PRINTABLE = re.compile(r"[\x21-\x7E]+")
_HOST = re.compile(r"[a-z0-9.-]+")


def affiliate_link(link: str, referral_code: str) -> str:
    """Return `link` with its `ref` query parameter set to `referral_code`.

    Only an https link on `white.market` or a subdomain is accepted (no port, no credentials);
    anything else is a `ValueError`, so a code is never attached to a foreign URL. An existing `ref`
    is removed, the new one is percent-encoded and goes last; the fragment is kept.
    """
    if not referral_code:
        raise ValueError("the referral code must not be empty")
    match = _LINK.fullmatch(link) if _PRINTABLE.fullmatch(link) else None
    if match is None:
        raise ValueError("the link is not an https URL")
    authority, path, query, fragment = match.groups()
    host = authority.lower()
    if not (host == _DOMAIN or host.endswith("." + _DOMAIN)) or not _HOST.fullmatch(host):
        raise ValueError(f"the link must point to {_DOMAIN} or a subdomain of it")
    parameters = [
        part for part in (query or "").split("&") if part and part.split("=", 1)[0] != "ref"
    ]
    parameters.append("ref=" + quote(referral_code, safe=""))
    suffix = "" if fragment is None else "#" + fragment
    return f"https://{authority}{path}?{'&'.join(parameters)}{suffix}"
