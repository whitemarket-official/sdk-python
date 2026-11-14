"""Step results and the Markdown report (`var/live-smoke/report.md`, a workflow artifact).

A result holds the step name, PASS or FAIL, milliseconds, the exception class and the error
category. Never a message, an id or a URL: the report is an artifact of a public workflow run.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

_CLASS_NAME = re.compile(r"[A-Za-z0-9_.]{1,80}")
_CATEGORY = re.compile(r"[A-Za-z0-9_.\-]{1,64}")


class Status(StrEnum):
    PASSED = "PASS"
    FAILED = "FAIL"


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    status: Status
    milliseconds: int
    exception_class: str = ""
    category: str = ""


def safe_class_name(error: BaseException) -> str:
    name = type(error).__name__
    return name if _CLASS_NAME.fullmatch(name) else "(invalid)"


def safe_category(category: str | None) -> str:
    """A category the server sent, only when it looks like one; anything else is not echoed."""
    if category is None:
        return "(none)"
    return category if _CATEGORY.fullmatch(category) else "(invalid)"


def summary(results: list[StepResult]) -> str:
    failed = sum(1 for r in results if r.status is Status.FAILED)
    return f"PASS {len(results) - failed}, FAIL {failed}"


def exit_code(results: list[StepResult]) -> int:
    return 1 if any(r.status is Status.FAILED for r in results) else 0


def render(results: list[StepResult]) -> str:
    lines = [
        "# Live smoke report",
        "",
        "| Step | Result | ms | Exception | Category |",
        "| --- | --- | ---: | --- | --- |",
    ]
    lines.extend(
        f"| {r.name} | {r.status.value} | {r.milliseconds} | {r.exception_class} | {r.category} |"
        for r in results
    )
    lines += ["", summary(results), ""]
    return "\n".join(lines)
