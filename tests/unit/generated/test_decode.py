"""Decoding of generated results: unknown types and values, exact numbers, credentials.

Mirrors the PHP `GeneratedClientTest` and the decode part of
`MarketApiTest::searchDecodesAnInterfaceFieldAtTheDepthLimitByItsTypename` (CLAUDE.md rules 3, 5).
Every case runs through the async and the sync client. Responses are synthetic.
"""

import json
import traceback
from decimal import Decimal
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from support.executors import Harness
from support.payloads import market_list_payload, model_json
from whitemarket import Secret
from whitemarket._generated.auth_token import AuthToken
from whitemarket._generated.enums import DeliveryType, MarketDealStatus
from whitemarket._generated.fragments import MarketProductResultFields
from whitemarket._generated.market_edit_multiple import (
    MarketEditMultipleMarketEditMultipleProductMarketProduct,
    MarketEditMultipleMarketEditMultipleProductMarketProductUnknownTypename,
)
from whitemarket._generated.market_list import (
    MarketListMarketListEdgesNodeItemCSGOInventoryItem,
    MarketListMarketListEdgesNodeItemInventoryItemInterface,
)
from whitemarket._generated.wallet_deposits import WalletDepositsWalletDeposits
from whitemarket._runtime.json_codec import decode
from whitemarket.errors import DecodeError

KINDS = pytest.mark.parametrize("kind", ["async", "sync"])
CSGO_ITEM = MarketListMarketListEdgesNodeItemCSGOInventoryItem
CREDENTIAL = "synthetic-credential-4b1d"


def csgo_item(**overrides: Any) -> dict[str, Any]:
    item = model_json(CSGO_ITEM)
    item["__typename"] = "CSGOInventoryItem"
    item["product"] = None
    item["deal"] = None
    return {**item, **overrides}


def edges(result: Any) -> list[Any]:
    return [edge.node for edge in result.market_list.edges if edge and edge.node]


# --- interface and union selections with a type the snapshot does not know ---------------------
@KINDS
@pytest.mark.parametrize("typename", ["TF2InventoryItem", "CSGOInventoryItem", "BrandNewItem"])
def test_market_list_decodes_an_interface_at_the_depth_limit_by_its_typename(
    kind: str, typename: str
) -> None:
    # `product.item` is selected as `__typename id` only: known and unknown types both decode.
    product_model = get_args(CSGO_ITEM.model_fields["product"].annotation)[0]
    product = {**model_json(product_model), "item": {"__typename": typename, "id": "nested-1"}}
    product["store"] = None
    payload = market_list_payload([csgo_item(product=product)])

    result = Harness(kind, payload).call("market_list")

    (node,) = edges(result)
    assert isinstance(node.item, CSGO_ITEM)
    assert node.item.product.item.typename__ == typename
    assert node.item.product.item.id == "nested-1"


@KINDS
def test_market_list_decodes_an_unknown_item_type_to_the_interface_member(kind: str) -> None:
    unknown = {"__typename": "DOTA2InventoryItem", "id": "i-9", "brandNewField": 1}
    payload = market_list_payload([csgo_item(), unknown])

    result = Harness(kind, payload).call("market_list")

    known, other = edges(result)
    assert isinstance(known.item, CSGO_ITEM)
    assert isinstance(other.item, MarketListMarketListEdgesNodeItemInventoryItemInterface)
    assert other.item.typename__ == "DOTA2InventoryItem"


@KINDS
def test_a_union_with_every_member_selected_gets_an_unknown_fallback(kind: str) -> None:
    product_type = MarketEditMultipleMarketEditMultipleProductMarketProduct
    row = model_json(MarketProductResultFields)
    known = {**model_json(product_type), "__typename": "MarketProduct", "item": None}
    known["store"] = None
    data = {
        "market_edit_multiple": [
            {**row, "product": known},
            {**row, "product": {"__typename": "MarketProductDraft", "x": 1}},
        ]
    }

    result = Harness(kind, data).call("market_edit_multiple", items=[])

    first, second = (r.product for r in result.market_edit_multiple)
    assert isinstance(first, product_type)
    assert isinstance(
        second, MarketEditMultipleMarketEditMultipleProductMarketProductUnknownTypename
    )
    assert second.typename__ == "MarketProductDraft"


# --- enums ------------------------------------------------------------------------------------
@KINDS
def test_an_unknown_enum_value_decodes_to_the_unknown_member_with_its_raw_value(kind: str) -> None:
    payload = market_list_payload([csgo_item()])
    payload["market_list"]["edges"][0]["node"]["deliveryType"] = "TELEPORT"

    result = Harness(kind, payload).call("market_list")

    (node,) = edges(result)
    assert node.delivery_type.is_unknown
    assert node.delivery_type.value == "TELEPORT"
    assert node.delivery_type not in list(DeliveryType), "not a declared member"
    assert DeliveryType("TELEPORT") == "TELEPORT"


def test_a_known_enum_value_is_the_declared_member() -> None:
    assert MarketDealStatus("COMPLETED") is MarketDealStatus.COMPLETED
    assert not MarketDealStatus.COMPLETED.is_unknown


def test_a_non_string_enum_value_is_still_an_error() -> None:
    with pytest.raises(ValueError, match="is not a valid"):
        MarketDealStatus(5)


# --- exact numbers ----------------------------------------------------------------------------
@KINDS
def test_a_float_scalar_decodes_to_the_exact_decimal_of_the_wire_text(kind: str) -> None:
    placeholder = "@@FADE@@"
    payload = market_list_payload([csgo_item(fade=placeholder, amount=2**63 + 1)])
    body = json.dumps({"data": payload}).replace(f'"{placeholder}"', "95.130000000000000001")

    data = decode(body)["data"]
    result = Harness(kind, data).call("market_list")

    (node,) = edges(result)
    assert node.item.fade == Decimal("95.130000000000000001")
    assert isinstance(node.item.fade, Decimal)
    assert node.item.amount == 2**63 + 1, "integers beyond 2^53 stay exact"


def test_the_64_bit_ids_are_strings() -> None:
    fields = CSGO_ITEM.model_fields
    assert {name: fields[name].annotation for name in ("asset_id", "class_id", "instance_id")} == {
        "asset_id": str,
        "class_id": str,
        "instance_id": str,
    }


# --- credential fields ------------------------------------------------------------------------
@KINDS
def test_a_credential_field_decodes_into_a_secret_that_never_prints(kind: str) -> None:
    data = {"auth_token": {"accessToken": CREDENTIAL, "isNewPerson": False}}

    result = Harness(kind, data).call("auth_token")

    token = result.auth_token.access_token
    assert isinstance(token, Secret)
    assert token.reveal() == CREDENTIAL
    renderings = (repr(result), str(result), result.model_dump_json(), str(result.model_dump()))
    assert all(CREDENTIAL not in rendering for rendering in renderings)
    dumped = result.model_dump(mode="json")["auth_token"]
    assert list(dumped.values()).count("***") == 1, "a dump masks the credential"


def test_a_secret_in_a_list_item_decodes_too() -> None:
    row = model_json(WalletDepositsWalletDeposits)
    row["airwallexSecret"] = CREDENTIAL

    parsed = WalletDepositsWalletDeposits.model_validate(row)

    assert isinstance(parsed.airwallex_secret, Secret)
    assert parsed.airwallex_secret.reveal() == CREDENTIAL


MALFORMED_NEXT_TO_A_CREDENTIAL = [
    pytest.param(
        "auth_token",
        {"auth_token": {"accessToken": CREDENTIAL, "isNewPerson": "nope"}},
        ("auth_token", "isNewPerson"),
        id="object: bad sibling of accessToken",
    ),
    pytest.param(
        "auth_token",
        {"auth_token": {"accessToken": CREDENTIAL}},  # pydantic prints the whole parent for this
        ("auth_token", "isNewPerson"),
        id="object: missing sibling of accessToken",
    ),
    pytest.param(
        "wallet_deposits",
        {
            "wallet_deposits": [
                {
                    **model_json(WalletDepositsWalletDeposits),
                    "airwallexSecret": CREDENTIAL,
                    "comment": 5,
                }
            ]
        },
        ("wallet_deposits", 0, "comment"),
        id="list: bad sibling of airwallexSecret",
    ),
]


@KINDS
@pytest.mark.parametrize(("method", "data", "path"), MALFORMED_NEXT_TO_A_CREDENTIAL)
def test_a_malformed_sibling_of_a_credential_gives_a_decode_error_without_the_credential(
    kind: str, method: str, data: dict[str, Any], path: tuple[str | int, ...]
) -> None:
    with pytest.raises(DecodeError) as caught:
        Harness(kind, data).call(method)

    error = caught.value
    assert error.path == path, "the malformed sibling failed, not the credential"
    assert error.__cause__ is None
    assert error.__context__ is None, "the ValidationError, which holds the input, is not kept"
    everything = " ".join(
        [
            str(error),
            repr(error),
            repr(error.args),
            error.reason,
            *traceback.format_exception(error),
        ]
    )
    assert CREDENTIAL not in everything


@KINDS
def test_a_decode_error_carries_the_path_and_the_reason_only(kind: str) -> None:
    data = {"auth_token": {"accessToken": CREDENTIAL, "isNewPerson": "not-a-bool-marker"}}

    with pytest.raises(DecodeError) as caught:
        Harness(kind, data).call("auth_token")

    assert caught.value.path == ("auth_token", "isNewPerson")
    assert caught.value.reason == (
        "bool_parsing: Input should be a valid boolean, unable to interpret input"
    )
    assert str(caught.value) == f"auth_token.isNewPerson: {caught.value.reason}"
    assert "not-a-bool-marker" not in repr(caught.value)


def test_the_generated_models_hide_their_input_in_validation_errors() -> None:
    with pytest.raises(ValidationError) as caught:
        AuthToken.model_validate({"auth_token": {"accessToken": CREDENTIAL}})

    assert CREDENTIAL not in str(caught.value), "defence in depth: hide_input_in_errors"
