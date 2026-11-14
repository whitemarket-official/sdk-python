"""Synthetic wire JSON of the selling operations (`market_new`, `*_multiple`, `market_my`, ...).

Every builder starts from `model_json` of the generated model of the operation and sets what a test
cares about; values are invented, never recorded.
"""

import importlib
from dataclasses import dataclass
from typing import Any

from support import market_payloads as mp
from support.http import Reply, data
from support.payloads import model_json
from whitemarket._generated.market_my import MarketMyMarketMyEdgesNode

PRODUCT_ID = "7d1c0e52-3b8a-4f6d-9a21-5e4c8b7f0a13"
OTHER_ID = "11111111-1111-4111-8111-111111111111"
INVENTORY_ID = "0b6c1c0a-5a44-4e49-8f27-1f2d3c4b5a69"
ASSET_ID = "9007199254740993"  # beyond 2^53: must stay a string
PRICE = {"currency": "USD", "value": "12.50"}


def product_as(model: Any, **overrides: Any) -> dict[str, Any]:
    """A live listing (`MarketProduct`) shaped like `model`: the fields of `mp.product()` that
    `model` has, every other field at its smallest valid value."""
    base = model_json(model)
    base.update({name: value for name, value in mp.product().items() if name in base})
    return {**base, **overrides}


def history_as(model: Any, **overrides: Any) -> dict[str, Any]:
    """An archived listing (`MarketProductHistory`) shaped like `model`."""
    base = model_json(model)
    shared = {k: v for k, v in mp.history_product().items() if k not in ("description", "params")}
    base.update({name: value for name, value in shared.items() if name in base})
    return {**base, **overrides}


@dataclass(frozen=True)
class Batch:
    """The generated models of one `*_multiple` operation."""

    field: str  # the root field, e.g. `market_new_multiple`
    operation: str  # the operation name, e.g. `MarketNewMultiple`

    def _model(self, suffix: str) -> Any:
        module = importlib.import_module(f"whitemarket._generated.{self.field}")
        return getattr(module, f"{self.operation}{self.operation}{suffix}")

    def live(self, product_id: str, **overrides: Any) -> dict[str, Any]:
        model = self._model("ProductMarketProduct")
        return product_as(model, id=product_id, slug=f"slug-{product_id[:8]}", **overrides)

    def archived(self, product_id: str, **overrides: Any) -> dict[str, Any]:
        model = self._model("ProductMarketProductHistory")
        return history_as(model, id=product_id, **overrides)

    def row(
        self,
        index: int,
        created: bool = True,
        product: dict[str, Any] | None = None,
        category: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        row = model_json(self._model(""))
        row.update(
            {
                "index": index,
                "isCreated": created,
                "errorCategory": category,
                "errorMessage": message,
                "product": product,
            }
        )
        return row

    def answer(self, rows: list[dict[str, Any]]) -> Reply:
        return data(**{self.field: rows})

    def rows_for(self, count: int, prefix: str, first: int = 0) -> list[dict[str, Any]]:
        """`count` succeeded rows for the positions `0..count-1`, each with a live product whose
        id is `<prefix>-<first + position>` (a product without an item skips the identity check)."""
        return [
            self.row(i, True, self.live(f"{prefix}-{first + i}", item=None)) for i in range(count)
        ]


NEW = Batch("market_new_multiple", "MarketNewMultiple")
EDIT = Batch("market_edit_multiple", "MarketEditMultiple")
REMOVE = Batch("market_remove_multiple", "MarketRemoveMultiple")


def my_products_data(
    slugs: list[str], end_cursor: str | None = None, has_next_page: bool = False
) -> dict[str, Any]:
    """The `data` of a `market_my` answer with one listing per slug."""
    edges = [
        {
            "cursor": f"c-{slug}",
            "node": product_as(MarketMyMarketMyEdgesNode, id=f"id-{slug}", slug=slug, item=None),
        }
        for slug in slugs
    ]
    return {
        "market_my": {
            "edges": edges,
            "pageInfo": mp.page_info(end_cursor, has_next_page),
            "totalCount": 3,
        }
    }
