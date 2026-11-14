"""The error hierarchy (SDK_SPEC 1.5): shape, categories and the NotFoundError rule."""

from collections.abc import Callable
from functools import partial

import pytest

from whitemarket import errors
from whitemarket.errors import (
    AuthenticationError,
    BadRequestError,
    DecodeError,
    ErrorCategory,
    ExportError,
    GeneralExportError,
    GraphQLError,
    GraphQLErrorEntry,
    HttpError,
    LiveConnectionError,
    MutationOutcomeUnknownError,
    NotFoundError,
    PurchaseOutcomeUnknownError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    SourceLocation,
    StaleExportError,
    TransportError,
    WhiteMarketError,
)

HIERARCHY = [
    (TransportError, WhiteMarketError),
    (HttpError, WhiteMarketError),
    (BadRequestError, HttpError),
    (AuthenticationError, HttpError),
    (RateLimitError, HttpError),
    (ServerError, HttpError),
    (ServiceUnavailableError, ServerError),
    (GraphQLError, WhiteMarketError),
    (NotFoundError, GraphQLError),
    (PurchaseOutcomeUnknownError, WhiteMarketError),
    (MutationOutcomeUnknownError, WhiteMarketError),
    (DecodeError, WhiteMarketError),
    (ExportError, WhiteMarketError),
    (GeneralExportError, ExportError),
    (StaleExportError, ExportError),
    (LiveConnectionError, WhiteMarketError),
]


@pytest.mark.parametrize(("child", "parent"), HIERARCHY, ids=lambda c: c.__name__)
def test_the_hierarchy_matches_sdk_spec_1_5(child: type, parent: type) -> None:
    assert child.__mro__[1] is parent


def test_everything_is_a_whitemarket_error_and_an_exception() -> None:
    for name in errors.__all__:
        member = getattr(errors, name)
        if isinstance(member, type) and member not in (
            ErrorCategory,
            GraphQLErrorEntry,
            SourceLocation,
        ):
            assert issubclass(member, WhiteMarketError), name
            assert issubclass(member, Exception), name


@pytest.mark.parametrize(
    ("error", "status", "retry_after"),
    [
        (HttpError(418, b"teapot"), 418, None),
        (BadRequestError(b"x"), 400, None),
        (AuthenticationError(), 401, None),
        (RateLimitError(retry_after=2.5), 429, 2.5),
        (RateLimitError(), 429, None),
        (ServerError(), 500, None),
        (ServerError(status=502), 502, None),
        (ServiceUnavailableError(retry_after=30), 503, 30),
        (ServiceUnavailableError(), 503, None),
    ],
    ids=lambda v: getattr(v, "__class__", type(v)).__name__ if isinstance(v, Exception) else str(v),
)
def test_http_errors_carry_status_excerpt_and_retry_after(
    error: HttpError, status: int, retry_after: float | None
) -> None:
    assert error.status == status
    assert getattr(error, "retry_after", None) == retry_after
    assert str(error) == f"HTTP {status}", "the message holds no body"


def test_the_body_excerpt_is_kept_apart_from_the_message() -> None:
    error = HttpError(500, b"excerpt")

    assert error.body_excerpt == "excerpt"
    assert "excerpt" not in str(error)


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(partial(HttpError, 418), id="HttpError"),
        pytest.param(BadRequestError, id="BadRequestError"),
        pytest.param(AuthenticationError, id="AuthenticationError"),
        pytest.param(RateLimitError, id="RateLimitError"),
        pytest.param(ServerError, id="ServerError"),
        pytest.param(ServiceUnavailableError, id="ServiceUnavailableError"),
    ],
)
def test_the_body_excerpt_is_always_redacted(make: Callable[[bytes], HttpError]) -> None:
    error = make(b'{"accessToken":"synthetic-secret-value","code":1}')

    assert error.body_excerpt == '{"accessToken":"***","code":1}'
    assert "synthetic-secret-value" not in repr(error.__dict__)


def test_a_missing_body_gives_an_empty_excerpt() -> None:
    assert HttpError(500).body_excerpt == ""


def _payload(*categories: str | None, message: str = "m") -> list[object]:
    return [
        {"message": message, "extensions": {"category": c} if c is not None else {}}
        for c in categories
    ]


@pytest.mark.parametrize(
    ("categories", "expected"),
    [
        pytest.param(["market.product.not_found"], NotFoundError, id="one not_found"),
        pytest.param(["a.not_found", "b.not_found"], NotFoundError, id="every error not_found"),
        pytest.param(
            ["a.not_found", "internal.error"], GraphQLError, id="not_found mixed with another"
        ),
        pytest.param(["a.not_found", None], GraphQLError, id="not_found mixed with no category"),
        pytest.param(
            ["market.product.not_found_in_specified_price"], GraphQLError, id="suffix only"
        ),
        pytest.param(["not_found"], GraphQLError, id="no dot before the suffix"),
        pytest.param([None], GraphQLError, id="no category"),
        pytest.param([], GraphQLError, id="no errors"),
    ],
)
def test_not_found_only_when_every_category_ends_with_dot_not_found(
    categories: list[str | None], expected: type[GraphQLError]
) -> None:
    error = GraphQLError.from_payload(_payload(*categories))

    assert type(error) is expected


def test_a_graphql_error_exposes_every_entry_and_the_partial_data() -> None:
    raw = [
        {
            "message": "Oops! Item not found.",
            "locations": [{"line": 2, "column": 3}],
            "path": ["market_item", 0],
            "extensions": {"category": "market.product.not_found", "extra": 1},
        },
        {"message": "second"},
    ]

    error = GraphQLError.from_payload(raw, {"market_item": None})

    first, second = error.errors
    assert first == GraphQLErrorEntry(
        message="Oops! Item not found.",
        path=("market_item", 0),
        locations=(SourceLocation(2, 3),),
        category="market.product.not_found",
        extensions={"category": "market.product.not_found", "extra": 1},
    )
    assert (second.message, second.path, second.locations, second.category) == (
        "second",
        (),
        (),
        None,
    )
    assert error.partial_data == {"market_item": None}
    assert str(error) == "Oops! Item not found."
    assert error.has_category(ErrorCategory.MARKET_PRODUCT_NOT_FOUND)
    assert not error.has_category("other")


@pytest.mark.parametrize(
    "raw",
    [
        "a string",
        None,
        5,
        {"message": 5, "path": "x", "locations": "y", "extensions": [1]},
        {"locations": [{"line": "1", "column": 2}, "nope", {"line": 1}], "path": [{}, None, "ok"]},
    ],
    ids=["string", "none", "int", "wrong-types", "partial-parts"],
)
def test_a_malformed_error_entry_never_raises(raw: object) -> None:
    entry = GraphQLErrorEntry.from_payload(raw)

    assert isinstance(entry.message, str)
    assert entry.category is None
    assert entry.locations == ()
    assert entry.path in ((), ("ok",))


def test_an_unknown_category_is_delivered_as_a_plain_string() -> None:
    error = GraphQLError.from_payload(_payload("brand.new.category"))

    assert error.errors[0].category == "brand.new.category"
    assert type(error) is GraphQLError


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("market.product.not_found", True),
        (".not_found", True),
        ("market.product.not_found_in_specified_price", False),
        ("not_found", False),
        ("", False),
        (None, False),
    ],
)
def test_is_not_found_looks_at_the_suffix_only(category: str | None, expected: bool) -> None:
    assert ErrorCategory.is_not_found(category) is expected


def test_the_known_categories() -> None:
    assert ErrorCategory.MARKET_PRODUCT_NOT_FOUND == "market.product.not_found"
    assert (
        ErrorCategory.MARKET_PRODUCT_NOT_FOUND_IN_SPECIFIED_PRICE
        == "market.product.not_found_in_specified_price"
    )


def test_a_decode_error_holds_the_path_and_the_reason() -> None:
    error = DecodeError("bool_parsing: not a bool", ("a", 0, "b"))

    assert (error.path, error.reason) == (("a", 0, "b"), "bool_parsing: not a bool")
    assert str(error) == "a[0].b: bool_parsing: not a bool"
    assert str(DecodeError("only a reason")) == "only a reason"


@pytest.mark.parametrize(
    ("path", "text"),
    [
        pytest.param(("prices", 3, "price"), "prices[3].price", id="name index name"),
        pytest.param(("products", 3), "products[3]", id="name index"),
        pytest.param(("meta", "items"), "meta.items", id="names only"),
        pytest.param((0, "a"), "[0].a", id="leading index"),
        pytest.param(("a", 1, 2, "b"), "a[1][2].b", id="nested indexes"),
        pytest.param(("a",), "a", id="one name"),
    ],
)
def test_a_decode_error_path_renders_indexes_in_brackets(
    path: tuple[str | int, ...], text: str
) -> None:
    assert str(DecodeError("bad", path)) == f"{text}: bad"


def test_the_outcome_unknown_errors_name_what_the_caller_needs() -> None:
    purchase = PurchaseOutcomeUnknownError("cid-1")
    mutation = MutationOutcomeUnknownError("wallet_transfer_send")

    assert purchase.custom_id == "cid-1"
    assert "cid-1" in str(purchase)
    assert mutation.operation == "wallet_transfer_send"
    assert "wallet_transfer_send" in str(mutation)


@pytest.mark.parametrize(
    ("operation", "where"),
    [
        pytest.param("wallet.transfer", "wallet.transfers()", id="transfer"),
        pytest.param("wallet.take_credit", "wallet.credit()", id="take_credit"),
        pytest.param("other.op", "the result", id="unmapped-operation"),
    ],
)
def test_the_mutation_outcome_unknown_error_derives_where_to_check(
    operation: str, where: str
) -> None:
    assert str(MutationOutcomeUnknownError(operation)) == (
        f"{operation} may or may not have been executed; check {where} before trying again"
    )
