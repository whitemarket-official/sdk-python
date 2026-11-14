"""The read-only guard: the smoke never sends a mutation through its generated client."""

import re
from collections.abc import Mapping
from typing import Any

from whitemarket._runtime.operation import OperationType
from whitemarket._sync.executor import OperationExecutor

_QUERY_DOCUMENT = re.compile(r"\A\s*query\b", re.ASCII)
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_]")


class ReadOnlyViolationError(Exception):
    """An operation that is not a query reached the smoke's executor; nothing was sent."""


class ReadOnlyExecutor:
    """Wraps the executor of the smoke's generated client (SDK_SPEC 6.4).

    Refuses, before anything is sent, every operation unless its declared type is `query` AND its
    document starts with `query`. Both are checked because they come from two independent places
    of the generated client. The one allowed mutation, `auth_token`, does not pass here: the SDK's
    token provider owns its own executor.
    """

    def __init__(self, inner: OperationExecutor) -> None:
        self._inner = inner

    def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: OperationType,
    ) -> dict[str, Any]:
        if operation_type != "query" or _QUERY_DOCUMENT.match(document) is None:
            name = _UNSAFE_NAME.sub("?", operation_name or "")
            raise ReadOnlyViolationError(f"the live smoke refuses to run {name}: it is not a query")
        return self._inner.execute(document, operation_name, variables, operation_type)
