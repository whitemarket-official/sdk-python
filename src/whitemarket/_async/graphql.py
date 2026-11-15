"""Runs one GraphQL operation over the transport and maps the answer (SDK_SPEC 1.4, 1.5)."""

from collections.abc import Mapping
from typing import Any, Final, cast

from whitemarket._async.credentials import AsyncCredentials
from whitemarket._async.transport import AsyncGraphQLTransport
from whitemarket._runtime import json_codec
from whitemarket._runtime.attempts import AttemptBudget
from whitemarket._runtime.body import BodyBytes
from whitemarket._runtime.json_codec import RequestNotSentError
from whitemarket._runtime.operation import OperationType, effective_operation_type
from whitemarket.errors.base import DecodeError
from whitemarket.errors.graphql import GraphQLError
from whitemarket.errors.http import AuthenticationError

# Root fields whose answer carries a credential (a JWT, a proxy URL that may hold a password). They
# never reach `GraphQLError.partial_data`, which is raw server data and not redacted.
_CREDENTIAL_FIELDS: Final = frozenset({"auth_token", "auth_steam_jwt", "profile_steam_proxy_get"})


class AsyncGraphQLExecutor:
    """Sends `{query, operationName, variables}` and returns the `data` object.

    A 401 refreshes the credentials once and replays the request once, mutations included: the
    JWT check runs before the resolver, so a 401 means the request was not executed (SDK_SPEC 1.4,
    the one exception to "a mutation is never retried"). A second 401 is an `AuthenticationError`.
    The replay shares the call's attempt budget: a query sends at most `max_attempts` requests in
    total, a 401 on the last attempt is still replayed once and not retried; a mutation is sent at
    most twice.
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
        # Whatever the caller declared, a document that is not clearly a query is never retried.
        operation_type = effective_operation_type(document, operation_type)
        response = await self._post_with_one_replay(name, operation_type, body)
        return _data_or_raise(response)

    async def _post_with_one_replay(
        self, name: str, operation_type: OperationType, body: bytes
    ) -> BodyBytes:
        headers = await self._credentials.headers(name)
        budget = AttemptBudget()
        try:
            return await self._transport.post(name, operation_type, body, headers, budget)
        except AuthenticationError:
            replay = await self._credentials.headers_after_rejection(headers)
            if replay is None:
                raise
        return await self._transport.post(name, operation_type, body, replay, budget)


def _encode(document: str, operation_name: str | None, variables: Mapping[str, object]) -> bytes:
    """The request body. A value that cannot be encoded is a `RequestNotSentError`: nothing has
    been sent yet, so a mutation caller can tell it from an ambiguous failure."""
    payload: dict[str, object] = {"query": document}
    if operation_name:
        payload["operationName"] = operation_name
    payload["variables"] = dict(variables)
    failure = ""
    try:
        return json_codec.encode(payload).encode("utf-8")
    except UnicodeEncodeError:
        failure = "the request holds text that is not valid Unicode"
    except (TypeError, ValueError) as error:
        failure = str(error)
    # Raised outside the handlers: no __context__ keeps the text, which may hold a secret.
    raise RequestNotSentError(failure)


def _decode_body(body: BodyBytes) -> object:
    failure = ""
    try:
        return json_codec.decode(body)
    except (ValueError, RecursionError):
        failure = "the response is not valid JSON"
    raise DecodeError(failure)


def _data_or_raise(body: BodyBytes) -> dict[str, Any]:
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
            cast("list[object]", errors),
            _without_credentials(cast("dict[str, Any] | None", data)),
            data_present="data" in fields,
        )
    if data is None:
        raise DecodeError("missing in a response without errors", ("data",))
    return cast("dict[str, Any]", data)


def _without_credentials(data: dict[str, Any] | None) -> dict[str, Any] | None:
    # Only the credential values go; the shape stays. A credential-only `data` object becomes `{}`,
    # never None: None means "the response had no data", and the rejection classification
    # (`is_mutation_rejection`) must not read a stripped answer as one (SDK_SPEC 3.3 rule 6).
    if data is None:
        return None
    return {name: value for name, value in data.items() if name not in _CREDENTIAL_FIELDS}
