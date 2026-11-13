"""The kind of a GraphQL operation: the transport retries queries and never retries mutations
(SDK_SPEC 1.4)."""

from typing import Literal

OperationType = Literal["query", "mutation"]
