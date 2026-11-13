"""Base of the generated client (`_generated/async_base_client.py` subclasses it)."""

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from whitemarket._async.executor import AsyncOperationExecutor
from whitemarket._runtime.decode import decode_error_from
from whitemarket._runtime.json_codec import to_plain
from whitemarket._runtime.operation import OperationType

_Model = TypeVar("_Model", bound=BaseModel)


class AsyncGraphQLBase:
    """Hands every operation to the executor with its type; decodes answers without leaking data."""

    def __init__(self, executor: AsyncOperationExecutor) -> None:
        self._executor = executor

    async def execute(
        self,
        document: str,
        variables: Mapping[str, object] | None = None,
        operation_name: str | None = None,
        *,
        operation_type: OperationType | None = None,
    ) -> dict[str, Any]:
        """Run a document and return the `data` object.

        The generated methods pass `operation_type`. A raw call that declares none runs as a
        mutation, so it is never retried (CLAUDE.md rule 2); declare a query to allow retries.
        """
        plain = cast("dict[str, object]", to_plain(variables or {}))  # a mapping stays a dict
        return await self._executor.execute(
            document, operation_name, plain, operation_type or "mutation"
        )

    def get_data(self, response: dict[str, Any]) -> dict[str, Any]:
        return response

    def _decode(self, model: type[_Model], data: dict[str, Any]) -> _Model:
        """Validate `data` into `model`; a mismatch is a `DecodeError`: a path and a reason only."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            error = decode_error_from(exc)
        # Raised outside the except block: no __context__ keeps the ValidationError and its input.
        raise error
