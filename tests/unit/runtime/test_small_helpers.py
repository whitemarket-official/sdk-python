"""Pure helpers of the transport: raw document type, log redaction, credential shapes, endpoints."""

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
    ],
)
def test_invalid_endpoints_are_refused(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"must|valid"):
        endpoints.Endpoints.resolve(**kwargs)


def test_the_user_agent_suffix_is_printable_ascii() -> None:
    assert endpoints.require_user_agent_suffix(None) is None
    assert endpoints.require_user_agent_suffix("my-app/1.0") == "my-app/1.0"
    for bad in ("", "tab\t", "café", "a\nb"):
        with pytest.raises(ValueError, match="user_agent_suffix"):
            endpoints.require_user_agent_suffix(bad)
