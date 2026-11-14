"""Turn a pydantic `ValidationError` into a `DecodeError` without response data (SDK_SPEC 8)."""

from pydantic import ValidationError

from whitemarket.errors import DecodeError

DecodePath = tuple[str | int, ...]
"""Where a value sits in a record: keys and indexes, outermost first."""


def decode_error_from(exc: ValidationError) -> DecodeError:
    """Build a `DecodeError` from the path and reason of the first problem and a count of the rest.

    Only `errors(include_input=False, include_url=False, include_context=False)` is read: pydantic
    prints the whole parent object of a missing field, which can include a sibling credential.
    The caller must raise the result outside its `except` block, so that no `__context__` keeps
    the original exception, and with it the input, alive.
    """
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    first = errors[0]
    reason = f"{first['type']}: {first['msg']}"
    if len(errors) > 1:
        reason += f" (and {len(errors) - 1} more)"
    return DecodeError(reason, first["loc"])
