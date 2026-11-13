"""Runs one GraphQL operation over the transport and maps the answer (SDK_SPEC 1.4, 1.5)."""

from collections.abc import Mapping
from typing import Any, cast

from whitemarket._async.credentials import AsyncCredentials
from whitemarket._async.transport import AsyncGraphQLTransport
from whitemarket._runtime import json_codec
from whitemarket._runtime.operation import OperationType
from whitemarket.errors.base import DecodeError
from whitemarket.errors.graphql import GraphQLError
from whitemarket.errors.http import AuthenticationError


class AsyncGraphQLExecutor:
    """Sends `{query, operationName, variables}` and returns the `data` object.

    A 401 refreshes the credentials once and replays the request once, mutations included: the
    JWT check runs before the resolver, so a 401 means the request was not executed (SDK_SPEC 1.4,
    the one exception to "a mutation is never retried"). A second 401 is an `AuthenticationError`.
    """

    def __init__(self, transport: AsyncGraphQLTransport, credentials: AsyncCredentials) -> None:
        self._transport = transport
        self._credentials = credentials

    async def execute(
        self,
        document: str,
        operation_name: str | None,
        variables: Mapping[str, object],
        operation_type: OperationType,
    ) -> dict[str, Any]:
        body = _encode(document, operation_name, variables)
        name = operation_name or ""
        response = await self._post_with_one_replay(name, operation_type, body)
        return _data_or_raise(response)

    async def _post_with_one_replay(
        self, name: str, operation_type: OperationType, body: bytes
    ) -> bytes:
        headers = await self._credentials.headers(name)
        try:
            return await self._transport.post(name, operation_type, body, headers)
        except AuthenticationError:
            replay = await self._credentials.headers_after_rejection(headers)
            if replay is None:
                raise
        return await self._transport.post(name, operation_type, body, replay)


def _encode(document: str, operation_name: str | None, variables: Mapping[str, object]) -> bytes:
    payload: dict[str, object] = {"query": document}
    if operation_name:
        payload["operationName"] = operation_name
    payload["variables"] = dict(variables)
    text = json_codec.encode(payload)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        pass
    # Raised outside the handler: no __context__ keeps the text, which may hold a secret.
    raise ValueError("the request holds text that is not valid Unicode")


def _decode_body(body: bytes) -> object:
    failure = ""
    try:
        return json_codec.decode(body)
    except (ValueError, RecursionError):
        failure = "the response is not valid JSON"
    raise DecodeError(failure)


def _data_or_raise(body: bytes) -> dict[str, Any]:
    response = _decode_body(body)
    if not isinstance(response, dict):
        raise DecodeError("the response is not a JSON object")
    fields = cast("dict[str, Any]", response)
    data = fields.get("data")
    if data is not None and not isinstance(data, dict):
        raise DecodeError("expected an object or null", ("data",))
    errors = fields.get("errors")
    if errors is None:
        errors = []
    if not isinstance(errors, list):
        raise DecodeError("expected a list", ("errors",))
    if errors:
        raise GraphQLError.from_payload(
            cast("list[object]", errors), cast("dict[str, Any] | None", data)
        )
    if data is None:
        raise DecodeError("missing in a response without errors", ("data",))
    return cast("dict[str, Any]", data)
