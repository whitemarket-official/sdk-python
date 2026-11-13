"""HTTP error body redaction (SDK_SPEC 1.5), a port of the PHP SDK's `BodyRedactor`.

The excerpt is at most 512 bytes of valid UTF-8 (invalid bytes become U+FFFD). Credentials the
body may echo become `***`. A JSON object or array body is redacted by structure: every key and
every string value is redacted as text, and the value under a key that holds a credential marker
is masked whatever its type. Anything else (not JSON, too deep, too large) is redacted as text.
Text is cut after its first credential marker, searched as given and after each pass of JSON
unescaping, so a secret after a marker never survives, whatever its format.

Not detected, by design (owner decision 2026-10-31): a secret with no marker before it in the same
string or key, including a credential in a JSON value whose marker is in a sibling value
(`{"name": "Cookie", "value": "..."}`). Each string is redacted on its own to keep the rest of the
error body readable.

Everything works on bytes: markers are ASCII, and no Unicode case folding may widen them.
"""

import json
import re
from typing import Final, cast

from whitemarket._runtime.secret import MASK

EXCERPT_BYTES: Final = 512

_MASK: Final = MASK.encode()
_JSON_MAX_BYTES: Final = 1024 * 1024
_JSON_MAX_DEPTH: Final = 64
_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1
_INT64_DIGITS: Final = 19
_FIRST_PRINTABLE: Final = 0x20
_DEL: Final = 0x7F

_MARKER: Final = re.compile(
    rb"token|secret|passw|authori[sz]ation|cookie|api[_-]?key|jwt|credential|session"
    rb"|bearer|basic|eyJ|cf_connect",
    re.IGNORECASE,
)
# One JSON escape that can spell a marker letter: `\uXXXX`, or an escaped quote, backslash or slash.
_ESCAPE: Final = re.compile(rb'\\(?:u(?P<code>[0-9A-Fa-f]{4})|(?P<char>["\\/]))')
# A JSON `\u0000` escape not preceded by an escaped backslash (an odd run of backslashes before it).
_ESCAPED_NUL: Final = re.compile(rb"(?<!\\)(?:\\\\)*\\u0000")
# Tokens for the depth scan: a whole string literal, or a bracket.
_DEPTH_TOKEN: Final = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]', re.DOTALL)

_VALID_UTF8_SEQUENCE: Final = re.compile(
    rb"[\x00-\x7F]|[\xC2-\xDF][\x80-\xBF]|\xE0[\xA0-\xBF][\x80-\xBF]"
    rb"|[\xE1-\xEC\xEE\xEF][\x80-\xBF]{2}|\xED[\x80-\x9F][\x80-\xBF]|\xF0[\x90-\xBF][\x80-\xBF]{2}"
    rb"|[\xF1-\xF3][\x80-\xBF]{3}|\xF4[\x80-\x8F][\x80-\xBF]{2}"
)
_INCOMPLETE_TAIL: Final = re.compile(
    rb"(?:[\xC2-\xDF]|[\xE0-\xEF][\x80-\xBF]?|[\xF0-\xF4][\x80-\xBF]{0,2})\Z"
)
_FFFD: Final = "\ufffd".encode()

_JSON_ESCAPES: Final = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}
_NEEDS_ESCAPE: Final = re.compile(r'["\\\x00-\x1f\u2028\u2029]')


class _RawNumber(str):
    """A JSON float, kept as its original text so re-encoding cannot change it."""

    __slots__ = ()


class _NotJsonError(Exception):
    """The body is not a JSON object or array the redactor can decode: it is redacted as text."""


def redact_body_excerpt(body: bytes) -> str:
    """Return the start of an HTTP error body, safe to log.

    At most 512 bytes of valid UTF-8; any failure yields an empty string, never unredacted text.
    """
    try:
        redacted = _redact_json(body)
        if redacted is None:
            redacted = _cut_at_first_marker(body)[0]
        # A replacement character is longer than the byte it replaces: cut after replacing.
        cut = _valid_utf8(_valid_utf8(redacted)[:EXCERPT_BYTES])
        return cut.decode()
    except Exception:
        # Whatever fails, the unredacted text must not leak (SDK_SPEC 1.5).
        return ""


def _redact_json(body: bytes) -> bytes | None:
    if len(body) > _JSON_MAX_BYTES or not _is_safe_to_decode(body):
        return None
    try:
        data = _decode_json(body)
        return _encode(_redact_value(data)).encode()
    except (_NotJsonError, ValueError, RecursionError):
        return None


def _is_safe_to_decode(body: bytes) -> bool:
    stripped = body.lstrip(b" \t\n\r")
    if stripped[:1] not in (b"{", b"[") or _ESCAPED_NUL.search(body) is not None:
        return False
    return _depth_within_limit(body)


def _depth_within_limit(body: bytes) -> bool:
    depth = 0
    for token in _DEPTH_TOKEN.finditer(body):
        char = token.group()
        if char in (b"[", b"{"):
            depth += 1
            if depth > _JSON_MAX_DEPTH:
                return False
        elif char in (b"]", b"}"):
            depth -= 1
    return True


def _decode_json(body: bytes) -> object:
    def parse_int(text: str) -> int | str:
        digits = text.lstrip("-")
        if len(digits) > _INT64_DIGITS:
            return text
        value = int(text)
        return value if _INT64_MIN <= value <= _INT64_MAX else text

    def parse_float(text: str) -> str:
        return _RawNumber(text)

    def reject_constant(name: str) -> object:
        raise _NotJsonError(name)  # NaN, Infinity: not JSON

    def parse_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        return dict(pairs)  # a later duplicate wins, at the position of the first

    data = json.loads(
        body.decode("utf-8"),
        parse_int=parse_int,
        parse_float=parse_float,
        parse_constant=reject_constant,
        object_pairs_hook=parse_object,
    )
    if not isinstance(data, (dict, list)):
        raise _NotJsonError
    return cast("object", data)


def _redact_value(value: object) -> object:
    if isinstance(value, _RawNumber):
        return value
    if isinstance(value, str):
        return _lossy_text(_cut_at_first_marker(_strict_utf8(value))[0])
    if isinstance(value, list):
        return [_redact_value(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in cast("dict[str, object]", value).items():
            name, marked = _cut_at_first_marker(_strict_utf8(key))
            redacted[_lossy_text(name)] = MASK if marked else _redact_value(item)
        return redacted
    return value


def _strict_utf8(text: str) -> bytes:
    # A lone surrogate (`\ud800`) is invalid JSON for PHP: the body is then redacted as text.
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _NotJsonError from error


def _lossy_text(text: bytes) -> str:
    return _replace_invalid(text).decode()


def _encode(value: object) -> str:
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, (_RawNumber, int)):
        return str(value)
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in cast("list[object]", value)) + "]"
    if isinstance(value, dict):
        members = cast("dict[str, object]", value).items()
        return (
            "{" + ",".join(f"{_encode_string(key)}:{_encode(item)}" for key, item in members) + "}"
        )
    raise _NotJsonError


def _encode_string(text: str) -> str:
    def escape(match: re.Match[str]) -> str:
        char = match.group()
        # Control characters and the line separators (as PHP does) use the `\\uXXXX` form.
        return _JSON_ESCAPES.get(char) or f"\\u{ord(char):04x}"

    return '"' + _NEEDS_ESCAPE.sub(escape, text) + '"'


def _cut_at_first_marker(text: bytes) -> tuple[bytes, bool]:
    """Keep the text up to the first credential marker (inclusive) and replace the rest with `***`.

    Cutting instead of matching value formats means no quoting, escaping or nesting of the value
    can carry it past the redaction. The text is cut to the limit first, so no byte past it can
    reach the excerpt.

    The marker is searched in the text as given and again after every pass of escape decoding, and
    the text is cut at each stage it shows up in: decoding can neither hide a marker
    (`\\u005cu0074oken` -> `\\u0074oken` -> `token`) nor swallow the first letter of a literal one
    (`\\u007eyJ` -> `~yJ`). Every pass shortens the text or ends the loop. Text with no marker at
    any stage is returned as given; nothing after the marker means no `***`.

    Returns the redacted text and whether it held a marker.
    """
    text = text[:EXCERPT_BYTES]
    current = text
    marked = False
    cut = False
    while True:
        match = _MARKER.search(current)
        if match is not None:
            end = match.end()
            marked = True
            cut = cut or end < len(current)
            current = current[:end]
        previous = current
        current = _decode_escapes(current)
        if current == previous:
            break
    if not marked:
        return text, False
    return (current + _MASK if cut else current), True


def _decode_escapes(text: bytes) -> bytes:
    """One pass of JSON string unescaping, as a consumer decoding the excerpt reads it.

    `\\\\`, `\\"`, `\\/` and `\\uXXXX` from U+0020 to U+007F are decoded, each escape read left to
    right as one unit, so an escaped backslash never starts an escape of its own. Other escapes
    cannot spell a marker and stay as they are; a decoded control character such as NUL would be
    an invalid property name.
    """

    def decode(match: re.Match[bytes]) -> bytes:
        char = match.group("char")
        if char is not None:
            return char
        code_point = int(match.group("code"), 16)
        return bytes((code_point,)) if _FIRST_PRINTABLE <= code_point <= _DEL else match.group()

    return _ESCAPE.sub(decode, text)


def _valid_utf8(text: bytes) -> bytes:
    """Drop a character cut by the limit, then replace every remaining invalid byte with U+FFFD."""
    return _replace_invalid(_INCOMPLETE_TAIL.sub(b"", text, count=1))


def _replace_invalid(text: bytes) -> bytes:
    try:
        text.decode("utf-8")
    except UnicodeDecodeError:
        return _replace_invalid_slow(text)
    return text


def _replace_invalid_slow(text: bytes) -> bytes:
    out = bytearray()
    position = 0
    while position < len(text):
        sequence = _VALID_UTF8_SEQUENCE.match(text, position)
        if sequence is None:
            out += _FFFD  # one replacement per invalid byte, as the PHP SDK does
            position += 1
        else:
            out += sequence.group()
            position = sequence.end()
    return bytes(out)
