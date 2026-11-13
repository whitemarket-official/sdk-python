"""`Secret` (SDK_SPEC 8): a value that never prints."""

import copy
import logging

import pytest
from pydantic import BaseModel, ValidationError

from whitemarket import Secret

VALUE = "synthetic-partner-token-7f3a"


class Holder(BaseModel):
    token: Secret


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(str, id="str"),
        pytest.param(repr, id="repr"),
        pytest.param(format, id="format"),
        pytest.param(lambda s: f"{s}", id="f-string"),
        pytest.param(lambda s: f"{s!r}", id="f-string-repr"),
        pytest.param(lambda s: f"{s:>20}", id="f-string-with-spec"),
        pytest.param(lambda s: str([s]), id="inside-a-list"),
        pytest.param(lambda s: str({"k": s}), id="inside-a-dict"),
    ],
)
def test_every_rendering_is_masked(render: object) -> None:
    rendered = render(Secret(VALUE))

    assert "***" in rendered
    assert VALUE not in rendered


def test_reveal_is_the_only_way_out() -> None:
    assert Secret(VALUE).reveal() == VALUE


def test_a_log_record_does_not_carry_the_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        logging.getLogger("x").info("token=%s", Secret(VALUE))

    assert VALUE not in caplog.text


def test_the_object_is_immutable() -> None:
    secret = Secret(VALUE)

    with pytest.raises(AttributeError):
        secret._value = "other"
    with pytest.raises(AttributeError):
        secret.extra = 1
    with pytest.raises(AttributeError):
        del secret._value

    assert secret.reveal() == VALUE


@pytest.mark.parametrize(
    "bad", [None, 5, b"bytes", Secret("x")], ids=["none", "int", "bytes", "secret"]
)
def test_only_a_str_can_be_wrapped(bad: object) -> None:
    with pytest.raises(TypeError):
        Secret(bad)


def test_an_empty_secret_is_allowed_and_masked() -> None:
    # The value is opaque; "no credential" is the caller's configuration check, not the wrapper's.
    empty = Secret("")

    assert empty.reveal() == ""
    assert str(empty) == "***"
    assert empty == Secret("")
    assert bool(empty) is True, "no truthiness trap: an empty credential is still a Secret"


def test_equality_is_by_value_and_only_between_secrets() -> None:
    assert Secret(VALUE) == Secret(VALUE)
    assert Secret(VALUE) != Secret(VALUE + "x")
    assert Secret(VALUE) != VALUE, "a Secret is not equal to the plain string"
    assert Secret(VALUE) != VALUE
    assert Secret("é") == Secret("é"), "non-ASCII values compare too"


def test_the_hash_is_consistent_with_equality() -> None:
    assert hash(Secret(VALUE)) == hash(Secret(VALUE))
    assert {Secret(VALUE): 1}[Secret(VALUE)] == 1
    assert len({Secret(VALUE), Secret(VALUE), Secret("other")}) == 2


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        pytest.param("abc", "abc", True, id="same"),
        pytest.param("abc", "abd", False, id="last char differs"),
        pytest.param("abc", "abcd", False, id="a prefix"),
        pytest.param("", "", True, id="both empty"),
        pytest.param("\ud800x", "\ud800x", True, id="lone surrogate, same"),
        pytest.param("\ud800x", "\udc00x", False, id="lone surrogates, different"),
    ],
)
def test_equality_compares_values_and_never_raises(a: str, b: str, equal: bool) -> None:
    # Constant time is `hmac.compare_digest`'s property; what is pinned here is the result, for
    # any str: a value a header can never carry must still compare without an exception.
    assert (Secret(a) == Secret(b)) is equal


def test_copying_returns_the_same_object_and_leaks_nothing() -> None:
    secret = Secret(VALUE)

    assert copy.copy(secret) is secret
    assert copy.deepcopy(secret) is secret
    assert VALUE not in repr(copy.deepcopy({"k": [secret]}))


@pytest.mark.parametrize("protocol", [0, 1, 2, 3, 4, 5])
def test_pickling_is_refused_at_every_protocol(protocol: int) -> None:
    # What pickle.dumps(secret, protocol) calls first; the value never reaches a byte stream.
    with pytest.raises(TypeError, match="cannot be pickled"):
        Secret(VALUE).__reduce_ex__(protocol)


def test_a_string_validates_into_a_secret_in_python_and_json_mode() -> None:
    assert Holder(token=VALUE).token.reveal() == VALUE
    assert Holder.model_validate_json(f'{{"token": "{VALUE}"}}').token.reveal() == VALUE
    existing = Secret(VALUE)
    assert Holder(token=existing).token is existing


def test_a_non_string_does_not_validate_and_the_error_hides_the_input() -> None:
    with pytest.raises(ValidationError) as caught:
        Holder(token=5)

    errors = caught.value.errors(include_input=False, include_url=False, include_context=False)
    assert {e["loc"][0] for e in errors} == {"token"}
    assert {e["type"] for e in errors} == {"is_instance_of", "string_type"}  # both union branches
    assert all("input" not in e for e in errors)


def test_a_secret_field_serialises_as_the_mask_never_the_value() -> None:
    holder = Holder(token=VALUE)

    assert holder.model_dump() == {"token": "***"}
    assert holder.model_dump(mode="json") == {"token": "***"}
    assert holder.model_dump_json() == '{"token":"***"}'
    assert VALUE not in repr(holder)
    assert VALUE not in str(holder)
