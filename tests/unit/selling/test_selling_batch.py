"""`client.selling` batch methods (`list_many`, `reprice_many`, `remove_many`) through the HTTP
boundary: chunking, re-indexing, outcomes and the failure classification (SDK_SPEC 3.5 rules 3, 4,
7, 8). Every case runs against the async client and its generated sync twin.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from support import market_payloads as mp
from support import selling_payloads as sp
from support.clients import ACCESS, ClientRig
from support.flavors import Flavor
from support.http import Reply, json_response, reply
from support.selling_payloads import Batch
from whitemarket.errors import (
    BadRequestError,
    BatchIncompleteError,
    DecodeError,
    GraphQLError,
    RateLimitError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.models import DeliveryPromise, DeliveryType, Money, Product, ProductHistory
from whitemarket.selling import BatchOutcome, Listing, ListingOptions, PriceChange

PRICE = Money.usd("5.00")
S, F, U, N = (
    BatchOutcome.SUCCEEDED,
    BatchOutcome.FAILED,
    BatchOutcome.UNKNOWN,
    BatchOutcome.NOT_SENT,
)


def uuid_of(i: int) -> str:
    return f"00000000-0000-4000-8000-{i:012d}"


# name -> (the batch models, inputs for n items, the call)
MANY: dict[str, tuple[Batch, Callable[[int], list[Any]], Callable[[Any, list[Any]], Any]]] = {
    "list_many": (
        sp.NEW,
        lambda n: [Listing(str(1000 + i), PRICE) for i in range(n)],
        lambda selling, items: selling.list_many(items),
    ),
    "reprice_many": (
        sp.EDIT,
        lambda n: [PriceChange(str(1000 + i), PRICE) for i in range(n)],
        lambda selling, items: selling.reprice_many(items),
    ),
    "remove_many": (
        sp.REMOVE,
        lambda n: [uuid_of(i) for i in range(n)],
        lambda selling, items: selling.remove_many(items),
    ),
}
many_methods = pytest.mark.parametrize("method", MANY)


def make(flavor: Flavor, *outcomes: Any, size: int | None = None) -> ClientRig:
    options = {} if size is None else {"selling_batch_size": size}
    return ClientRig(flavor, *outcomes, **options)


def call_many(rig: ClientRig, method: str, count: int) -> list[Any]:
    _, make_items, call = MANY[method]
    return rig.call(call(rig.client.selling, make_items(count)))


def run_many(rig: ClientRig, method: str, count: int) -> BatchIncompleteError:
    with pytest.raises(BatchIncompleteError) as error:
        call_many(rig, method, count)
    return error.value


def outcomes(results: Any) -> list[BatchOutcome]:
    return [r.outcome for r in results]


@many_methods
@pytest.mark.parametrize(
    ("count", "sizes"),
    [
        pytest.param(1, [1], id="1 item"),
        pytest.param(99, [99], id="99 items"),
        pytest.param(100, [100], id="100 items"),
        pytest.param(101, [100, 1], id="101 items"),
        pytest.param(250, [100, 100, 50], id="250 items"),
    ],
)
def test_one_request_per_chunk_in_order_and_results_reindexed_to_the_callers_list(
    flavor: Flavor, method: str, count: int, sizes: list[int]
) -> None:
    batch, _, _ = MANY[method]
    answers = [batch.answer(batch.rows_for(size, f"c{k}")) for k, size in enumerate(sizes)]
    with make(flavor, *answers) as rig:
        results = call_many(rig, method, count)

        assert [len(v["items"]) for v in rig.variables()] == sizes
        assert {b["operationName"] for b in rig.bodies()} == {batch.operation}
    assert [r.index for r in results] == list(range(count))
    assert set(outcomes(results)) == {S}
    assert results[0].product is not None
    assert results[0].product.id == "c0-0"
    assert results[-1].product is not None
    assert results[-1].product.id == f"c{len(sizes) - 1}-{sizes[-1] - 1}"


@many_methods
def test_a_configured_chunk_size_is_used(flavor: Flavor, method: str) -> None:
    batch, _, _ = MANY[method]
    answers = [batch.answer(batch.rows_for(2, "a")), batch.answer(batch.rows_for(1, "b"))]
    with make(flavor, *answers, size=2) as rig:
        call_many(rig, method, 3)

        assert [len(v["items"]) for v in rig.variables()] == [2, 1]


@many_methods
def test_an_empty_list_sends_nothing(flavor: Flavor, method: str) -> None:
    with make(flavor, reply(500)) as rig:
        assert call_many(rig, method, 0) == []
        assert rig.script.count == 0


def test_list_many_applies_the_options_to_every_chunk_and_routes_the_two_kinds_of_id(
    flavor: Flavor,
) -> None:
    items = [
        Listing(sp.INVENTORY_ID, PRICE),
        Listing(sp.ASSET_ID, Money.usd("1.25")),
        Listing("7", PRICE),
    ]
    options = ListingOptions(
        delivery_type=DeliveryType.MANUAL, delivery_promise=DeliveryPromise.HOUR1, lifetime=3600
    )
    answers = [sp.NEW.answer(sp.NEW.rows_for(2, "a")), sp.NEW.answer(sp.NEW.rows_for(1, "b"))]
    with make(flavor, *answers, size=2) as rig:
        rig.call(rig.client.selling.list_many(items, options))

        shared = {"deliveryType": "MANUAL", "deliveryPromise": "HOUR1", "lifetime": 3600}
        wire_price = {"currency": "USD", "value": "5.00"}
        assert rig.variables() == [
            {
                **shared,
                "items": [
                    {"inventoryId": sp.INVENTORY_ID, "price": wire_price},
                    {"assetId": sp.ASSET_ID, "price": {"currency": "USD", "value": "1.25"}},
                ],
            },
            {**shared, "items": [{"assetId": "7", "price": wire_price}]},
        ]


def test_list_many_without_options_sends_semi_and_nothing_else(flavor: Flavor) -> None:
    with make(flavor, sp.NEW.answer(sp.NEW.rows_for(1, "a"))) as rig:
        rig.call(rig.client.selling.list_many([Listing("5", PRICE)]))

        assert rig.variables() == [
            {
                "deliveryType": "SEMI",
                "items": [{"assetId": "5", "price": {"currency": "USD", "value": "5.00"}}],
            }
        ]


def test_reprice_many_routes_listing_ids_and_asset_ids(flavor: Flavor) -> None:
    changes = [PriceChange(sp.PRODUCT_ID, PRICE), PriceChange("18446744073709551615", PRICE)]
    rows = [
        sp.EDIT.row(0, True, sp.EDIT.live(sp.PRODUCT_ID, item=None)),
        sp.EDIT.row(1, True, sp.EDIT.live("p1", item=None)),
    ]
    with make(flavor, sp.EDIT.answer(rows)) as rig:
        rig.call(rig.client.selling.reprice_many(changes))

        wire_price = {"currency": "USD", "value": "5.00"}
        assert rig.variables() == [
            {
                "items": [
                    {"productId": sp.PRODUCT_ID, "price": wire_price},
                    {"assetId": "18446744073709551615", "price": wire_price},
                ]
            }
        ]


def test_remove_many_refuses_a_bad_id_at_the_end_of_a_long_list_before_the_first_request(
    flavor: Flavor,
) -> None:
    ids = [uuid_of(i) for i in range(250)] + ["not-a-uuid"]
    with make(flavor, sp.REMOVE.answer([])) as rig:
        with pytest.raises(ValueError, match="product id must be a UUID"):
            rig.call(rig.client.selling.remove_many(ids))

        assert rig.script.count == 0


def test_remove_many_refuses_an_asset_id(flavor: Flavor) -> None:
    with make(flavor, sp.REMOVE.answer([])) as rig:
        with pytest.raises(ValueError, match="product id must be a UUID"):
            rig.call(rig.client.selling.remove_many([sp.ASSET_ID]))

        assert rig.script.count == 0


def test_the_batch_size_option_below_one_is_refused_before_any_http_client_is_made(
    flavor: Flavor,
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        flavor.cls("client", "WhiteMarketClient")(access_token=ACCESS, selling_batch_size=0)


@many_methods
def test_rows_are_matched_to_items_by_index_whatever_the_order_of_the_answer(
    flavor: Flavor, method: str
) -> None:
    batch, _, _ = MANY[method]
    rows = [
        batch.row(2, True, batch.live("p2", item=None)),
        batch.row(0, True, batch.live("p0", item=None)),
        batch.row(1, True, batch.live("p1", item=None)),
    ]
    with make(flavor, batch.answer(rows)) as rig:
        results = call_many(rig, method, 3)

    assert [(r.index, r.product.id) for r in results if r.product] == [
        (0, "p0"),
        (1, "p1"),
        (2, "p2"),
    ]


def test_a_failed_row_carries_the_servers_category_and_message_and_does_not_raise(
    flavor: Flavor,
) -> None:
    rows = [
        sp.NEW.row(1, False, None, "market.product.not_tradable", "Item is not tradable"),
        sp.NEW.row(0, True, sp.NEW.live("ok-0", item=None)),
        sp.NEW.row(2, False, None),
    ]
    with make(flavor, sp.NEW.answer(rows)) as rig:
        results = call_many(rig, "list_many", 3)

    assert [(r.index, r.outcome, r.error_category, r.error_message) for r in results] == [
        (0, S, None, None),
        (1, F, "market.product.not_tradable", "Item is not tradable"),
        (2, F, None, None),
    ]
    assert [results[1].product, results[2].product] == [None, None]
    assert isinstance(results[0].product, Product)


def test_a_mix_of_created_and_not_created_rows_is_a_normal_return(flavor: Flavor) -> None:
    rows = [sp.NEW.row(0, True, sp.NEW.live("a", item=None)), sp.NEW.row(1, False, None, "c", "m")]
    with make(flavor, sp.NEW.answer(rows)) as rig:
        assert outcomes(call_many(rig, "list_many", 2)) == [S, F]


def test_a_row_with_the_product_of_each_kind_is_mapped_to_its_model(flavor: Flavor) -> None:
    rows = [
        sp.NEW.row(0, True, sp.NEW.live("live", item=None)),
        sp.NEW.row(1, True, sp.NEW.archived("archived")),
        sp.NEW.row(2, True, {"__typename": "SomethingNew", "whatever": 1}),
        sp.NEW.row(3, True, None),
    ]
    with make(flavor, sp.NEW.answer(rows)) as rig:
        results = call_many(rig, "list_many", 4)

    live, archived = results[0].product, results[1].product
    assert isinstance(live, Product)
    assert live.id == "live"
    assert isinstance(archived, ProductHistory)
    assert archived.id == "archived"
    assert results[2].product is None
    assert results[3].product is None
    assert set(outcomes(results)) == {S}


def test_a_product_with_an_unknown_enum_value_is_mapped_and_the_row_stays_succeeded(
    flavor: Flavor,
) -> None:
    product = sp.NEW.live("teleport", item=None, deliveryType="TELEPORT")
    with make(flavor, sp.NEW.answer([sp.NEW.row(0, True, product)])) as rig:
        (result,) = call_many(rig, "list_many", 1)

    assert isinstance(result.product, Product)
    assert result.product.delivery_type.value == "TELEPORT"
    assert result.product.delivery_type.is_unknown
    assert result.outcome is S


def test_an_unknown_error_category_is_carried_verbatim_and_the_row_fails(flavor: Flavor) -> None:
    row = sp.NEW.row(0, False, None, "market.brand_new.category", "Something new")
    with make(flavor, sp.NEW.answer([row])) as rig:
        (result,) = call_many(rig, "list_many", 1)

    assert (result.outcome, result.error_category, result.error_message) == (
        F,
        "market.brand_new.category",
        "Something new",
    )


def test_a_product_that_cannot_be_mapped_keeps_the_outcome_the_server_reported(
    flavor: Flavor,
) -> None:
    broken = sp.NEW.live("broken", item=None, price={"currency": "USD", "value": "not-a-number"})
    rows = [sp.NEW.row(0, True, broken), sp.NEW.row(1, False, broken, "x", "y")]
    with make(flavor, sp.NEW.answer(rows)) as rig:
        results = call_many(rig, "list_many", 2)

    assert outcomes(results) == [S, F]
    assert [r.product for r in results] == [None, None]


@many_methods
def test_an_item_without_a_row_is_unknown_and_later_chunks_still_go_out_before_the_error(
    flavor: Flavor, method: str
) -> None:
    batch, _, _ = MANY[method]
    first = batch.rows_for(2, "a")[:1]
    with make(flavor, batch.answer(first), batch.answer(batch.rows_for(2, "b", 2)), size=2) as rig:
        error = run_many(rig, method, 4)

        assert rig.script.count == 2, "the later chunk was sent"
    assert outcomes(error.results) == [S, U, S, S]
    assert [r.index for r in error.results] == [0, 1, 2, 3]
    assert error.__cause__ is None, "nothing failed, the server only left an item out"
    assert str(error) == "batch incomplete: 3 succeeded, 0 failed, 1 unknown, 0 not sent"


def graphql_failure(**body: Any) -> Reply:
    return json_response(body)


def gql_error(path: list[Any] | None = None) -> dict[str, Any]:
    return {"message": "Rejected", **({} if path is None else {"path": path})}


FIELD = "market_new_multiple"
FAILURES = [
    pytest.param(reply(503), U, ServiceUnavailableError, id="HTTP 503 (ambiguous)"),
    pytest.param(httpx.ConnectError("boom"), U, TransportError, id="a network error (ambiguous)"),
    pytest.param(reply(200, b"not json"), U, DecodeError, id="an unreadable body (ambiguous)"),
    pytest.param(
        json_response({"data": {FIELD: [{"index": "x"}]}}),
        U,
        DecodeError,
        id="a row that does not decode (ambiguous)",
    ),
    pytest.param(reply(429), N, RateLimitError, id="HTTP 429 (rejected)"),
    pytest.param(reply(400, b"bad"), N, BadRequestError, id="HTTP 400 (rejected)"),
    pytest.param(
        json_response({"data": None, "errors": [gql_error([FIELD])]}),
        U,
        GraphQLError,
        id="root-path error, data null (the resolver may have acted on some items)",
    ),
    pytest.param(
        json_response({"data": {FIELD: None}, "errors": [gql_error([FIELD])]}),
        U,
        GraphQLError,
        id="root-path error, root field null",
    ),
    pytest.param(
        json_response({"data": None, "errors": [gql_error(), gql_error([FIELD])]}),
        U,
        GraphQLError,
        id="pathless and root-path errors",
    ),
    pytest.param(
        json_response({"errors": [gql_error()]}),
        N,
        GraphQLError,
        id="request error without a path and without a data key (rejected)",
    ),
    pytest.param(
        json_response({"errors": [gql_error(), gql_error()]}),
        N,
        GraphQLError,
        id="two pathless errors, no data key (rejected)",
    ),
    pytest.param(
        json_response({"errors": [gql_error(), gql_error([FIELD])]}),
        U,
        GraphQLError,
        id="no data key but one error has a path",
    ),
    pytest.param(
        json_response({"errors": [{"message": "m", "path": "x"}]}),
        U,
        GraphQLError,
        id="no data key and a malformed path",
    ),
    pytest.param(
        json_response({"data": None, "errors": [gql_error()]}),
        U,
        GraphQLError,
        id="pathless error, data null (execution started)",
    ),
    pytest.param(
        json_response({"data": {FIELD: None}, "errors": [gql_error([FIELD, 0, "product"])]}),
        U,
        GraphQLError,
        id="nested-path error",
    ),
    pytest.param(
        json_response({"data": {FIELD: []}, "errors": [gql_error([FIELD])]}),
        U,
        GraphQLError,
        id="error next to a result",
    ),
]


@pytest.mark.parametrize(("failure", "expected", "cause"), FAILURES)
def test_a_failing_chunk_stops_the_batch_keeps_earlier_results_and_never_sends_later_chunks(
    flavor: Flavor, failure: Any, expected: BatchOutcome, cause: type[Exception]
) -> None:
    answers = [
        sp.NEW.answer(sp.NEW.rows_for(2, "a")),
        failure,
        sp.NEW.answer(sp.NEW.rows_for(2, "c")),
    ]
    with make(flavor, *answers, size=2) as rig:
        error = run_many(rig, "list_many", 6)

        assert rig.script.count == 2, "chunk 3 is never sent, chunk 2 only once"
    assert outcomes(error.results) == [S, S, expected, expected, N, N]
    assert [r.index for r in error.results] == [0, 1, 2, 3, 4, 5]
    assert [r.product.id if r.product else None for r in error.results] == [
        "a-0",
        "a-1",
        None,
        None,
        None,
        None,
    ]
    assert isinstance(error.__cause__, cause)


@many_methods
def test_the_first_chunk_failing_leaves_every_item_not_sent_or_unknown(
    flavor: Flavor, method: str
) -> None:
    with make(flavor, reply(503), reply(200), size=2) as rig:
        error = run_many(rig, method, 3)

        assert rig.script.count == 1
    assert outcomes(error.results) == [U, U, N]


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param([0, 2], id="an index past the chunk"),
        pytest.param([2, 1], id="an index equal to the chunk size"),
        pytest.param([0, -1], id="a negative index"),
        pytest.param([1, 1], id="an index repeated"),
        pytest.param([0, 1, 0], id="more rows than items"),
    ],
)
def test_an_index_out_of_range_or_repeated_makes_the_chunk_unknown_because_it_already_ran(
    flavor: Flavor, claims: list[int]
) -> None:
    rows = [sp.NEW.row(i, True, sp.NEW.live("x", item=None)) for i in claims]
    answers = [
        sp.NEW.answer(sp.NEW.rows_for(2, "a")),
        sp.NEW.answer(rows),
        sp.NEW.answer(sp.NEW.rows_for(2, "c")),
    ]
    with make(flavor, *answers, size=2) as rig:
        error = run_many(rig, "list_many", 6)

        assert rig.script.count == 2, "chunk 3 is never sent"
    assert outcomes(error.results) == [S, S, U, U, N, N]
    assert isinstance(error.__cause__, DecodeError)
    path = error.__cause__.path
    assert path[0] == FIELD
    assert path[2] == "index"


OTHER = sp.OTHER_ID
BIG = "18446744073709551615"


def requested_item(item_id: str | None, asset: str | None) -> dict[str, Any]:
    return mp.item(id=item_id or "item-x", assetId=asset or "1")


@pytest.mark.parametrize(
    ("method", "items", "specs", "matches"),
    [
        ("remove_many", [sp.PRODUCT_ID, OTHER], [{"id": sp.PRODUCT_ID}, {"id": OTHER}], True),
        (
            "remove_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": sp.PRODUCT_ID.upper()}, {"id": OTHER}],
            True,
        ),
        (
            "remove_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": sp.PRODUCT_ID}, {"id": sp.INVENTORY_ID}],
            False,
        ),
        (
            "remove_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": OTHER}, {"id": sp.PRODUCT_ID}],
            False,
        ),
        ("remove_many", [sp.PRODUCT_ID, OTHER], [{"product": False}, {"id": OTHER}], True),
        (
            "remove_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": sp.PRODUCT_ID}, {"id": "x"}],
            False,
        ),
        (
            "reprice_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": sp.PRODUCT_ID.upper()}, {"id": OTHER}],
            True,
        ),
        (
            "reprice_many",
            [sp.PRODUCT_ID, OTHER],
            [{"id": sp.PRODUCT_ID}, {"id": sp.INVENTORY_ID}],
            False,
        ),
        ("reprice_many", [sp.PRODUCT_ID, OTHER], [{"id": sp.PRODUCT_ID}, {"product": False}], True),
        (
            "reprice_many",
            [sp.ASSET_ID, BIG],
            [{"id": "p0", "asset": sp.ASSET_ID}, {"id": "p1", "asset": BIG}],
            True,
        ),
        (
            "reprice_many",
            [sp.ASSET_ID, BIG],
            [{"id": "p0", "asset": sp.ASSET_ID}, {"id": "p1", "asset": "18446744073709551614"}],
            False,
        ),
        ("reprice_many", [sp.ASSET_ID, BIG], [{"id": "p0"}, {"id": "p1"}], True),
        (
            "list_many",
            [sp.ASSET_ID, BIG],
            [{"id": "p0", "asset": sp.ASSET_ID}, {"id": "p1", "asset": BIG}],
            True,
        ),
        (
            "list_many",
            [sp.ASSET_ID, BIG],
            [{"id": "p0", "asset": sp.ASSET_ID}, {"id": "p1", "asset": sp.ASSET_ID}],
            False,
        ),
        ("list_many", [sp.ASSET_ID, BIG], [{"id": "p0"}, {"id": "p1"}], True),
        ("list_many", [sp.ASSET_ID, BIG], [{"product": False}, {"product": False}], True),
        (
            "list_many",
            [sp.INVENTORY_ID, OTHER],
            [
                {"id": "p0", "inventory": sp.INVENTORY_ID.upper()},
                {"id": "p1", "inventory": OTHER},
            ],
            True,
        ),
        (
            "list_many",
            [sp.INVENTORY_ID, OTHER],
            [
                {"id": "p0", "inventory": sp.INVENTORY_ID},
                {"id": "p1", "inventory": sp.INVENTORY_ID},
            ],
            False,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 12 else None,
)
def test_a_row_is_checked_against_the_item_requested_at_its_position(
    flavor: Flavor,
    method: str,
    items: list[str],
    specs: list[dict[str, Any]],
    matches: bool,
) -> None:
    batch = MANY[method][0]
    rows: list[dict[str, Any]] = []
    for position, spec in enumerate(specs):
        if spec.get("product") is False:
            rows.append(batch.row(position, True, None))
        elif method == "remove_many":
            rows.append(batch.row(position, True, batch.archived(spec["id"])))
        else:
            item = None
            if "asset" in spec or "inventory" in spec:
                item = requested_item(spec.get("inventory"), spec.get("asset"))
            rows.append(batch.row(position, True, batch.live(spec["id"], item=item)))
    build = {
        "list_many": lambda: rig.client.selling.list_many([Listing(i, PRICE) for i in items]),
        "reprice_many": lambda: rig.client.selling.reprice_many(
            [PriceChange(i, PRICE) for i in items]
        ),
        "remove_many": lambda: rig.client.selling.remove_many(items),
    }[method]
    with make(flavor, batch.answer(rows)) as rig:
        if matches:
            assert outcomes(rig.call(build())) == [S, S]
            return
        with pytest.raises(BatchIncompleteError) as error:
            rig.call(build())

    assert outcomes(error.value.results) == [U, U], "a mismatch makes the whole chunk unknown"
    assert isinstance(error.value.__cause__, DecodeError)
    assert error.value.__cause__.path[-2:] == ("product", "id")
