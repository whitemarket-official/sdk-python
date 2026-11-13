"""The kind of a GraphQL operation: the transport retries queries and never retries mutations
(SDK_SPEC 1.4)."""

import re
from typing import Final, Literal

OperationType = Literal["query", "mutation"]

# Ignored tokens before the first definition: BOM, whitespace, commas and `#` comments.
_IGNORED_PREFIX: Final = r"^﻿?(?:[\s,]+|#[^\r\n]*)*"
_FIRST_TOKEN: Final = re.compile(
    _IGNORED_PREFIX + r"(query\b|mutation\b|subscription\b|fragment\b|\{)", re.ASCII
)
_MUTATION_WORD: Final = re.compile(r"\bmutation\b", re.ASCII)


def infer_operation_type(document: str) -> OperationType:
    """`query` only for a document that is clearly a query, otherwise `mutation`.

    Clearly a query: the first definition is `query ...` or the `{ ... }` shorthand and the word
    `mutation` appears nowhere (a second operation, even inside a comment, may run one). A
    document that starts with a fragment may hold its operation anywhere, so it is not guessed.
    Everything else is a mutation, and a mutation is never retried (CLAUDE.md rule 2): a wrong
    guess costs a retry, never a repeated purchase.
    """
    if _MUTATION_WORD.search(document) is not None:
        return "mutation"
    match = _FIRST_TOKEN.match(document)
    if match is None:
        return "mutation"
    return "query" if match.group(1) in ("query", "{") else "mutation"


def effective_operation_type(document: str, declared: OperationType) -> OperationType:
    """The type the transport acts on: a declared `query` never outranks the document.

    A declaration may only downgrade (`query` to `mutation`); a document that is not clearly a
    query runs as a mutation, whatever a caller declared (CLAUDE.md rule 2).
    """
    if declared == "mutation":
        return "mutation"
    return infer_operation_type(document)
