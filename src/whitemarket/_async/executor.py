"""The seam between the generated client and the transport."""

from collections.abc import Mapping
from typing import Any, Protocol

from whitemarket._runtime.operation import OperationType


class AsyncOperationExecutor(Protocol):
    """Runs one GraphQL operation and returns the `data` object of the answer.

    The real implementation is `AsyncGraphQLExecutor` (`_async/graphql.py`): HTTP, auth, retries,
    error mapping.
    `variables` is plain JSON data (`whitemarket._runtime.json_codec.to_plain`): exact numbers are
    `Decimal`, there is no float. An implementation may retry `operation_type="query"` per the
    retry table (SDK_SPEC 1.4) and never retries a mutation.
    """

    async def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: OperationType,
    ) -> dict[str, Any]: ...
