"""`affiliate_link` (SDK_SPEC 3.10 rule 6)."""

import pytest

from whitemarket.exports import affiliate_link

W = "https://white.market"

CASES: list[tuple[str, str, str, str]] = [
    # (id, link, code, expected)
    ("no query", f"{W}/item/x", "abc", f"{W}/item/x?ref=abc"),
    ("an existing query", f"{W}/x?id=1", "abc", f"{W}/x?id=1&ref=abc"),
    ("an existing ref is replaced", f"{W}/x?ref=old&id=1", "abc", f"{W}/x?id=1&ref=abc"),
    ("every ref is removed", f"{W}/x?a=1&ref=old&b=2&ref=older", "abc", f"{W}/x?a=1&b=2&ref=abc"),
    ("a ref without a value", f"{W}/x?ref", "abc", f"{W}/x?ref=abc"),
    ("a parameter that starts with ref", f"{W}/x?reference=1", "abc", f"{W}/x?reference=1&ref=abc"),
    ("the fragment is kept", f"{W}/x?id=1#details", "abc", f"{W}/x?id=1&ref=abc#details"),
    ("a fragment without a query", f"{W}/x#details", "abc", f"{W}/x?ref=abc#details"),
    ("an empty query mark", f"{W}/x?", "abc", f"{W}/x?ref=abc"),
    ("empty parameters", f"{W}/x?&&a=1&", "abc", f"{W}/x?a=1&ref=abc"),
    ("a subdomain", "https://app.white.market/x", "abc", "https://app.white.market/x?ref=abc"),
    ("a host in capitals", "HTTPS://White.Market/x", "abc", "https://White.Market/x?ref=abc"),
    (
        "a deeper subdomain",
        "https://A.B.WHITE.MARKET/x",
        "abc",
        "https://A.B.WHITE.MARKET/x?ref=abc",
    ),
    (
        "a dash in a label",
        "https://my-shop.white.market/x",
        "a",
        "https://my-shop.white.market/x?ref=a",
    ),
    ("the bare host", W, "abc", f"{W}?ref=abc"),
    ("the code is percent-encoded", f"{W}/x", "a b&c=d#e", f"{W}/x?ref=a%20b%26c%3Dd%23e"),
    (
        "non-ASCII and slash in the code",
        f"{W}/x",
        "\u0436/\u00fc+",
        f"{W}/x?ref=%D0%B6%2F%C3%BC%2B",
    ),
    ("unreserved characters stay", f"{W}/x", "a-b_c.d~e", f"{W}/x?ref=a-b_c.d~e"),
    (
        "an export link",
        f"{W}/item?appId=730&nameHash=AK%20%7C%20x",
        "r1",
        f"{W}/item?appId=730&nameHash=AK%20%7C%20x&ref=r1",
    ),
]


@pytest.mark.parametrize(
    ("link", "code", "expected"), [pytest.param(*c[1:], id=c[0]) for c in CASES]
)
def test_the_ref_parameter_is_set_last_and_the_rest_is_kept(
    link: str, code: str, expected: str
) -> None:
    assert affiliate_link(link, code) == expected


@pytest.mark.parametrize(
    "link",
    [
        pytest.param("https://evil.example.test/x", id="another host"),
        pytest.param("https://notwhite.market/x", id="a lookalike suffix"),
        pytest.param("https://xwhite.market/x", id="a lookalike prefix"),
        pytest.param("https://evil-white.market/x", id="a dash lookalike"),
        pytest.param(
            "https://white.market.evil.example.test/x",
            id="white.market as a subdomain of another host",
        ),
        pytest.param("https://evil.example.test/white.market", id="white.market in the path"),
        pytest.param("https://evil.test?u=white.market", id="white.market in the query"),
        pytest.param("https://evil.test#.white.market", id="white.market in the fragment"),
        pytest.param(
            "https://white.market@evil.example.test/x", id="credentials before another host"
        ),
        pytest.param("https://user@white.market/x", id="credentials with the host"),
        pytest.param("https://user:pw@app.white.market/x", id="credentials with a password"),
        pytest.param("https://white.market:8443/x", id="a port"),
        pytest.param("http://white.market/x", id="plain http"),
        pytest.param("//white.market/x", id="protocol-relative"),
        pytest.param("/item/x", id="a relative path"),
        pytest.param("", id="empty"),
        pytest.param("https://white.market/x y", id="a space in the link"),
        pytest.param("https://white.market/x\n", id="a final line feed"),
        pytest.param("https://white.market/x?a=1\n", id="a final line feed after a query"),
        pytest.param("https://white.market/x#f\n", id="a final line feed after a fragment"),
        pytest.param("https://white.market/x#a\nb", id="a line feed in the fragment"),
        pytest.param("https://\nwhite.market/x", id="a line feed before the host"),
        pytest.param(" https://white.market/x", id="a space before the scheme"),
        pytest.param("xhttps://white.market/x", id="a prefix before the scheme"),
        pytest.param("https://a_b.white.market/x", id="an underscore in a label"),
        pytest.param("https:// app.white.market/x", id="a space before a subdomain"),
        pytest.param("https://white.market/ж", id="a non-ASCII character in the path"),
        pytest.param("https://вhite.market/x", id="a non-ASCII host"),
    ],
)
def test_a_link_outside_white_market_is_refused(link: str) -> None:
    with pytest.raises(ValueError, match="link"):
        affiliate_link(link, "abc")


def test_an_empty_referral_code_is_refused() -> None:
    with pytest.raises(ValueError, match="referral code"):
        affiliate_link("https://white.market/x", "")


def test_the_message_does_not_repeat_the_link() -> None:
    with pytest.raises(ValueError, match="link") as error:
        affiliate_link("https://evil.example.test/?token=SECRET", "abc")

    assert "SECRET" not in str(error.value)
