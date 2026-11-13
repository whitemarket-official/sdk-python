"""Invariants over the generated source (ADR 0001, "Consequences"): what the plugin must guarantee.

Read from the committed files, so a plugin change that emits something else fails here and in
`make codegen-check`.
"""

import ast
import re
import warnings
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from whitemarket import Secret
from whitemarket._generated.input_types import (
    DecimalNotNullRangeInput,
    MarketProductSearchInput,
    MoneyInput,
    PersonStoreInput,
)
from whitemarket._runtime.json_codec import to_plain

GENERATED = Path(__file__).resolve().parents[3] / "src" / "whitemarket" / "_generated"
FILES = sorted(GENERATED.glob("*.py"))
CREDENTIAL = re.compile(
    r"token|secret|passw|authori[sz]ation|cookie|api_key|api-key|apikey|jwt|credential",
    re.IGNORECASE,
)


def _annotations(tree: ast.Module) -> list[ast.AnnAssign]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.AnnAssign)]


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_the_generated_files_are_found() -> None:
    assert len(FILES) >= 70, "one module per operation plus the shared ones"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_generated_file_says_do_not_edit(path: Path) -> None:
    assert path.read_text(encoding="utf-8").startswith("# DO NOT EDIT.")


def test_no_annotation_is_a_binary_float() -> None:
    # Float fields are Decimal (rule 3); the schema's wear and money values are strings already.
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in FILES
        for node in _annotations(ast.parse(path.read_text(encoding="utf-8")))
        if "float" in _names(node.annotation)
    ]
    assert offenders == []


def test_no_stock_discriminated_union_survives() -> None:
    # `Field(discriminator=...)` rejects an unknown __typename (rule 5); the plugin replaces it.
    offenders = [p.name for p in FILES if "discriminator=" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_credential_named_string_field_is_a_secret() -> None:
    offenders: list[str] = []
    secrets = 0
    for path in FILES:
        for node in _annotations(ast.parse(path.read_text(encoding="utf-8"))):
            target = node.target
            if not (isinstance(target, ast.Name) and CREDENTIAL.search(target.id)):
                continue
            names = _names(node.annotation)
            secrets += "Secret" in names
            if "str" in names:
                offenders.append(f"{path.name}:{target.id}")
    assert offenders == []
    assert secrets >= 2, "AuthTokens.accessToken and WalletDeposit.airwallexSecret at least"


def test_a_deprecated_input_field_is_marked_and_warns_on_access() -> None:
    field = MarketProductSearchInput.model_fields["price_from"]
    assert field.deprecated == "Use MoneyRangeInput $price instead"
    search = MarketProductSearchInput(price_from=MoneyInput(value="1", currency="USD"))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = search.price_from

    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_a_file_upload_input_field_is_dropped_and_its_encoded_twin_stays() -> None:
    assert "custom_avatar" not in PersonStoreInput.model_fields
    assert "encoded_custom_avatar" in PersonStoreInput.model_fields


def test_an_input_with_a_python_keyword_name_serialises_under_the_schema_name() -> None:
    # `from` is a keyword: the field is `from_` and only the wire name is `from`.
    assert to_plain(DecimalNotNullRangeInput(from_="1.5", to="2")) == {"from": "1.5", "to": "2"}


def test_a_float_input_field_is_a_decimal_and_rejects_text_that_is_no_number() -> None:
    assert MarketProductSearchInput(csgo_fade_from=Decimal("0.10")).csgo_fade_from == Decimal(
        "0.10"
    )
    with pytest.raises(ValidationError) as caught:
        MarketProductSearchInput(csgo_fade_from="not-a-number")
    assert "not-a-number" not in str(caught.value), "the models hide their input"


def test_secret_is_the_runtime_type_the_generated_code_imports() -> None:
    sources = " ".join(p.read_text(encoding="utf-8") for p in FILES)
    assert "from whitemarket._runtime.secret import Secret" in sources
    assert Secret.__module__ == "whitemarket._runtime.secret"
