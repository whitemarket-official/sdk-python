"""Turns the exception of a step into PASS or FAIL (SPEC_SYNC 4, approved 2026-11-02)."""

from live_smoke.report import Status, StepResult, safe_category, safe_class_name
from whitemarket.errors import GraphQLError, NotFoundError

# Categories that mean the call did not really reach the business logic.
UNREACHABLE_PREFIXES = ("auth", "internal", "server")


def is_reachable(error: GraphQLError) -> bool:
    """A categorized GraphQL error proves the operation is reachable and its answer decoded.

    Not found always counts. Otherwise every error needs a category and none may start with
    auth, internal or server (case-insensitive).
    """
    if isinstance(error, NotFoundError):
        return True
    for entry in error.errors:
        category = entry.category
        if not category or category.lower().startswith(UNREACHABLE_PREFIXES):
            return False
    return True


def classify(name: str, error: Exception, milliseconds: int) -> StepResult:
    """The class name and, for GraphQL errors, the sanitised categories. Never the message."""
    categories = ""
    if isinstance(error, GraphQLError):
        if is_reachable(error):
            return StepResult(
                name, Status.PASSED, milliseconds, safe_class_name(error), "reachable"
            )
        categories = ",".join(sorted({safe_category(e.category) for e in error.errors}))
    return StepResult(name, Status.FAILED, milliseconds, safe_class_name(error), categories)
