"""HTTP error body redaction (SDK_SPEC 1.5); cases ported 1:1 from the PHP BodyRedactorTest."""

from typing import cast

import pytest

from whitemarket.errors._redact import redact_body_excerpt

LIMIT = 512

# A synthetic JWT (`{"sub":"SYNTHETIC"}`), split so secret scanners do not flag the fixture.
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiJTWU5USEVUSUMifQ" + ".synthetic-signature"

# Raw strings are used wherever the body holds JSON escapes (a backslash is part of the input).
JSON_BODIES = [
    pytest.param(
        '{"accessToken":"synthetic-access","code":1}',
        '{"accessToken":"***","code":1}',
        id="token field, other fields kept",
    ),
    pytest.param(
        '{"X-Partner-TOKEN" :  "synthetic"}',
        '{"X-Partner-TOKEN":"***"}',
        id="any case, spacing is normalized",
    ),
    pytest.param(
        '{"airwallexSecret":"a","password":"b","Authorization":"c","Set-Cookie":"d","api_key":"e",'
        '"apiKey":"f","jwt":"g","credentials":"h","sessionId":"i"}',
        '{"airwallexSecret":"***","passw***":"***","Authorization":"***","Set-Cookie":"***",'
        '"api_key":"***","apiKey":"***","jwt":"***","credential***":"***","session***":"***"}',
        id="every credential key word",
    ),
    pytest.param(
        r'{"token":"syn\"thetic","ok":true}',
        '{"token":"***","ok":true}',
        id="escaped quote in the value",
    ),
    pytest.param(
        r'{"\u0074oken":"synthetic","p\u0061ssword":"synthetic"}',
        '{"token":"***","passw***":"***"}',
        id="key spelled with a \\u escape",
    ),
    pytest.param(
        '{"cookies":[{"value":"synthetic"}],"tokenExpired":true}',
        '{"cookie***":"***","token***":"***"}',
        id="non-string value under a credential key",
    ),
    pytest.param(
        '{"errors":[{"extensions":{"partnerToken":"synthetic"}}]}',
        '{"errors":[{"extensions":{"partnerToken":"***"}}]}',
        id="nested in GraphQL errors",
    ),
    pytest.param(
        '{"errors":[{"message":"Item not found","path":["market_buy"]}]}',
        '{"errors":[{"message":"Item not found","path":["market_buy"]}]}',
        id="message without a marker kept",
    ),
    pytest.param(
        r'{"error":"bad header Bearer abc\/synthetic","code":1}',
        '{"error":"bad header Bearer***","code":1}',
        id="message cut at a credential word",
    ),
    pytest.param(
        r'{"error":"password=\"synthetic\" rejected"}',
        '{"error":"passw***"}',
        id="quoted pair inside a message",
    ),
    pytest.param(
        r'{"error":"{\"token\":\"synthetic\"}"}',
        r'{"error":"{\"token***"}',
        id="escaped JSON inside a message",
    ),
    pytest.param(
        '{"error":"ctx ' + JWT + ' end"}',
        '{"error":"ctx eyJ***"}',
        id="JWT in a message",
    ),
    pytest.param(
        '{"error":"' + "x" * 470 + JWT + '"}',
        '{"error":"' + "x" * 470 + 'eyJ***"}',
        id="JWT that would cross the excerpt limit",
    ),
    pytest.param(
        '{"url":"/live?cf_connect=synthetic%7B%7D&x=1"}',
        '{"url":"/live?cf_connect***"}',
        id="cf_connect in a message",
    ),
    pytest.param(
        r'{"msg":"literal \\u0041 and \\/"}',
        r'{"msg":"literal \\u0041 and \\/"}',
        id="escape-like text in a value is not decoded twice",
    ),
    pytest.param(
        r'{"message":"upstream: \\u0074oken=synthetic"}',
        '{"message":"upstream: token***"}',
        id="escaped marker in a value",
    ),
    pytest.param(
        r'{"error":"{\"tok\\u0065n\":\"synthetic\"}"}',
        r'{"error":"{\"token***"}',
        id="escaped key in escaped JSON in a value",
    ),
    pytest.param(
        r'{"m":"a \\u005cu0074oken=synthetic"}',
        '{"m":"a token***"}',
        id="escaped backslash before an escaped marker",
    ),
    pytest.param(
        '{"bearer_token":"synthetic","basic_password":"synthetic"}',
        '{"bearer***":"***","basic***":"***"}',
        id="scheme word before a credential word in a key",
    ),
    pytest.param(
        '{"Bearer":"synthetic","cf_connect":1}',
        '{"Bearer":"***","cf_connect":"***"}',
        id="key that is only a marker",
    ),
    pytest.param(
        '{"Bearer synthetic":1,"code":2}',
        '{"Bearer***":"***","code":2}',
        id="marker in a key",
    ),
    pytest.param(
        r'{"\\u0074oken=synthetic":1}',
        '{"token***":"***"}',
        id="escaped credential word in a key",
    ),
    pytest.param(
        '{"scheme":"Bearer"}',
        '{"scheme":"Bearer"}',
        id="marker with nothing after it kept",
    ),
    pytest.param(
        r'{"m":"\\u007basic U1lOVEhFVElD"}',
        '{"m":"{asic***"}',
        id="literal marker whose first letter an escape would swallow, in a value",
    ),
    pytest.param(
        r'{"\\u003cookie":"synthetic"}',
        '{"<ookie":"***"}',
        id="literal marker whose first letter an escape would swallow, in a key",
    ),
    pytest.param(
        r'{"\\u0000tokenX":"synthetic"}',
        r'{"\\u0000token***":"***"}',
        id="escaped control character before a marker in a key",
    ),
    pytest.param(
        r'{"message":"\\\\u007a\\u0070i_key=synthetic"}',
        '{"message":"zpi_key***"}',
        id="marker spelled across an escaped backslash, in a value",
    ),
    pytest.param(
        r'{"\\\\u002b\\u0061sic":"synthetic"}',
        '{"+asic":"***"}',
        id="marker spelled across an escaped backslash, in a key",
    ),
    pytest.param(
        '{"id":12345678901234567890}',
        '{"id":"12345678901234567890"}',
        id="integer beyond 64 bits kept exact",
    ),
    pytest.param(
        '{"data":{},"list":[]}',
        '{"data":{},"list":[]}',
        id="empty object and array kept apart",
    ),
    pytest.param(
        " " * (LIMIT - 20) + '{"token":"synthetic-value-past-the-limit"}',
        '{"token":"***"}',
        id="leading whitespace, value past the limit",
    ),
]

TEXT_BODIES = [
    pytest.param(
        "<html><body>502 Bad Gateway</body></html>",
        "<html><body>502 Bad Gateway</body></html>",
        id="no marker -> kept",
    ),
    pytest.param(
        "upstream said: Bearer synthetic.value-x",
        "upstream said: Bearer***",
        id="bearer header echoed",
    ),
    pytest.param(
        "upstream said: Basic c3ludGhldGlj",
        "upstream said: Basic***",
        id="basic header echoed",
    ),
    pytest.param(
        "Authorization: Bearer synthetic",
        "Authorization***",
        id="authorization header echoed",
    ),
    pytest.param("<p>ctx " + JWT + " end</p>", "<p>ctx eyJ***", id="JWT anywhere"),
    pytest.param(
        "ctx eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJTWU5U", "ctx eyJ***", id="JWT truncated by the server"
    ),
    pytest.param("x" * 500 + JWT, "x" * 500 + "eyJ***", id="JWT cut by the limit"),
    pytest.param(
        "GET /live?cf_connect=synthetic%7B%7D&x=1",
        "GET /live?cf_connect***",
        id="cf_connect query value",
    ),
    pytest.param("<p>token=synthetic&x=1</p>", "<p>token***", id="form-style pair"),
    pytest.param('error: password="synthetic"', "error: passw***", id="double-quoted value"),
    pytest.param("error: token='synthetic'", "error: token***", id="single-quoted value"),
    pytest.param('{password:"synthetic"}', "{passw***", id="unquoted key, quoted value"),
    pytest.param("'api_key' => 'synthetic'", "'api_key***", id="PHP array syntax"),
    pytest.param(
        'Cookie: session="synthetic"', "Cookie***", id="cookie header with a quoted value"
    ),
    pytest.param(
        r'"{\"token\":\"synthetic\"}"',
        '"{"token***',
        id="top-level JSON string holding escaped JSON",
    ),
    pytest.param(
        '<p>{"token":"syn\\\nthetic"}',
        '<p>{"token***',
        id="broken JSON, raw newline after a backslash",
    ),
    pytest.param(
        r'<p>{"\u0074oken":"synthetic"}',
        '<p>{"token***',
        id="broken JSON, key spelled with a \\u escape",
    ),
    pytest.param(
        r'<p>{"m":"\u005cu0074oken=synthetic',
        '<p>{"m":"token***',
        id="broken JSON, escaped backslash before an escaped marker",
    ),
    pytest.param(
        r"err \u007eyJhbGciOiJIUzI1NiJ9.QUJD.c2ln",
        "err ~yJ***",
        id="literal JWT header whose first letter an escape would swallow",
    ),
    pytest.param(
        r"Set: \u003cookie: synthetic",
        "Set: <ookie***",
        id="literal cookie whose first letter an escape would swallow",
    ),
    pytest.param(
        r"error: \\u007a\u0070i_key=synthetic",
        "error: zpi_key***",
        id="marker spelled across an escaped backslash",
    ),
    pytest.param(
        r"a\u0020b token=synthetic",
        "a b token***",
        id="lowest printable escape before a marker decoded",
    ),
    pytest.param(
        r"a\u007Fb token=synthetic",
        "a\x7fb token***",
        id="highest decoded escape before a marker",
    ),
    pytest.param(
        r"a\u001Fb token=synthetic",
        r"a\u001Fb token***",
        id="control escape before a marker kept",
    ),
    pytest.param(
        r"a\u0080b token=synthetic",
        r"a\u0080b token***",
        id="escape past ASCII before a marker kept",
    ),
    pytest.param(
        r'{"error":"{\"token\":\"synthetic\"}"',
        '{"error":"{"token***',
        id="broken JSON, escaped nested object",
    ),
    pytest.param(
        r'<p>{"e":"Bearer abc\/synthetic"}',
        '<p>{"e":"Bearer***',
        id="broken JSON, bearer with an escaped slash",
    ),
    pytest.param(
        " " * (LIMIT - 8) + '<p>{"token":"synthetic"}',
        " " * (LIMIT - 8) + '<p>{"tok',
        id="broken JSON, word crossing the limit",
    ),
    pytest.param(
        "[" * 70 + '{"token":["synthetic"]}' + "]" * 70,
        "[" * 70 + '{"token***',
        id="JSON nested deeper than the decoder allows",
    ),
]

NESTED = "u005c" * 200_000

LARGE_NESTED_ESCAPES = [
    pytest.param(
        r'{"m":"\\' + NESTED + 'u0074oken=synthetic"}',
        (r'{"m":"\\' + NESTED)[:LIMIT],
        id="value",
    ),
    pytest.param(
        r'{"\\' + NESTED + 'u0074oken=synthetic":1}',
        (r'{"\\' + NESTED)[:LIMIT],
        id="key",
    ),
    pytest.param(
        "<p>\\" + NESTED + NESTED + "u0074oken=synthetic</p>",
        ("<p>\\" + NESTED + NESTED)[:LIMIT],
        id="text body",
    ),
]

DOCUMENT_STARTS = [
    pytest.param(
        ' \t\r\n{"token":1,"code":2}',
        '{"token":"***","code":2}',
        id="whitespace before an object -> by structure",
    ),
    pytest.param(
        '[{"token":1},{"code":2}]', '[{"token":"***"},{"code":2}]', id="array -> by structure"
    ),
    pytest.param('"token synthetic"', '"token***', id="scalar JSON -> as text"),
    pytest.param('{"token":"synthetic",}', '{"token***', id="malformed object -> as text"),
    pytest.param("", "", id="empty body"),
    pytest.param(
        r'{"a":"\u0000x token synthetic"}',
        r'{"a":"\u0000x token***',
        id="escaped NUL anywhere -> as text",
    ),
    pytest.param(
        r'{"a":"\\u0000","token":1}',
        r'{"a":"\\u0000","token":"***"}',
        id="escaped backslash before u0000 -> by structure",
    ),
]

INVALID_UTF8 = [
    pytest.param(b"a\xffb", "a\ufffdb", id="invalid byte in the middle -> replacement character"),
    pytest.param(b"a\x80b", "a\ufffdb", id="stray continuation byte -> replacement character"),
    pytest.param(b"a\xc0\xafb", "a\ufffd\ufffdb", id="overlong encoding -> replacement characters"),
    pytest.param(
        b"\x80" * LIMIT,
        "\ufffd" * 170,
        id="replacement characters do not push the excerpt past the limit",
    ),
    pytest.param(b'{"e":"\xff"}', '{"e":"\ufffd"}', id="invalid JSON body is handled as text"),
]

CUTS = [
    pytest.param(
        "a" * (LIMIT - 1) + "\u00e9tail",
        "a" * (LIMIT - 1),
        id="2-byte char across the limit -> dropped",
    ),
    pytest.param(
        "a" * (LIMIT - 2) + "\u20actail", "a" * (LIMIT - 2), id="3-byte char, 2 bytes in -> dropped"
    ),
    pytest.param(
        "a" * (LIMIT - 3) + "\U0001f600tail",
        "a" * (LIMIT - 3),
        id="4-byte char, 3 bytes in -> dropped",
    ),
    pytest.param(
        "a" * (LIMIT - 2) + "\u00e9tail",
        "a" * (LIMIT - 2) + "\u00e9",
        id="2-byte char ending at the limit -> kept",
    ),
    pytest.param(
        "a" * (LIMIT - 4) + "\U0001f600tail",
        "a" * (LIMIT - 4) + "\U0001f600",
        id="4-byte char ending at the limit -> kept",
    ),
    pytest.param("a" * LIMIT, "a" * LIMIT, id="exactly the limit -> whole"),
]


def _redact(body: str | bytes) -> str:
    return redact_body_excerpt(body.encode() if isinstance(body, str) else body)


@pytest.mark.parametrize(("body", "expected"), JSON_BODIES)
def test_redacts_json_by_key_and_cuts_strings_at_a_credential_marker(
    body: str, expected: str
) -> None:
    assert _redact(body) == expected


@pytest.mark.parametrize(("body", "expected"), TEXT_BODIES)
def test_cuts_text_at_the_first_credential_marker(body: str, expected: str) -> None:
    assert _redact(body) == expected


def test_redacts_a_json_body_too_large_to_decode_as_text() -> None:
    body = '{"token":["synthetic"],"pad":"' + "x" * (2 * 1024 * 1024) + '"}'

    assert _redact(body) == '{"token***'


def test_keeps_the_json_structure_when_a_long_value_is_cut_inside_a_character() -> None:
    body = '{"tokenId":"x","pad":"a' + "\u00e9" * 300 + '"}'

    assert _redact(body).startswith('{"token***":"***","pad":"a\u00e9')


@pytest.mark.parametrize(("body", "expected"), LARGE_NESTED_ESCAPES)
def test_decodes_escapes_nested_through_a_large_input_only_up_to_the_limit(
    body: str, expected: str
) -> None:
    assert _redact(body) == expected


@pytest.mark.parametrize(("body", "expected"), DOCUMENT_STARTS)
def test_decodes_only_a_json_object_or_array(body: str, expected: str) -> None:
    assert _redact(body) == expected


def test_redacts_a_json_body_of_exactly_the_decode_limit_by_structure() -> None:
    prefix = '{"tokenId":"x","pad":"'
    body = prefix + "x" * (1024 * 1024 - len(prefix) - 2) + '"}'

    assert len(body) == 1024 * 1024
    assert _redact(body).startswith('{"token***":"***","pad":"x')


@pytest.mark.parametrize(("body", "expected"), INVALID_UTF8)
def test_returns_valid_utf8(body: bytes, expected: str) -> None:
    excerpt = _redact(body)

    assert excerpt == expected
    assert len(excerpt.encode()) <= LIMIT


@pytest.mark.parametrize(("body", "expected"), CUTS)
def test_cuts_at_the_limit_without_splitting_a_character(body: str, expected: str) -> None:
    assert _redact(body) == expected


# Cases beyond the PHP suite: Python's JSON decoder differs from PHP's, each difference is pinned.

PYTHON_SPECIFIC = [
    pytest.param(
        '{"price":1.50,"rate":1e2,"n":-0.0}',
        '{"price":1.50,"rate":1e2,"n":-0.0}',
        id="floats keep their original text",
    ),
    pytest.param(
        '{"a":NaN,"token":"synthetic"}', '{"a":NaN,"token***', id="NaN is not JSON -> as text"
    ),
    pytest.param(
        '{"a":-Infinity,"token":"synthetic"}',
        '{"a":-Infinity,"token***',
        id="Infinity is not JSON -> as text",
    ),
    pytest.param(
        '{"a":1,"a":2,"token":3,"token":4}',
        '{"a":2,"token":"***"}',
        id="duplicate keys: the later value wins",
    ),
    pytest.param(
        '{"k":"1","tokenA":1,"tokenB":2}',
        '{"k":"1","token***":"***"}',
        id="keys that collide after redaction merge",
    ),
    pytest.param(
        r'{"a":"\ud800","token":"synthetic"}',
        r'{"a":"\ud800","token***',
        id="lone surrogate escape -> as text",
    ),
    pytest.param(
        r'{"a":"\ud83d\ude00"}', '{"a":"\U0001f600"}', id="surrogate pair decoded and written raw"
    ),
    pytest.param(
        '{"a":"x\u2028y\u2029z"}',
        '{"a":"x\\u2028y\\u2029z"}',
        id="line separators stay escaped",
    ),
    pytest.param(
        r'{"a":"tab\there\u001f\u007f\n","b":"q\"s\\"}',
        r'{"a":"tab\there\u001f' + "\x7f" + r'\n","b":"q\"s\\"}',
        id="control characters re-escaped, DEL and slash raw",
    ),
    pytest.param('{"a":"x/y"}', '{"a":"x/y"}', id="slash is not escaped"),
    pytest.param(
        '{"a":"caf\u00e9 \u20ac"}', '{"a":"caf\u00e9 \u20ac"}', id="non-ASCII is not escaped"
    ),
    pytest.param(
        '{"n":-9223372036854775808,"m":9223372036854775807,"o":9223372036854775808,"p":-9223372036854775809}',
        '{"n":-9223372036854775808,"m":9223372036854775807,"o":"9223372036854775808","p":"-9223372036854775809"}',
        id="64-bit integer boundary",
    ),
    pytest.param("[]", "[]", id="empty array"),
    pytest.param('{"a":[true,false,null]}', '{"a":[true,false,null]}', id="literals kept"),
    pytest.param(b'\xef\xbb\xbf{"token":1}', '\ufeff{"token***', id="BOM -> as text"),
]


@pytest.mark.parametrize(("body", "expected"), PYTHON_SPECIFIC)
def test_matches_the_php_decoder_where_python_json_differs(
    body: str | bytes, expected: str
) -> None:
    assert _redact(body) == expected


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        pytest.param(64, "[" * 63 + '{"token":"***"}' + "]" * 63, id="64 levels -> by structure"),
        pytest.param(65, "[" * 64 + '{"token***', id="65 levels -> as text"),
    ],
)
def test_json_depth_limit_is_64(depth: int, expected: str) -> None:
    body = "[" * (depth - 1) + '{"token":1}' + "]" * (depth - 1)

    assert _redact(body) == expected


def test_a_json_body_one_byte_over_the_decode_limit_is_redacted_as_text() -> None:
    prefix = '{"tokenId":"x","pad":"'
    body = prefix + "x" * (1024 * 1024 - len(prefix) - 1) + '"}'

    assert len(body) == 1024 * 1024 + 1
    assert _redact(body) == '{"token***'


def test_brackets_inside_strings_do_not_count_towards_depth() -> None:
    body = '{"a":"' + "[" * 100 + '","token":1}'

    assert _redact(body) == '{"a":"' + "[" * 100 + '","token":"***"}'


def test_any_failure_yields_an_empty_excerpt_never_the_input() -> None:
    # A non-bytes body (a contract violation) fails inside the redactor: the excerpt is empty.
    assert redact_body_excerpt(cast(bytes, None)) == ""
    assert redact_body_excerpt(cast(bytes, 'token="synthetic"')) == ""
