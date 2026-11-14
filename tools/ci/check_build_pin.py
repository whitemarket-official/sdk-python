"""Fails when `[build-system] requires` pins another hatchling than uv.lock holds.

`make build` runs with `--no-isolation` in the locked environment, so the backend that builds the
release is the locked hatchling; the pin in pyproject.toml documents it for everyone who builds with
isolation (pip, uv build).
Stdlib only.
"""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pinned_backend(pyproject: dict) -> str:
    """The version of the exact `hatchling==X` requirement of [build-system]."""
    for requirement in pyproject["build-system"]["requires"]:
        match = re.fullmatch(r"hatchling==(\S+)", requirement.replace(" ", ""))
        if match:
            return match.group(1)
    raise SystemExit("[build-system] requires must pin hatchling exactly (hatchling==X)")


def locked_backend(lock: dict) -> str:
    """The hatchling version in uv.lock."""
    versions = {p["version"] for p in lock["package"] if p["name"] == "hatchling"}
    if len(versions) != 1:
        raise SystemExit(
            f"uv.lock must hold exactly one hatchling version, found {sorted(versions)}"
        )
    return versions.pop()


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    pinned, locked = pinned_backend(pyproject), locked_backend(lock)
    if pinned != locked:
        sys.stderr.write(f"hatchling: [build-system] pins {pinned}, uv.lock holds {locked}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
