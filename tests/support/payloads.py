"""Synthetic response payloads built from the generated models (no real data).

`model_json` fills every field with the smallest valid JSON value, so a test states only what it
cares about and overrides that.
"""

import types
import typing
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from whitemarket._generated.market_list import MarketListMarketListEdgesNode
from whitemarket._runtime.secret import Secret


def _fill(tp: Any) -> Any:
    origin = get_origin(tp)
    result: Any
    if origin is typing.Annotated:
        result = _fill(get_args(tp)[0])
    elif origin in (Union, types.UnionType):
        args = get_args(tp)
        result = None if type(None) in args else _fill(args[0])
    elif origin is list:
        result = []
    elif origin is typing.Literal:
        result = get_args(tp)[0]
    elif isinstance(tp, type) and issubclass(tp, BaseModel):
        result = model_json(tp)
    elif isinstance(tp, type) and issubclass(tp, Enum):
        result = next(iter(tp)).value
    elif tp is str or tp is Secret:
        result = "x"
    elif tp is bool:
        result = False
    elif tp is int:
        result = 1
    elif tp is Decimal:
        result = Decimal(1)
    elif "AwareDatetime" in repr(tp) or tp is datetime:
        result = "2026-01-01T00:00:00+00:00"
    else:
        raise TypeError(f"cannot synthesise a value for {tp!r}")
    return result


def model_json(model: type[BaseModel]) -> dict[str, Any]:
    """The smallest valid JSON object of `model`, keyed by the GraphQL (alias) names."""
    return {
        field.alias or name: _fill(field.annotation) for name, field in model.model_fields.items()
    }


def market_list_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    """A `market_list` data object with one edge per item (`node.item`)."""
    edges: list[dict[str, Any]] = []
    for item in items:
        node = model_json(MarketListMarketListEdgesNode)
        node["item"] = item
        edges.append({"cursor": "c", "node": node})
    return {
        "market_list": {
            "edges": edges,
            "pageInfo": {
                "hasNextPage": False,
                "hasPreviousPage": False,
                "startCursor": None,
                "endCursor": None,
            },
            "totalCount": len(items),
        }
    }
