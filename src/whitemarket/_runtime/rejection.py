"""Whether a failure of a mutation means the server did not run it (CLAUDE.md rule 2, SDK_SPEC 3.3).

A mutation is never resent, so the caller must know whether it may have happened. A request that
could not be encoded (nothing was sent), a malformed
request (400), a rejected credential (401 after the one refresh and replay) and a rate limit (429)
are rejections; so is a GraphQL error that can only have come from the root field itself. Every
other failure (a timeout, a 5xx, an unreadable answer, an unexpected exception) may have happened
after the mutation ran.
"""

from whitemarket._runtime.json_codec import RequestNotSentError
from whitemarket.errors.graphql import GraphQLError
from whitemarket.errors.http import AuthenticationError, BadRequestError, RateLimitError


def is_mutation_rejection(error: BaseException, field: str) -> bool:
    """True when `error` proves that the mutation `field` was not executed.

    A 200 answer carries partial `data` next to `errors` (WHITEMARKET_API.md 2). A rejection of the
    root field leaves no `field` value: `data` is null, or `{field: null}` (a nullable root field),
    and every error has no path or exactly `[field]`. Anything else is ambiguous and not a
    rejection: an empty or foreign `data` (no `field` key), a non-null `field` value (the mutation
    produced a result), an error on a nested path such as `[field, "item", "description"]` (the
    mutation ran), or an error entry that is not well formed (a malformed `path` must never read as
    "no path"). Residual: a root-path error raised after the effect was committed still reads as a
    rejection (needs the backend's category catalogue).
    """
    if isinstance(
        error, BadRequestError | AuthenticationError | RateLimitError | RequestNotSentError
    ):
        return True
    if not isinstance(error, GraphQLError) or not error.errors:
        return False
    data = error.partial_data
    if data is not None and (field not in data or data[field] is not None):
        return False
    return all(not e.malformed and e.path in ((), (field,)) for e in error.errors)


def is_batch_rejection(error: BaseException) -> bool:
    """True when `error` proves that a batch mutation (`*_multiple`) was not executed (SDK_SPEC 3.5
    rule 8).

    A batch resolver acts on its items one by one and can fail part-way, which also answers
    `data: null` with an error at the root field: that is not a rejection. A request error (parse,
    validation) is raised before execution, so its response has no `data` key at all (GraphQL spec,
    October 2021, 7.1.2) and every error has no path. HTTP 400, 401 (after the one refresh and
    replay) and 429 are rejections as for a single mutation.
    """
    if isinstance(
        error, BadRequestError | AuthenticationError | RateLimitError | RequestNotSentError
    ):
        return True
    if not isinstance(error, GraphQLError) or not error.errors or error.data_present:
        return False
    return all(not e.malformed and e.path == () for e in error.errors)
