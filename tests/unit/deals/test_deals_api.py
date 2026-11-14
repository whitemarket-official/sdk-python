"""`client.deals` through the HTTP boundary: references, statuses, lists, history, mutations,
balances (SDK_SPEC 3.4). Every case runs against the async client and its generated sync twin.
Responses are synthetic; time is a fake.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from support import market_payloads as mp
from support.clients import ClientRig
from support.deal_apis import (
    DEAL_ID,
    OTHER_ID,
    Timeline,
    archived_deal,
    cancelled_offer,
    deals_api,
    history_node,
    live_deal,
    names,
    not_found,
    operations,
    states,
)
from support.flavors import Flavor
from support.http import Reply, data, json_response, reply
from whitemarket import RetryPolicy
from whitemarket._generated.deal_buyer_list import DealBuyerListDealBuyerList
from whitemarket._generated.deal_request_cancel import DealRequestCancelDealRequestCancel
from whitemarket._generated.deal_seller_list import DealSellerListDealSellerList
from whitemarket._generated.deal_steam_offer_sent import DealSteamOfferSentDealSteamOfferSent
from whitemarket._generated.input_types import MarkerDealHistorySearchInput
from whitemarket._mappers.search import deal_history_search_input
from whitemarket.deals import DealHistoryFilter, DealHistorySort
from whitemarket.errors import (
    DecodeError,
    GraphQLError,
    NotFoundError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
)
from whitemarket.models import (
    Currency,
    DealAction,
    DealHistorySortField,
    DealHistoryStatus,
    DealStatus,
    Money,
    OfferCancelReason,
    PageRequest,
    SortDirection,
)

FLOAT: Any = 0.07  # a binary float, hidden from the type checker
NAIVE = datetime.fromtimestamp(0, UTC).replace(tzinfo=None)  # a datetime without a time zone
NO_RETRY = {"retry": RetryPolicy(max_attempts=1)}


def rig_of(flavor: Flavor, *outcomes: Any, **options: Any) -> tuple[ClientRig, Any]:
    rig = ClientRig(flavor, *outcomes, **{**NO_RETRY, **options})
    return rig, deals_api(rig, Timeline())


# ---- get -------------------------------------------------------------------------------------


def test_get_finds_a_deal_in_progress_by_id_with_one_request(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, live_deal("order-1"))
    with rig:
        deal = rig.call(api.get(DEAL_ID))

        assert operations(rig) == [("DealItem", {"id": DEAL_ID})]
        assert (deal.id, deal.custom_id, deal.is_archived) == (DEAL_ID, "order-1", False)


def test_get_treats_an_uppercase_uuid_as_an_id(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, live_deal("order-1"))
    with rig:
        rig.call(api.get(DEAL_ID.upper()))

        assert operations(rig) == [("DealItem", {"id": DEAL_ID.upper()})]


def test_get_falls_back_to_the_archive_by_the_same_id(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, not_found(), archived_deal("order-1"))
    with rig:
        deal = rig.call(api.get(DEAL_ID))

        assert operations(rig) == [
            ("DealItem", {"id": DEAL_ID}),
            ("DealHistoryItem", {"id": DEAL_ID}),
        ]
        assert deal.is_archived


def test_get_looks_a_uuid_shaped_reference_up_as_a_custom_id_when_no_deal_has_that_id(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, not_found("a"), not_found("b"), live_deal(DEAL_ID))
    with rig:
        deal = rig.call(api.get(DEAL_ID))

        assert operations(rig) == [
            ("DealItem", {"id": DEAL_ID}),
            ("DealHistoryItem", {"id": DEAL_ID}),
            ("DealItem", {"customId": DEAL_ID}),
        ]
        assert deal.custom_id == DEAL_ID


def test_get_finds_an_archived_deal_by_custom_id_as_the_last_candidate(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, not_found(), not_found(), not_found(), archived_deal(DEAL_ID))
    with rig:
        deal = rig.call(api.get(DEAL_ID))

        assert names(rig) == ["DealItem", "DealHistoryItem", "DealItem", "DealHistoryItem"]
        assert deal.is_archived


def test_get_sends_a_plain_reference_only_as_a_custom_id(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, not_found("live"), archived_deal("order-1"))
    with rig:
        deal = rig.call(api.get("order-1"))

        assert operations(rig) == [
            ("DealItem", {"customId": "order-1"}),
            ("DealHistoryItem", {"customId": "order-1"}),
        ]
        assert deal.is_archived


def test_get_raises_the_last_not_found_when_nothing_matches(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, *[not_found(str(i)) for i in range(4)])
    with rig:
        with pytest.raises(NotFoundError) as caught:
            rig.call(api.get(DEAL_ID))

        assert "3" in str(caught.value)
        assert rig.script.count == 4


def test_get_raises_the_not_found_of_the_archive_for_a_plain_reference(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, not_found("live"), not_found("archive"))
    with rig:
        with pytest.raises(NotFoundError, match="archive"):
            rig.call(api.get("order-1"))

        assert rig.script.count == 2


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(reply(500), ServerError, id="HTTP 500"),
        pytest.param(httpx.ConnectError("boom"), TransportError, id="network error"),
    ],
)
def test_get_lets_a_failure_that_is_not_a_not_found_through_at_once(
    flavor: Flavor, failure: Any, expected: type[Exception]
) -> None:
    rig, api = rig_of(flavor, failure, live_deal())
    with rig:
        with pytest.raises(expected):
            rig.call(api.get(DEAL_ID))

        assert rig.script.count == 1, "the next candidate is not tried"


def test_get_rejects_an_empty_reference_before_any_request(flavor: Flavor) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="empty"):
            rig.call(api.get(""))

        assert rig.script.count == 0


# ---- statuses --------------------------------------------------------------------------------


def answer_for_ids(request: httpx.Request) -> httpx.Response:
    """A state per requested id: id `deal-<x>` and custom id `<x>`."""
    ids = json.loads(request.content)["variables"]["ids"]
    rows = [mp.deal_state(id=f"deal-{i}", customId=i) for i in ids]
    return json_response({"data": {"deal_buyer_statuses": rows}}).build()


@pytest.mark.parametrize(
    ("count", "chunk_sizes"),
    [
        pytest.param(0, [], id="none -> no request"),
        pytest.param(1, [1], id="one"),
        pytest.param(299, [299], id="one below a full chunk"),
        pytest.param(300, [300], id="a full chunk"),
        pytest.param(301, [300, 1], id="one above a full chunk"),
        pytest.param(600, [300, 300], id="two full chunks"),
        pytest.param(601, [300, 300, 1], id="two chunks and one"),
    ],
)
def test_statuses_asks_for_at_most_300_ids_per_request_and_keeps_the_request_order(
    flavor: Flavor, count: int, chunk_sizes: list[int]
) -> None:
    ids = [f"order-{i}" for i in range(count)]
    rig, api = rig_of(flavor, answer_for_ids)
    with rig:
        result = rig.call(api.statuses(ids))

        sent = [variables["ids"] for _, variables in operations(rig)]
        assert [len(chunk) for chunk in sent] == chunk_sizes
        assert [i for chunk in sent for i in chunk] == ids
        assert list(result) == ids
        assert [state.id for state in result.values()] == [f"deal-{i}" for i in ids]


def test_statuses_keeps_the_request_order_when_the_server_answers_in_another_order(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(
        flavor,
        states(
            {"id": "id-c", "customId": None},
            {"id": "id-a", "customId": None},
            {"id": "id-b", "customId": None},
        ),
    )
    with rig:
        assert list(rig.call(api.statuses(["id-a", "id-b", "id-c"]))) == ["id-a", "id-b", "id-c"]


def test_statuses_matches_a_state_to_the_custom_id_that_was_requested(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, states({"id": DEAL_ID, "customId": "order-1", "status": "EXCHANGED"}))
    with rig:
        result = rig.call(api.statuses(["order-1"]))

        assert list(result) == ["order-1"]
        state = result["order-1"]
        assert (state.id, state.custom_id, state.status) == (
            DEAL_ID,
            "order-1",
            DealStatus.EXCHANGED,
        )


def test_statuses_matches_both_an_id_and_a_custom_id_in_one_request(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor,
        states({"id": DEAL_ID, "customId": "order-1"}, {"id": OTHER_ID, "customId": "order-2"}),
    )
    with rig:
        result = rig.call(api.statuses(["order-2", DEAL_ID]))

        assert list(result) == ["order-2", DEAL_ID]
        assert [result["order-2"].id, result[DEAL_ID].id] == [OTHER_ID, DEAL_ID]
        assert rig.script.count == 1


def test_statuses_leaves_out_what_the_server_does_not_know(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor,
        states({"id": "id-b", "customId": None}, {"id": "id-x", "customId": "not-asked"}),
    )
    with rig:
        assert list(rig.call(api.statuses(["id-a", "id-b", "id-c"]))) == ["id-b"]


def test_statuses_sends_a_duplicate_once_and_returns_it_once(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor,
        states(*({"id": i, "customId": None} for i in ("id-a", "id-b", "id-c"))),
    )
    with rig:
        result = rig.call(api.statuses(["id-a", "id-b", "id-a", "id-c", "id-b"]))

        assert operations(rig) == [("DealBuyerStatuses", {"ids": ["id-a", "id-b", "id-c"]})]
        assert list(result) == ["id-a", "id-b", "id-c"]


def test_statuses_counts_duplicates_before_chunking(flavor: Flavor) -> None:
    ids = [f"id-{i}" for i in range(300)]
    rig, api = rig_of(flavor, states())
    with rig:
        rig.call(api.statuses([*ids, *ids]))

        assert rig.script.count == 1, "300 distinct ids fit one request"


def test_statuses_matches_an_uppercase_uuid_to_the_lowercase_id_the_server_answered(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, states({"id": DEAL_ID, "customId": None}))
    with rig:
        result = rig.call(api.statuses([DEAL_ID.upper()]))

        assert list(result) == [DEAL_ID.upper()]
        assert result[DEAL_ID.upper()].id == DEAL_ID
        assert operations(rig) == [("DealBuyerStatuses", {"ids": [DEAL_ID.upper()]})]


def test_statuses_matches_a_lowercase_uuid_to_the_uppercase_id_the_server_answered(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, states({"id": DEAL_ID.upper(), "customId": None}))
    with rig:
        assert list(rig.call(api.statuses([DEAL_ID]))) == [DEAL_ID]


def test_statuses_does_not_match_a_uuid_shaped_custom_id_that_differs_in_case(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, states({"id": "deal-1", "customId": OTHER_ID}))
    with rig:
        assert rig.call(api.statuses([OTHER_ID.upper()])) == {}


def test_statuses_matches_a_uuid_shaped_custom_id_exactly(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, states({"id": "deal-1", "customId": OTHER_ID}))
    with rig:
        assert rig.call(api.statuses([OTHER_ID]))[OTHER_ID].id == "deal-1"


def test_statuses_keeps_two_custom_ids_that_differ_only_in_case_apart(flavor: Flavor) -> None:
    upper = OTHER_ID.upper()
    rig, api = rig_of(
        flavor,
        states(
            {"id": "deal-lower", "customId": OTHER_ID},
            {"id": "deal-upper", "customId": upper},
        ),
    )
    with rig:
        result = rig.call(api.statuses([OTHER_ID, upper]))

        assert operations(rig) == [("DealBuyerStatuses", {"ids": [OTHER_ID, upper]})]
        assert (result[OTHER_ID].id, result[upper].id) == ("deal-lower", "deal-upper")


def test_statuses_sends_every_spelling_of_a_uuid_and_returns_each_requested_spelling(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, states({"id": DEAL_ID, "customId": None}))
    with rig:
        result = rig.call(api.statuses([DEAL_ID, DEAL_ID.upper(), DEAL_ID]))

        assert operations(rig) == [("DealBuyerStatuses", {"ids": [DEAL_ID, DEAL_ID.upper()]})]
        assert list(result) == [DEAL_ID, DEAL_ID.upper()]
        assert result[DEAL_ID.upper()].id == DEAL_ID


def test_statuses_does_not_match_a_plain_custom_id_that_differs_in_case(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, states({"id": DEAL_ID, "customId": "Order-1"}))
    with rig:
        assert rig.call(api.statuses(["order-1"])) == {}


def test_statuses_does_not_match_a_plain_id_that_differs_in_case(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, states({"id": "Deal-A", "customId": None}))
    with rig:
        assert rig.call(api.statuses(["deal-a"])) == {}


@pytest.mark.parametrize("key", [DEAL_ID, "deal-x"], ids=["UUID form", "free-form string"])
def test_statuses_prefers_the_deal_whose_id_equals_the_key_over_the_one_whose_custom_id_does(
    flavor: Flavor, key: str
) -> None:
    rig, api = rig_of(
        flavor,
        states({"id": "deal-b", "customId": key}, {"id": key, "customId": None}),
    )
    with rig:
        assert rig.call(api.statuses([key]))[key].id == key


def test_statuses_maps_the_whole_state(flavor: Flavor) -> None:
    row = {
        "id": "id-a",
        "customId": "order-a",
        "status": "STEAM_ROLLBACK",
        "cancelReason": "STEAM_ISSUES",
        "price": {"currency": "USD", "value": "25.000"},
        "reversePenaltyValue": {"currency": "USD", "value": "1.250"},
        "reverseRefundValue": {"currency": "USD", "value": "23.750"},
        "steamId": "76561190000000002",
        "tradeId": "9000000000000000002",
        "isTradeProtected": True,
        "settlementTimeAt": "2026-11-09T10:00:00+00:00",
    }
    rig, api = rig_of(flavor, states(row))
    with rig:
        state = rig.call(api.statuses(["id-a"]))["id-a"]

        assert state.status is DealStatus.STEAM_ROLLBACK
        assert (str(state.price), str(state.reverse_penalty), str(state.reverse_refund)) == (
            "25.000 USD",
            "1.250 USD",
            "23.750 USD",
        )
        assert (state.steam_id, state.trade_id) == ("76561190000000002", "9000000000000000002")
        assert state.is_trade_protected is True
        assert state.settlement_time_at == datetime(2026, 11, 9, 10, tzinfo=UTC)


def test_statuses_maps_an_unknown_status_without_failing(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, states({"id": "id-a", "customId": None, "status": "SOMETHING_NEW"}))
    with rig:
        state = rig.call(api.statuses(["id-a"]))["id-a"]

        assert state.status.is_unknown
        assert state.status.value == "SOMETHING_NEW"


# ---- lists -----------------------------------------------------------------------------------

LISTS = [
    pytest.param(
        "list_as_buyer", "DealBuyerList", "deal_buyer_list", DealBuyerListDealBuyerList, id="buyer"
    ),
    pytest.param(
        "list_as_seller",
        "DealSellerList",
        "deal_seller_list",
        DealSellerListDealSellerList,
        id="seller",
    ),
]


@pytest.mark.parametrize(("method", "operation", "field", "model"), LISTS)
def test_lists_send_no_variable_without_a_filter_and_map_every_deal(
    flavor: Flavor, method: str, operation: str, field: str, model: Any
) -> None:
    rows = [
        mp.deal_as(model, customId="order-1"),
        mp.deal_as(model, customId="order-2", status="NEED_CONFIRMATION"),
    ]
    rig, api = rig_of(flavor, data(**{field: rows}))
    with rig:
        deals = rig.call(getattr(api, method)())

        assert operations(rig) == [(operation, {})]
        assert [(d.custom_id, d.status) for d in deals] == [
            ("order-1", DealStatus.OFFERED),
            ("order-2", DealStatus.NEED_CONFIRMATION),
        ]


@pytest.mark.parametrize(("method", "operation", "field", "model"), LISTS)
def test_lists_encode_the_status_filters(
    flavor: Flavor, method: str, operation: str, field: str, model: Any
) -> None:
    rig, api = rig_of(flavor, data(**{field: []}))
    with rig:
        deals = rig.call(
            getattr(api, method)([DealStatus.OFFERED, DealStatus.EXCHANGED], [DealStatus.HOLD])
        )

        assert deals == []
        assert operations(rig) == [
            (operation, {"statusesWith": ["OFFERED", "EXCHANGED"], "statusesWithout": ["HOLD"]})
        ]


@pytest.mark.parametrize(("method", "operation", "field", "model"), LISTS)
def test_lists_send_the_queued_status_in_either_filter(
    flavor: Flavor, method: str, operation: str, field: str, model: Any
) -> None:
    rig, api = rig_of(flavor, data(**{field: []}), data(**{field: []}))
    with rig:
        rig.call(getattr(api, method)([DealStatus.OFFERED, DealStatus.QUEUED]))
        rig.call(getattr(api, method)(None, [DealStatus.QUEUED]))

        assert operations(rig) == [
            (operation, {"statusesWith": ["OFFERED", "QUEUED"]}),
            (operation, {"statusesWithout": ["QUEUED"]}),
        ]


@pytest.mark.parametrize(("method", "operation", "field", "model"), LISTS)
def test_lists_refuse_a_status_the_schema_does_not_accept_before_sending(
    flavor: Flavor, method: str, operation: str, field: str, model: Any
) -> None:
    rig, api = rig_of(flavor, data(**{field: []}))
    with rig:
        with pytest.raises(ValueError, match="DealStatus"):
            rig.call(getattr(api, method)([DealStatus("FUTURE_STATUS")]))

        assert rig.script.count == 0


# ---- history ---------------------------------------------------------------------------------


def history_page(custom_ids: list[str], end_cursor: str | None, has_next: bool) -> Reply:
    return data(
        deal_history={
            "edges": [{"cursor": f"c-{i}", "node": history_node(i)} for i in custom_ids],
            "pageInfo": mp.page_info(end_cursor, has_next),
            "totalCount": 7,
        }
    )


def test_history_maps_archived_deals_and_the_page_info(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, history_page(["order-1", "order-2"], "cursor-2", True))
    with rig:
        page = rig.call(api.history())

        assert operations(rig) == [("DealHistory", {})]
        assert [(d.custom_id, d.is_archived) for d in page.items] == [
            ("order-1", True),
            ("order-2", True),
        ]
        assert (page.end_cursor, page.has_next_page, page.total_count) == ("cursor-2", True, 7)


def test_history_encodes_a_filter_and_a_page_request(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, history_page([], None, False))
    with rig:
        rig.call(
            api.history(
                DealHistoryFilter(action=DealAction.BUY), PageRequest(first=50, after="cursor-1")
            )
        )

        assert operations(rig) == [
            (
                "DealHistory",
                {
                    "forwardPagination": {"after": "cursor-1", "first": 50},
                    "search": {"action": "BUY"},
                },
            )
        ]


def test_history_sends_a_raw_input_exactly(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, history_page([], None, False))
    with rig:
        rig.call(
            api.history(MarkerDealHistorySearchInput(csgo_float_from="0.0700", name="redline"))
        )

        assert operations(rig) == [
            ("DealHistory", {"search": {"csgoFloatFrom": "0.0700", "name": "redline"}})
        ]


def test_iterate_history_requests_a_page_only_when_the_previous_one_is_consumed(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(
        flavor, history_page(["a", "b"], "c2", True), history_page(["c"], "c3", False)
    )
    with rig:
        items = api.iterate_history(DealHistoryFilter(action=DealAction.SELL), 2)

        assert rig.script.count == 0, "created, not started"
        assert rig.step(items).custom_id == "a"
        assert rig.script.count == 1
        assert rig.step(items).custom_id == "b"
        assert rig.script.count == 1, "last item of page 1: page 2 is not requested yet"
        assert rig.step(items).custom_id == "c"
        assert rig.script.count == 2
        with pytest.raises(StopIteration):
            rig.step(items)
        assert operations(rig) == [
            ("DealHistory", {"forwardPagination": {"first": 2}, "search": {"action": "SELL"}}),
            (
                "DealHistory",
                {"forwardPagination": {"after": "c2", "first": 2}, "search": {"action": "SELL"}},
            ),
        ]


def test_iterate_history_stops_on_a_missing_cursor_instead_of_looping(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, history_page(["a"], None, True))
    with rig:
        items = api.iterate_history()

        assert rig.step(items).custom_id == "a"
        with pytest.raises(DecodeError, match="cursor"):
            rig.step(items)


def test_the_history_filter_encodes_every_field_it_has() -> None:
    filter = DealHistoryFilter(
        action=DealAction.SELL,
        status=DealHistoryStatus.COMPLETED,
        price_from=Money.usd("1.50"),
        price_to=Money.usd("20"),
        created_from=datetime(2026, 11, 1, tzinfo=UTC),
        sort=DealHistorySort(field=DealHistorySortField.PRICE, direction=SortDirection.DESC),
        name_hash="AK-47 | Redline (Field-Tested)",
        asset_ids=["9007199254740993"],
        pattern=661,
    )

    wire = deal_history_search_input(filter).model_dump(
        by_alias=True, exclude_none=True, mode="json"
    )

    assert wire == {
        "action": "SELL",
        "status": "COMPLETED",
        "price": {
            "from": {"currency": "USD", "value": "1.50"},
            "to": {"currency": "USD", "value": "20"},
        },
        "createdAt": {"from": "2026-11-01T00:00:00Z"},
        "sort": {"field": "PRICE", "type": "DESC"},
        "nameHash": "AK-47 | Redline (Field-Tested)",
        "assetIds": ["9007199254740993"],
        "csgoPattern": 661,
    }


def test_the_history_filter_refuses_what_it_cannot_send() -> None:
    with pytest.raises(TypeError, match="float_from"):
        DealHistoryFilter(float_from=FLOAT)
    with pytest.raises(ValueError, match="created_to"):
        DealHistoryFilter(created_to=NAIVE)
    with pytest.raises(ValueError, match="EUR"):
        DealHistoryFilter(price_from=Money(amount=Decimal(1), currency=Currency("EUR")))
    assert (
        deal_history_search_input(DealHistoryFilter(float_from=Decimal("0.0700"))).csgo_float_from
        == "0.0700"
    )


# ---- requestCancel ---------------------------------------------------------------------------


def test_request_cancel_sends_one_mutation_with_the_id_and_maps_the_deal(flavor: Flavor) -> None:
    deal = mp.deal_as(
        DealRequestCancelDealRequestCancel, id=DEAL_ID, status="BUYER_CANCEL_REQUESTED"
    )
    rig, api = rig_of(flavor, data(deal_request_cancel=deal))
    with rig:
        result = rig.call(api.request_cancel(DEAL_ID))

        assert operations(rig) == [("DealRequestCancel", {"id": DEAL_ID})]
        assert rig.bodies()[0]["query"].lstrip().startswith("mutation DealRequestCancel(")
        assert (result.id, result.status) == (DEAL_ID, DealStatus.BUYER_CANCEL_REQUESTED)


def test_request_cancel_accepts_an_uppercase_uuid(flavor: Flavor) -> None:
    deal = mp.deal_as(DealRequestCancelDealRequestCancel, id=DEAL_ID)
    rig, api = rig_of(flavor, data(deal_request_cancel=deal))
    with rig:
        rig.call(api.request_cancel(DEAL_ID.upper()))

        assert operations(rig) == [("DealRequestCancel", {"id": DEAL_ID.upper()})]


@pytest.mark.parametrize(
    "bad_id",
    [
        pytest.param("", id="empty"),
        pytest.param("order-42", id="a custom id"),
        pytest.param(DEAL_ID + "\n", id="a UUID with a trailing newline"),
        pytest.param(" " + DEAL_ID, id="a UUID with a leading space"),
        pytest.param(DEAL_ID[:-1], id="a UUID one character short"),
    ],
)
def test_request_cancel_rejects_anything_but_a_deal_id_before_any_request(
    flavor: Flavor, bad_id: str
) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="UUID"):
            rig.call(api.request_cancel(bad_id))

        assert rig.script.count == 0


# ---- reportOfferSent and cancelSendingOffer ----------------------------------------------------


def offer_sent(custom_id: str) -> Reply:
    deal = mp.deal_as(
        DealSteamOfferSentDealSteamOfferSent, id=DEAL_ID, customId=custom_id, status="OFFERED"
    )
    return data(deal_steam_offer_sent=deal)


def test_report_offer_sent_sends_a_plain_reference_as_the_custom_id_without_any_lookup(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, offer_sent("order-42"))
    with rig:
        deal = rig.call(api.report_offer_sent("order-42", "5550001"))

        assert operations(rig) == [
            ("DealSteamOfferSent", {"customId": "order-42", "offerId": "5550001"})
        ]
        assert deal.custom_id == "order-42"


def test_report_offer_sent_resolves_a_uuid_shaped_reference_by_queries_then_sends_the_id_once(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, live_deal("order-1"), offer_sent("order-1"))
    with rig:
        rig.call(api.report_offer_sent(DEAL_ID, "5550001"))

        assert operations(rig) == [
            ("DealItem", {"id": DEAL_ID}),
            ("DealSteamOfferSent", {"id": DEAL_ID, "offerId": "5550001"}),
        ]


def reference_mutation(api: Any, call: str, reference: str) -> Any:
    """The call (a coroutine in the async flavor, the result in the sync one) of a mutation that
    takes a deal reference."""
    if call == "report_offer_sent":
        return api.report_offer_sent(reference, "5550001")
    return api.cancel_sending_offer(reference, OfferCancelReason.UNKNOWN, "x")


def item_of(deal_id: str, custom_id: str | None) -> Reply:
    return data(deal_item=mp.deal(id=deal_id, customId=custom_id))


def test_report_offer_sent_sends_the_id_found_for_a_uuid_shaped_custom_id(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor, not_found("a"), not_found("b"), item_of(OTHER_ID, DEAL_ID), offer_sent(DEAL_ID)
    )
    with rig:
        rig.call(api.report_offer_sent(DEAL_ID, "5550001"))

        assert operations(rig) == [
            ("DealItem", {"id": DEAL_ID}),
            ("DealHistoryItem", {"id": DEAL_ID}),
            ("DealItem", {"customId": DEAL_ID}),
            ("DealSteamOfferSent", {"id": OTHER_ID, "offerId": "5550001"}),
        ]


@pytest.mark.parametrize(
    ("deal_id", "custom_id"),
    [
        pytest.param(OTHER_ID, None, id="another id, no custom id"),
        pytest.param(OTHER_ID, "order-1", id="another id and another custom id"),
    ],
)
@pytest.mark.parametrize("call", ["report_offer_sent", "cancel_sending_offer"])
def test_a_mutation_is_not_sent_when_the_server_returns_another_deal_than_the_reference(
    flavor: Flavor, call: str, deal_id: str, custom_id: str | None
) -> None:
    rig, api = rig_of(flavor, item_of(deal_id, custom_id))
    with rig:
        with pytest.raises(DecodeError, match="different deal") as caught:
            rig.call(reference_mutation(api, call, DEAL_ID))

        assert caught.value.path == ("deal_item", "id")
        assert operations(rig) == [("DealItem", {"id": DEAL_ID})], "no mutation sent"


@pytest.mark.parametrize(
    ("reference", "found_id", "found_custom_id"),
    [
        pytest.param(DEAL_ID.upper(), DEAL_ID, "order-1", id="uppercase reference, lowercase id"),
        pytest.param(DEAL_ID, DEAL_ID.upper(), "order-1", id="lowercase reference, uppercase id"),
    ],
)
def test_a_mutation_accepts_a_deal_whose_id_differs_from_the_reference_only_in_case(
    flavor: Flavor, reference: str, found_id: str, found_custom_id: str
) -> None:
    rig, api = rig_of(flavor, item_of(found_id, found_custom_id), offer_sent("order-1"))
    with rig:
        rig.call(api.report_offer_sent(reference, "5550001"))

        assert operations(rig) == [
            ("DealItem", {"id": reference}),
            ("DealSteamOfferSent", {"id": found_id, "offerId": "5550001"}),
        ]


def test_a_mutation_is_not_sent_when_the_deals_custom_id_differs_from_the_reference_in_case(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, not_found("a"), not_found("b"), item_of(OTHER_ID, DEAL_ID))
    with rig:
        with pytest.raises(DecodeError) as caught:
            rig.call(api.report_offer_sent(DEAL_ID.upper(), "5550001"))

        assert caught.value.path == ("deal_item", "id")
        assert "DealSteamOfferSent" not in names(rig)


def test_a_mutation_accepts_a_deal_whose_custom_id_equals_the_reference_exactly(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(
        flavor, not_found("a"), not_found("b"), item_of(OTHER_ID, DEAL_ID), offer_sent(DEAL_ID)
    )
    with rig:
        rig.call(api.report_offer_sent(DEAL_ID, "5550001"))

        assert operations(rig)[3] == ("DealSteamOfferSent", {"id": OTHER_ID, "offerId": "5550001"})


@pytest.mark.parametrize("call", ["report_offer_sent", "cancel_sending_offer"])
def test_a_mutation_sends_nothing_when_the_deal_is_not_found(flavor: Flavor, call: str) -> None:
    rig, api = rig_of(flavor, *[not_found(str(i)) for i in range(4)])
    with rig:
        with pytest.raises(NotFoundError):
            rig.call(reference_mutation(api, call, DEAL_ID))

        assert set(names(rig)) <= {"DealItem", "DealHistoryItem"}


def test_cancel_sending_offer_sends_one_mutation_and_returns_the_archived_deal(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(flavor, cancelled_offer("order-42"))
    with rig:
        deal = rig.call(
            api.cancel_sending_offer("order-42", OfferCancelReason.STEAM_ISSUES_15, "Steam is down")
        )

        assert operations(rig) == [
            (
                "DealCancelSendingOffer",
                {"comment": "Steam is down", "customId": "order-42", "reason": "STEAM_ISSUES_15"},
            )
        ]
        assert (deal.custom_id, deal.is_archived) == ("order-42", True)


def test_cancel_sending_offer_resolves_a_uuid_shaped_reference_then_sends_the_id_once(
    flavor: Flavor,
) -> None:
    rig, api = rig_of(
        flavor, not_found("a"), not_found("b"), item_of(OTHER_ID, DEAL_ID), cancelled_offer(DEAL_ID)
    )
    with rig:
        rig.call(api.cancel_sending_offer(DEAL_ID, OfferCancelReason.SKIN_UNAVAILABLE, "gone"))

        assert operations(rig) == [
            ("DealItem", {"id": DEAL_ID}),
            ("DealHistoryItem", {"id": DEAL_ID}),
            ("DealItem", {"customId": DEAL_ID}),
            (
                "DealCancelSendingOffer",
                {"comment": "gone", "id": OTHER_ID, "reason": "SKIN_UNAVAILABLE"},
            ),
        ]


@pytest.mark.parametrize("reason", list(OfferCancelReason), ids=lambda r: r.value)
def test_cancel_sending_offer_sends_the_reason_by_its_wire_value(
    flavor: Flavor, reason: OfferCancelReason
) -> None:
    rig, api = rig_of(flavor, cancelled_offer("order-42"))
    with rig:
        rig.call(api.cancel_sending_offer("order-42", reason, "x"))

        assert rig.variables()[0]["reason"] == reason.value


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("", id="empty"),
        pytest.param("a", id="one letter"),
        pytest.param("Az09 _-", id="every allowed kind of character"),
        pytest.param("a" * 255, id="exactly 255 characters"),
        pytest.param("   ", id="only spaces"),
    ],
)
def test_cancel_sending_offer_accepts_a_comment_within_the_rule(
    flavor: Flavor, comment: str
) -> None:
    rig, api = rig_of(flavor, cancelled_offer("order-42"))
    with rig:
        rig.call(api.cancel_sending_offer("order-42", OfferCancelReason.UNKNOWN, comment))

        assert rig.variables()[0]["comment"] == comment


@pytest.mark.parametrize(
    "comment",
    [
        pytest.param("a" * 256, id="256 characters"),
        pytest.param("a" * 1000, id="far too long"),
        pytest.param("café", id="a non-ASCII letter"),
        pytest.param("no!", id="an exclamation mark"),
        pytest.param("a.b", id="a dot"),
        pytest.param("line\nbreak", id="a newline in the middle"),
        pytest.param("ok\n", id="a trailing newline"),
        pytest.param("a\tb", id="a tab"),
        pytest.param("a\0b", id="a null byte"),
        pytest.param('say "hi"', id="a quote"),
    ],
)
def test_cancel_sending_offer_rejects_a_comment_outside_the_rule_before_any_request(
    flavor: Flavor, comment: str
) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="comment") as caught:
            rig.call(api.cancel_sending_offer(DEAL_ID, OfferCancelReason.UNKNOWN, comment))

        assert comment not in str(caught.value), "the comment is not echoed"
        assert rig.script.count == 0, "also for a UUID reference: no lookup either"


def test_cancel_sending_offer_names_the_violated_rule(flavor: Flavor) -> None:
    rig, api = rig_of(flavor)
    with rig:
        messages = []
        for comment in ("a" * 256, "no!"):
            with pytest.raises(ValueError, match="cancel comment") as caught:
                rig.call(api.cancel_sending_offer("order-42", OfferCancelReason.UNKNOWN, comment))
            messages.append(str(caught.value))

        assert messages == [
            "the cancel comment is longer than 255 characters",
            'the cancel comment may contain only the characters a-z, A-Z, 0-9, space, "_" and "-"',
        ]


def test_cancel_sending_offer_refuses_a_reason_the_schema_does_not_accept(flavor: Flavor) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="OfferCancelReason"):
            rig.call(api.cancel_sending_offer("order-42", OfferCancelReason("FUTURE"), "x"))

        assert rig.script.count == 0


MUTATIONS = {
    "request_cancel": lambda api: api.request_cancel(DEAL_ID),
    "report_offer_sent by custom id": lambda api: api.report_offer_sent("order-42", "5550001"),
    "cancel_sending_offer by custom id": lambda api: api.cancel_sending_offer(
        "order-42", OfferCancelReason.UNKNOWN, "x"
    ),
}


@pytest.mark.parametrize("call", list(MUTATIONS))
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(reply(503), ServiceUnavailableError, id="HTTP 503"),
        pytest.param(httpx.ConnectError("boom"), TransportError, id="network error"),
    ],
)
def test_a_mutation_is_sent_once_with_the_default_retry_policy(
    flavor: Flavor, call: str, failure: Any, expected: type[Exception]
) -> None:
    rig = ClientRig(flavor, failure, failure, failure)  # the client's default RetryPolicy
    api = deals_api(rig, Timeline())
    with rig:
        with pytest.raises(expected):
            rig.call(MUTATIONS[call](api))

        assert rig.script.count == 1


@pytest.mark.parametrize("call", ["report_offer_sent", "cancel_sending_offer"])
def test_a_mutation_with_an_empty_reference_fails_before_any_request(
    flavor: Flavor, call: str
) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="empty"):
            rig.call(reference_mutation(api, call, ""))

        assert rig.script.count == 0


def test_a_graphql_rejection_of_a_mutation_reaches_the_caller(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor,
        json_response(
            {"data": None, "errors": [{"message": "no", "extensions": {"category": "x.y"}}]}
        ),
    )
    with rig:
        with pytest.raises(GraphQLError) as caught:
            rig.call(api.request_cancel(DEAL_ID))

        assert caught.value.errors[0].category == "x.y"


# ---- hold balances ---------------------------------------------------------------------------


def test_hold_balance_sends_the_currency_and_maps_the_amount(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, data(deal_balance_hold={"currency": "USD", "value": "1234.560"}))
    with rig:
        money = rig.call(api.hold_balance(Currency.USD))

        assert operations(rig) == [("DealBalanceHold", {"currency": "USD"})]
        assert str(money) == "1234.560 USD"


def test_hold_balance_refuses_an_unknown_currency_before_sending(flavor: Flavor) -> None:
    rig, api = rig_of(flavor)
    with rig:
        with pytest.raises(ValueError, match="Currency"):
            rig.call(api.hold_balance(Currency("EUR")))

        assert rig.script.count == 0


def test_hold_balances_maps_every_currency(flavor: Flavor) -> None:
    rig, api = rig_of(
        flavor,
        data(
            deal_balances_hold=[
                {"currency": "USD", "value": "1.50"},
                {"currency": "EUR", "value": "0"},
            ]
        ),
    )
    with rig:
        held = rig.call(api.hold_balances())

        assert operations(rig) == [("DealBalancesHold", {})]
        assert [str(m) for m in held] == ["1.50 USD", "0 EUR"]
        assert held[1].currency.is_unknown


def test_hold_balances_is_empty_when_nothing_is_held(flavor: Flavor) -> None:
    rig, api = rig_of(flavor, data(deal_balances_hold=[]))
    with rig:
        assert rig.call(api.hold_balances()) == []
