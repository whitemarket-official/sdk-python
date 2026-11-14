"""Mutation score gate over mutmut's results, and the changed-files selection for pull requests.

    mutation_gate.py gate [--meta-dir mutants] [--min-score 80] [--min-covered 90]
    mutation_gate.py names --base origin/main   # mutant-name globs of changed hand-written files

`gate` reads the `*.meta` files mutmut 3.8.1 writes under `mutants/` (`exit_code_by_key`, the data
`mutmut export-cicd-stats` aggregates). That export is not used: its `total` counts mutants
that have not run, which a changed-files run leaves behind. Exit codes map to statuses as in
`mutmut/stats.py`
(`status_by_exit_code`); an unknown code counts as suspicious, like mutmut does.

    score   = (killed + timeout) / (total - no_tests)   total counts the mutants that ran
    covered = the same ratio; the gate fails below --min-score, --min-covered (90) only warns.

Mirrors the PHP SDK (infection.json5: minMsi 80, minCoveredMsi 90). Stdlib only.
"""

import argparse
import fnmatch
import json
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

KILLED = "killed"
TIMEOUT = "timeout"
SURVIVED = "survived"
NO_TESTS = "no_tests"
SUSPICIOUS = "suspicious"
# Not part of the score: not run yet (None), interrupted, or skipped by mutmut's no-mutate pragma.
NOT_COUNTED = frozenset({"not_checked", "interrupted", "skipped"})

# mutmut/stats.py status_by_exit_code (mutmut 3.8.1); 37 = caught by the type checker, a kill.
_STATUS_BY_EXIT_CODE: dict[int | None, str] = {
    1: KILLED,
    3: KILLED,
    37: KILLED,
    0: SURVIVED,
    5: NO_TESTS,
    33: NO_TESTS,
    2: "interrupted",
    None: "not_checked",
    34: "skipped",
    35: SUSPICIOUS,
    36: TIMEOUT,
    -24: TIMEOUT,
    24: TIMEOUT,
    152: TIMEOUT,
    255: TIMEOUT,
    -11: "segfault",
    -9: "segfault",
}


def say(text: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(text + "\n")


def status_of(exit_code: int | None) -> str:
    return _STATUS_BY_EXIT_CODE.get(exit_code, SUSPICIOUS)


def count_statuses(exit_codes: Iterable[int | None]) -> Counter[str]:
    return Counter(status_of(code) for code in exit_codes)


def load_exit_codes(meta_dir: Path) -> list[int | None]:
    codes: list[int | None] = []
    for meta in sorted(meta_dir.rglob("*.meta")):
        codes.extend(json.loads(meta.read_text())["exit_code_by_key"].values())
    return codes


def score(counts: Mapping[str, int]) -> tuple[float, int]:
    """(percent, mutants in the denominator); 100 when nothing was left to judge."""
    total = sum(n for status, n in counts.items() if status not in NOT_COUNTED)
    judged = total - counts.get(NO_TESTS, 0)
    if judged <= 0:
        return 100.0, 0
    return 100.0 * (counts.get(KILLED, 0) + counts.get(TIMEOUT, 0)) / judged, judged


def gate(counts: Mapping[str, int], min_score: float, min_covered: float) -> int:
    percent, judged = score(counts)
    line = ", ".join(f"{status} {n}" for status, n in sorted(counts.items()))
    say(f"mutation: {line}")
    say(f"mutation score: {percent:.2f} % of {judged} mutants (gate {min_score:g} %)")
    say(f"mutation covered score: {percent:.2f} % (target {min_covered:g} %, informational)")
    if judged == 0:
        say("mutation: no mutant was judged (no mutated file in this run); nothing to gate")
    if percent < min_covered:
        say(f"::warning::mutation covered score {percent:.2f} % is below {min_covered:g} %")
    if percent < min_score:
        say(f"mutation: FAIL, score {percent:.2f} % is below {min_score:g} %", err=True)
        return 1
    say("mutation: PASS")
    return 0


def mutant_globs(paths: Iterable[str], excluded: Iterable[str]) -> list[str]:
    """mutmut mutant-name globs (`whitemarket.live._ws.*`) of hand-written `src/` Python files."""
    globs: list[str] = []
    for path in sorted(set(paths)):
        if not (path.startswith("src/") and path.endswith(".py")):
            continue
        if any(fnmatch.fnmatch(path, pattern) for pattern in excluded):
            continue
        globs.append(path.removeprefix("src/").removesuffix(".py").replace("/", ".") + ".*")
    return globs


def changed_paths(base: str) -> list[str]:
    """Files added or modified on this branch since it left `base` (merge-base diff)."""
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git is required for the changed-files mode")
    # S603: a fixed argv; the base ref comes from the Makefile or CI, see #0
    out = subprocess.run(  # noqa: S603
        [git, "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--", "src"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return out.splitlines()


def excluded_patterns() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return list(config["tool"]["mutmut"]["do_not_mutate"])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gate_parser = sub.add_parser("gate")
    gate_parser.add_argument("--meta-dir", type=Path, default=Path("mutants"))
    gate_parser.add_argument("--min-score", type=float, default=80.0)
    gate_parser.add_argument("--min-covered", type=float, default=90.0)
    names_parser = sub.add_parser("names")
    names_parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    if args.command == "names":
        say("\n".join(mutant_globs(changed_paths(args.base), excluded_patterns())))
        return 0
    counts = count_statuses(load_exit_codes(args.meta_dir))
    return gate(counts, args.min_score, args.min_covered)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
