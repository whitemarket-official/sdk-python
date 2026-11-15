"""Pure helpers of the transport: raw document type, log redaction, credential shapes, endpoints."""

import httpx
import pytest

from whitemarket._runtime import endpoints
from whitemarket._runtime.credential_format import is_valid_bearer_token, is_valid_header_value
from whitemarket._runtime.log_redaction import redact_headers, redact_url
from whitemarket._runtime.operation import infer_operation_type


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("query Ping { test_ping }", "query", id="named query"),
        pytest.param("{ test_ping }", "query", id="shorthand"),
        pytest.param("﻿  # c\n, query { a }", "query", id="BOM, comment, comma, query"),
        pytest.param("mutation M { x }", "mutation", id="mutation"),
        pytest.param("query Q { a } mutation M { b }", "mutation", id="a second operation"),
        pytest.param("query Q { a } # mutation later", "mutation", id="word in a comment"),
        pytest.param("fragment F on T { a } query Q { ...F }", "mutation", id="fragment first"),
        pytest.param("subscription S { a }", "mutation", id="subscription"),
        pytest.param("", "mutation", id="empty"),
        pytest.param("garbage", "mutation", id="not graphql"),
        pytest.param("queryX { a }", "mutation", id="query as a prefix of a name"),
    ],
)
def test_only_a_clear_query_is_a_query(document: str, expected: str) -> None:
    assert infer_operation_type(document) == expected


def test_headers_are_redacted_by_allow_list() -> None:
    shown = redact_headers(
        {
            "Authorization": "Bearer eyJsecret",
            "X-partner-token": "partner-secret",
            "x-future-credential": "who-knows",
            "Content-Type": "application/json",
            "user-agent": "ua/1",
        }
    )

    assert shown == {
        "Authorization": "***",
        "X-partner-token": "***",
        "x-future-credential": "***",
        "Content-Type": "application/json",
        "user-agent": "ua/1",
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param(
            "https://api.example/sse_endpoint?cf_connect=%7B%22token%22%3A%22abc%22%7D",
            "https://api.example/sse_endpoint?cf_connect=***",
            id="cf_connect",
        ),
        pytest.param(
            "https://u:p@h.example:8443/p?a=1&b=2",
            "https://h.example:8443/p?a=***&b=***",
            id="userinfo and every value",
        ),
        pytest.param("https://h.example/p", "https://h.example/p", id="nothing to hide"),
        pytest.param("https://h.example/p?flag", "https://h.example/p?flag", id="valueless key"),
    ],
)
def test_urls_lose_user_information_and_every_query_value(url: str, expected: str) -> None:
    assert redact_url(url) == expected


@pytest.mark.parametrize(
    ("value", "header_ok", "bearer_ok"),
    [
        pytest.param("abc.def-ghi_jkl~+/==", True, True, id="b64token"),
        pytest.param("with space", True, False, id="inner space"),
        pytest.param(" lead", False, False, id="leading space"),
        pytest.param("trail ", False, False, id="trailing space"),
        pytest.param("new\nline", False, False, id="newline"),
        pytest.param("tab\tx", False, False, id="tab"),
        pytest.param("trail\n", False, False, id="trailing newline"),
        pytest.param("", False, False, id="empty"),
        pytest.param("café", False, False, id="non-ascii"),
        pytest.param("a=b=", True, False, id="equals inside"),
    ],
)
def test_credential_shapes(value: str, header_ok: bool, bearer_ok: bool) -> None:
    assert is_valid_header_value(value) is header_ok
    assert is_valid_bearer_token(value) is bearer_ok


def test_endpoints_default_to_the_partner_api_and_derive_the_live_urls() -> None:
    resolved = endpoints.Endpoints.resolve()

    assert resolved.graphql_url == "https://api.white.market/graphql/partner"
    assert resolved.sse_url == "https://api.white.market/sse_endpoint"
    assert resolved.ws_url == "wss://api.white.market/ws_endpoint"
    assert resolved.export_base_url == "https://export.white.market"


def test_a_base_url_moves_the_derived_live_urls_and_drops_a_trailing_slash() -> None:
    resolved = endpoints.Endpoints.resolve(
        base_url="https://staging.example:8443/", graphql_path="/g"
    )

    assert resolved.graphql_url == "https://staging.example:8443/g"
    assert resolved.sse_url == "https://staging.example:8443/sse_endpoint"
    assert resolved.ws_url == "wss://staging.example:8443/ws_endpoint"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"base_url": "http://api.example"}, id="plain http base"),
        pytest.param({"base_url": "https://api.example/path"}, id="base with a path"),
        pytest.param({"base_url": "https://api.example?x=1"}, id="base with a query"),
        pytest.param({"base_url": "https://user:pw@api.example"}, id="base with credentials"),
        pytest.param({"base_url": "ftp://api.example"}, id="other scheme"),
        pytest.param({"base_url": "api.example"}, id="no scheme"),
        pytest.param({"base_url": ""}, id="empty base"),
        pytest.param({"base_url": "https://api.example\n"}, id="newline"),
        pytest.param({"graphql_path": "graphql"}, id="path without slash"),
        pytest.param({"graphql_path": "/g?x=1"}, id="path with a query"),
        pytest.param({"export_base_url": "http://export.example"}, id="plain http export"),
        pytest.param({"sse_url": ""}, id="empty sse url"),
        pytest.param({"ws_url": ""}, id="empty ws url"),
        pytest.param({"sse_url": "http://api.example/sse"}, id="plain http sse"),
        pytest.param({"ws_url": "ws://api.example/ws"}, id="plain ws"),
        pytest.param({"ws_url": "https://api.example/ws"}, id="https as ws"),
        pytest.param({"sse_url": "https://u:p@api.example/sse"}, id="sse with credentials"),
        pytest.param({"sse_url": "https://api.example:badport/sse"}, id="bad port"),
        # An empty fragment is falsy in `urlsplit`; the connect query would land in it.
        pytest.param({"sse_url": "https://api.example/sse#"}, id="sse with an empty fragment"),
        pytest.param({"ws_url": "wss://api.example/ws#"}, id="ws with an empty fragment"),
    ],
)
def test_invalid_endpoints_are_refused(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"must|valid"):
        endpoints.Endpoints.resolve(**kwargs)


_ENDPOINT_TEMPLATES = [
    ("base_url", "https://api.example{}"),
    ("graphql_path", "/graphql{}"),
    ("export_base_url", "https://export.example{}"),
    ("sse_url", "https://api.example/sse{}"),
    ("ws_url", "wss://api.example/ws{}"),
]

_NOT_PRINTABLE_ASCII_CASES = [
    pytest.param(name, template.format(character), id=f"{name} with {label} -> refused")
    for name, template in _ENDPOINT_TEMPLATES
    for label, character in [
        ("NUL", "\x00"),
        ("unit separator 0x1F", "\x1f"),
        ("DEL 0x7F", "\x7f"),
        ("tab", "\t"),  # `urlsplit` drops a tab silently, httpx refuses it
        ("U+0080", "\x80"),
        ("next line U+0085", "\x85"),
        ("no-break space U+00A0", "\xa0"),
        ("letter U+00E9", "\xe9"),
        ("line separator U+2028", "\u2028"),
        ("BOM U+FEFF", "\ufeff"),
        ("emoji", "\U0001f600"),
        ("lone surrogate", "\ud800"),
    ]
]


@pytest.mark.parametrize(("name", "value"), _NOT_PRINTABLE_ASCII_CASES)
def test_an_endpoint_outside_printable_ascii_is_refused(name: str, value: str) -> None:
    # httpx refuses most of these only when it builds a request, and for SSE that request holds
    # the live token; refusing them here also stops a live session retrying a URL that cannot work.
    with pytest.raises(ValueError, match=f"^{name} must be printable ASCII"):
        endpoints.Endpoints.resolve(**{name: value})


def test_the_printable_ascii_boundaries_are_accepted_in_an_endpoint() -> None:
    resolved = endpoints.Endpoints.resolve(sse_url="https://api.example/sse~", graphql_path="/g~!")
    assert (resolved.sse_url, resolved.graphql_path) == ("https://api.example/sse~", "/g~!")


# The URL options; "{}" stands for the host with its port.
_URL_OPTION_TEMPLATES = [
    ("base_url", "https://{}"),
    ("export_base_url", "https://{}"),
    ("sse_url", "https://{}/sse"),
    ("ws_url", "wss://{}/ws"),
]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param(name, value, id=f"{name}: {label} -> refused")
        for name, template in _URL_OPTION_TEMPLATES
        for label, value in [
            ("letters in the port", template.format("api.example:44a3")),
            ("IPv4 out of range", template.format("999.999.999.999")),
            ("A-label that is not punycode", template.format("xn--zz")),
            # httpx builds these and fails only at connect; urlsplit and websockets refuse the
            # first three, and websockets reads port 0 as 443 while httpx connects to port 0.
            # For a base URL the derived WS URL inherits the port.
            ("port 65536", template.format("api.example:65536")),
            ("port 99999", template.format("api.example:99999")),
            ("a signed port", template.format("api.example:+443")),
            ("port 0", template.format("api.example:0")),
            ("port 0 zero-padded", template.format("api.example:00")),
        ]
    ],
)
def test_an_endpoint_the_http_library_cannot_build_a_request_for_is_refused(
    name: str, value: str
) -> None:
    with pytest.raises(ValueError, match=f"^{name} is not a valid URL$"):
        endpoints.Endpoints.resolve(**{name: value})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param(
            name, template.format(f"api.example:{port}"), id=f"{name}: {label} -> accepted"
        )
        for name, template in _URL_OPTION_TEMPLATES
        for label, port in [
            ("port 1", "1"),
            ("port 65535", "65535"),
            # PHP refuses the next two (its HTTP layers disagree on them). httpx, urlsplit and
            # websockets all read them as the default port 443, so they are usable here.
            ("an empty port", ""),
            ("a zero-padded port", "000443"),
        ]
    ],
)
def test_an_endpoint_with_a_port_every_http_layer_reads_alike_is_accepted(
    name: str, value: str
) -> None:
    resolved = endpoints.Endpoints.resolve(**{name: value})
    assert getattr(resolved, name) == value


_MAX = endpoints.MAX_ENDPOINT_LENGTH


def _of_length(name: str, length: int) -> str:
    """A valid value of option `name` exactly `length` characters long."""
    prefix, suffix = {
        "base_url": ("https://", ".example"),
        "export_base_url": ("https://", ".example"),
        "graphql_path": ("/", ""),
        "sse_url": ("https://api.example/", ""),
        "ws_url": ("wss://api.example/", ""),
    }[name]
    return prefix + "a" * (length - len(prefix) - len(suffix)) + suffix


_OPTIONS = [name for name, _ in _ENDPOINT_TEMPLATES]


@pytest.mark.parametrize("name", _OPTIONS)
def test_an_endpoint_one_character_over_the_length_limit_is_refused(name: str) -> None:
    # Each part passes httpx on its own, but the URL the SDK builds from it (base + path, SSE URL
    # + connect query with the token) would exceed httpx's 65536 limit and fail on every call.
    with pytest.raises(ValueError, match=f"^{name} must be at most {_MAX} characters$"):
        endpoints.Endpoints.resolve(**{name: _of_length(name, _MAX + 1)})


def test_every_url_built_from_endpoints_at_the_length_limit_can_be_requested() -> None:
    resolved = endpoints.Endpoints.resolve(**{name: _of_length(name, _MAX) for name in _OPTIONS})
    derived = endpoints.Endpoints.resolve(base_url=_of_length("base_url", _MAX))
    connect_query = "?cf_connect=" + "%7B" * 5000  # a percent-encoded token and subs, generous
    urls = [
        resolved.graphql_url,
        resolved.export_base_url + "/v1/market_history/2147483647_24h.jsonl",
        resolved.sse_url + connect_query,
        resolved.ws_url,
        derived.graphql_url,
        derived.sse_url + connect_query,
        derived.ws_url,
    ]
    assert all(len(_of_length(name, _MAX)) == _MAX for name in _OPTIONS)
    for url in urls:
        httpx.Request("GET", url)  # raises InvalidURL ("URL too long") over httpx's limit


def test_an_internationalised_host_in_its_ascii_form_is_accepted() -> None:
    resolved = endpoints.Endpoints.resolve(base_url="https://xn--bcher-kva.example")
    assert resolved.ws_url == "wss://xn--bcher-kva.example/ws_endpoint"


def test_the_user_agent_suffix_is_printable_ascii() -> None:
    assert endpoints.require_user_agent_suffix(None) is None
    assert endpoints.require_user_agent_suffix("my-app/1.0") == "my-app/1.0"
    for bad in ("", "tab\t", "café", "a\nb"):
        with pytest.raises(ValueError, match="user_agent_suffix"):
            endpoints.require_user_agent_suffix(bad)
