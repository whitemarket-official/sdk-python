"""Invariants over every operation document in graphql/operations (SDK_SPEC 1.2).

Mirrors PHP `AbstractSelectionTest`, `ProductHistoryParamsSelectionTest` and
`HighLevelItemOrderSelectionTest`. Covers generated documents and hand-written overrides alike.
"""

from pathlib import Path

import pytest

from support import graphql_docs as docs

if not docs.available():
    pytest.skip("graphql/ and schema/ are not part of this checkout", allow_module_level=True)

OPERATION_FILES = docs.operation_files()
ITEM_ORDER_DOCUMENTS = ("market_list", "market_item", "market_my", "market_new", "market_edit")


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def _text(name: str) -> str:
    (path,) = (p for p in OPERATION_FILES if p.stem == name)
    return path.read_text(encoding="utf-8")


def test_the_documents_are_found() -> None:
    # 69 root fields (2026-11-13); far fewer means the glob broke and every other test is vacuous.
    assert len(OPERATION_FILES) >= 60


@pytest.mark.parametrize("path", OPERATION_FILES, ids=_id)
def test_every_interface_or_union_field_selects_typename(path: Path) -> None:
    missing = docs.abstract_fields_without_typename(path.read_text(encoding="utf-8"))
    assert missing == [], "interface or union fields without __typename"


def test_the_typename_check_catches_a_missing_typename() -> None:
    # `item` is an interface (InventoryItemInterface): the check must not be vacuous.
    bad = "query Q { market_list { edges { node { item { id } } } } }"
    good = "query Q { market_list { edges { node { item { __typename id } } } } }"
    assert docs.abstract_fields_without_typename(bad) == ["item (InventoryItemInterface)"]
    assert docs.abstract_fields_without_typename(good) == []


def test_deal_item_params_selections_are_found() -> None:
    # 13+ operations select a deal's product item (2026-11-02); far fewer means the scan broke.
    found = sum(
        len(docs.selections_of(p.read_text(encoding="utf-8"), "params", "MarketProductHistory"))
        for p in OPERATION_FILES
    )
    assert found >= 13


@pytest.mark.parametrize("path", OPERATION_FILES, ids=_id)
def test_a_deals_product_item_selects_neither_its_update_time_nor_its_order(path: Path) -> None:
    # The server fails `updatedAt` there with "Internal error occurred" and `params.order { id }`
    # with HTTP 500, and a mutation that selects either is rolled back (observed live 2026-11-02,
    # docs/WHITEMARKET_API.md).
    for selection in docs.selections_of(
        path.read_text(encoding="utf-8"), "params", "MarketProductHistory"
    ):
        names = docs.field_names(selection)
        assert "updatedAt" not in names
        assert "order" not in names
        assert "...CSGOInventoryItemFields" not in names, "the fragment holds updatedAt"


def test_the_params_check_catches_an_update_time_and_an_order() -> None:
    bad = (
        'query Q { deal_item(id: "x") { product { params { __typename '
        "... on CSGOInventoryItem { updatedAt order { id } } } } } }"
    )
    (selection,) = docs.selections_of(bad, "params", "MarketProductHistory")
    assert {"updatedAt", "order"} <= docs.field_names(selection)


@pytest.mark.parametrize("name", ITEM_ORDER_DOCUMENTS)
def test_an_item_order_selects_only_its_typename(name: str) -> None:
    # The high-level layer does not read `order`, and the server has failed `order` selections
    # before: the overrides in graphql/overrides keep it at `order { __typename }` (PHP
    # HighLevelItemOrderSelectionTest).
    selections = docs.selections_of(_text(name), "order")
    assert selections, "the item order selection is expected in the document"
    for selection in selections:
        assert docs.field_names(selection) == {"__typename"}
