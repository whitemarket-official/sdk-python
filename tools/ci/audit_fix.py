"""Helpers of the dependency-audit workflow (.github/workflows/dependency-audit.yml), stdlib only.

    audit_fix.py requirements PYPROJECT [codegen]  print the declared requirements, one per line
    audit_fix.py fix AUDIT_JSON PYPROJECT REPORT raise the exact pins that pip-audit flags

`fix` rewrites an exact `==` pin in pyproject.toml to the lowest version that fixes every advisory
of the package and appends a Markdown table to REPORT. Exit codes: 0 nothing left to fix by hand,
1 advisories remain (a transitive package, a lower-bound range, no fixed version), 2 usage or
input error. Nothing from the audited packages is imported or run.
"""

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NAME = re.compile(r"[-_.]+")
_VERSION = re.compile(r"\d+(?:\.\d+)*")


def normalize(name: str) -> str:
    """PEP 503 normalized name."""
    return _NAME.sub("-", name).lower()


CODEGEN_EXTRA = (
    "codegen"  # resolved on its own: ariadne-codegen's ruff range conflicts with the dev pin
)


def requirements(pyproject: dict[str, Any], *, codegen: bool = False) -> list[str]:
    """Runtime dependencies and every extra but `codegen`; with `codegen=True` only that extra.

    The project's own `whitemarket-sdk[...]` entries are left out.
    """
    project = pyproject["project"]
    extras: dict[str, list[str]] = project.get("optional-dependencies", {})
    if codegen:
        found = list(extras[CODEGEN_EXTRA])
    else:
        found = list(project.get("dependencies", []))
        for name, extra in extras.items():
            if name != CODEGEN_EXTRA:
                found.extend(extra)
    own = normalize(str(project["name"]))
    return sorted(
        {r for r in found if normalize(re.split(r"[\[<>=!~; ]", r, maxsplit=1)[0]) != own}
    )


def _numbers(version: str) -> tuple[int, ...] | None:
    return tuple(int(p) for p in version.split(".")) if _VERSION.fullmatch(version) else None


@dataclass(frozen=True)
class Change:
    package: str
    advisories: tuple[str, ...]
    before: str
    after: str


def target_version(current: str, fix_versions: list[list[str]]) -> str | None:
    """Lowest version above `current` that fixes every advisory, or None when there is none.

    Each advisory contributes the lowest of its fix versions that is newer than `current`; the
    answer is the highest of those, so one bump fixes them all.
    """
    now = _numbers(current)
    if now is None or not fix_versions:
        return None
    best: tuple[int, ...] | None = None
    best_text = ""
    for versions in fix_versions:
        newer = [(n, v) for v in versions if (n := _numbers(v)) is not None and n > now]
        if not newer:
            return None
        number, text = min(newer)
        if best is None or number > best:
            best, best_text = number, text
    return best_text


def plan_fixes(audit: dict[str, Any], pyproject_text: str) -> tuple[str, list[Change], list[str]]:
    """The rewritten pyproject text, the pins raised and the packages that need a human."""
    changes: list[Change] = []
    remaining: list[str] = []
    text = pyproject_text
    for dep in audit.get("dependencies", []):
        vulns = dep.get("vulns") or []
        if not vulns:
            continue
        name, current = str(dep["name"]), str(dep["version"])
        target = target_version(current, [list(v.get("fix_versions") or []) for v in vulns])
        pin = re.compile(
            rf'(?P<head>"{re.escape(name)}(?:\[[^\]]*\])?==)(?P<old>{re.escape(current)})(?P<tail>")',
            re.IGNORECASE,
        )
        if target is None or pin.search(text) is None:
            remaining.append(name)
            continue
        text = pin.sub(rf"\g<head>{target}\g<tail>", text)
        ids = tuple(sorted(str(v["id"]) for v in vulns))
        changes.append(Change(name, ids, current, target))
    return text, changes, remaining


def render(changes: list[Change], remaining: list[str]) -> str:
    if not changes and not remaining:
        return ""
    lines = ["### pyproject.toml", ""]
    if changes:
        lines += ["| Package | Advisories | Before | After |", "|---|---|---|---|"]
        lines += [
            f"| `{c.package}` | {', '.join(c.advisories)} | `{c.before}` | `{c.after}` |"
            for c in changes
        ]
        lines.append("")
    if remaining:
        lines += [
            "**Needs a human** (transitive package, lower-bound range or no fixed version): "
            + ", ".join(f"`{r}`" for r in remaining),
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    match argv[1:]:
        case ["requirements", path, *rest] if rest in ([], [CODEGEN_EXTRA]):
            found = requirements(tomllib.loads(Path(path).read_text()), codegen=bool(rest))
            sys.stdout.write("\n".join(found) + "\n")
            return 0
        case ["fix", audit_path, pyproject_path, report_path]:
            audit = json.loads(Path(audit_path).read_text())
            pyproject = Path(pyproject_path)
            text, changes, remaining = plan_fixes(audit, pyproject.read_text())
            if changes:
                pyproject.write_text(text)
            with Path(report_path).open("a") as report:
                report.write(render(changes, remaining))
            sys.stdout.write(
                f"raised {len(changes)} pin(s); {len(remaining)} package(s) need a human\n"
            )
            return 1 if remaining else 0
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
