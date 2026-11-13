"""The operation documents of `graphql/` against the schema snapshot (graphql-core, tests only)."""

from collections.abc import Iterator
from functools import cache
from pathlib import Path

from graphql import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLSchema,
    SelectionSetNode,
    TypeInfo,
    TypeInfoVisitor,
    Visitor,
    build_schema,
    get_named_type,
    is_abstract_type,
    parse,
    visit,
)

REPO = Path(__file__).resolve().parents[2]
OPERATIONS = REPO / "graphql" / "operations"
FRAGMENTS = REPO / "graphql" / "fragments"
SCHEMA = REPO / "schema" / "partner.graphql"


def available() -> bool:
    """False when the sources are not here (the sdist has `tests/` but no `graphql/`, `schema/`)."""
    return OPERATIONS.is_dir() and FRAGMENTS.is_dir() and SCHEMA.is_file()


@cache
def schema() -> GraphQLSchema:
    return build_schema(SCHEMA.read_text(encoding="utf-8"))


@cache
def fragments() -> dict[str, FragmentDefinitionNode]:
    result: dict[str, FragmentDefinitionNode] = {}
    for path in sorted(FRAGMENTS.glob("*.graphql")):
        for definition in parse(path.read_text(encoding="utf-8")).definitions:
            if isinstance(definition, FragmentDefinitionNode):
                result[definition.name.value] = definition
    return result


def operation_files() -> list[Path]:
    return sorted([*OPERATIONS.glob("query/*.graphql"), *OPERATIONS.glob("mutation/*.graphql")])


def parse_text(text: str) -> DocumentNode:
    """A document with the fragments reachable from it appended."""
    document = parse(text)
    wanted = _spreads(document)
    known = fragments()
    seen: dict[str, FragmentDefinitionNode] = {}
    while wanted:
        name = wanted.pop()
        if name in seen or name not in known:
            continue
        seen[name] = known[name]
        wanted.update(_spreads(known[name]))
    return DocumentNode(definitions=(*document.definitions, *seen.values()))


def _spreads(node: object) -> set[str]:
    names: set[str] = set()

    class Collect(Visitor):
        def enter_fragment_spread(self, spread: FragmentSpreadNode, *_: object) -> None:
            names.add(spread.name.value)

    visit(node, Collect())
    return names


def abstract_fields_without_typename(text: str) -> list[str]:
    """Interface or union fields whose selection lacks a direct `__typename`."""
    document = parse_text(text)
    info = TypeInfo(schema())
    missing: list[str] = []

    class Check(Visitor):
        def enter_field(self, node: FieldNode, *_: object) -> None:
            type_ = info.get_type()
            if type_ is None or node.selection_set is None:
                return
            if not is_abstract_type(get_named_type(type_)):
                return
            if not any(
                isinstance(s, FieldNode) and s.name.value == "__typename"
                for s in node.selection_set.selections
            ):
                missing.append(f"{node.name.value} ({type_})")

    visit(document, TypeInfoVisitor(info, Check()))
    return missing


def _field_names(selection_set: SelectionSetNode | None) -> Iterator[str]:
    """Field names written in a selection (inline fragments expanded); a spread is `...Name`."""
    if selection_set is None:
        return
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            yield selection.name.value
            yield from _field_names(selection.selection_set)
        elif isinstance(selection, FragmentSpreadNode):
            yield f"...{selection.name.value}"  # opaque: the block is judged by what it spells out
        else:
            yield from _field_names(selection.selection_set)


def selections_of(text: str, field: str, parent_type: str | None = None) -> list[SelectionSetNode]:
    """The selection sets of every `field` (of `parent_type`, if given) in a document."""
    document = parse_text(text)
    info = TypeInfo(schema())
    found: list[SelectionSetNode] = []

    class Collect(Visitor):
        def enter_field(self, node: FieldNode, *_: object) -> None:
            parent = info.get_parent_type()
            if node.name.value != field or node.selection_set is None:
                return
            if parent_type is None or (parent is not None and parent.name == parent_type):
                found.append(node.selection_set)

    visit(document, TypeInfoVisitor(info, Collect()))
    return found


def field_names(selection_set: SelectionSetNode) -> set[str]:
    return set(_field_names(selection_set))
