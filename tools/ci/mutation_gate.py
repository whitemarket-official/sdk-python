"""Mutation score gate over mutmut's results, and the changed-files selection for pull requests.

    mutation_gate.py gate [--meta-dir mutants] [--min-score 80] [--min-covered 90]
    mutation_gate.py gate --counts DIR --parts 6   # the sum of the part counts, all parts present
    mutation_gate.py names --base origin/main      # mutant-name globs of changed hand-written files
    mutation_gate.py names --part 2 --parts 6      # globs of the second of six parts of all of them
    mutation_gate.py counts --out FILE             # the statuses of this run as JSON, for the gate

A full run is split into parts (CI: one job each, at the same time; locally: one small part of
many, e.g. `--part 1 --parts 20`, for a quick look): every hand-written
file goes to exactly one part, the parts balanced by the number of mutants mutmut generates per
file (largest file first into the lightest part; line counts left parts from 1291 to 2412 mutants
in the CI run 43838380124), so the union of the parts is the full run and the summed counts give
its score.

Stdlib only, except `names --part`: counting mutants imports mutmut (the dev environment).

`gate` reads the `*.meta` files mutmut 3.8.1 writes under `mutants/` (`exit_code_by_key`, the data
`mutmut export-cicd-stats` aggregates). That export is not used: its `total` counts mutants
that have not run, which a changed-files run leaves behind. Exit codes map to statuses as in
`mutmut/stats.py`
(`status_by_exit_code`); an unknown code counts as suspicious, like mutmut does.

    score   = (killed + timeout) / (total - no_tests)   total counts the mutants that ran
    covered = the same ratio; the gate fails below --min-score, --min-covered (90) only warns.

Mirrors the PHP SDK (infection.json5: minMsi 80, minCoveredMsi 90).
"""

import argparse
import fnmatch
import functools
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
    return [_glob(path) for path in sorted(set(paths)) if is_mutated(path, excluded)]


def is_mutated(path: str, excluded: Iterable[str]) -> bool:
    """A hand-written `src/` Python file: not matched by mutmut's `do_not_mutate`."""
    return (
        path.startswith("src/")
        and path.endswith(".py")
        and not any(fnmatch.fnmatch(path, pattern) for pattern in excluded)
    )


def _glob(path: str) -> str:
    return path.removeprefix("src/").removesuffix(".py").replace("/", ".") + ".*"


def split_into_parts(
    paths: Iterable[str], sizes: Mapping[str, int], n_parts: int
) -> list[list[str]]:
    """`n_parts` parts, each sorted: largest file first into the lightest part (ties: by path,
    lowest part), so every path lands in exactly one part whatever the input order."""
    loads = [0] * n_parts
    parts: list[list[str]] = [[] for _ in range(n_parts)]
    for path in sorted(set(paths), key=lambda p: (-sizes[p], p)):
        lightest = min(range(n_parts), key=lambda i: (loads[i], i))
        loads[lightest] += sizes[path]
        parts[lightest].append(path)
    return [sorted(part) for part in parts]


def src_python_paths() -> list[str]:
    """Every Python file under `src/`, as repository-relative POSIX paths."""
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py"))


def mutants_in(source: str, filename: str = "<source>") -> int:
    """How many mutants mutmut generates for `source`, by mutmut's own generator, so the count
    is exact (coverage-excluded lines aside). The one part of this tool that is not stdlib: it
    needs the dev environment, and `mutate_file_contents` is mutmut 3.8.1's internal API."""
    # PLC0415: the `gate` job runs this file with a bare python3, without mutmut installed, see #0
    from mutmut.mutation.file_mutation import mutate_file_contents  # noqa: PLC0415

    return len(mutate_file_contents(filename, source).mutant_names)


@functools.cache
def _mutants_in_file(path: str) -> int:
    return mutants_in((ROOT / path).read_text(encoding="utf-8"), path)


def mutant_counts(paths: Iterable[str]) -> dict[str, int]:
    return {path: _mutants_in_file(path) for path in paths}


def save_counts(counts: Mapping[str, int], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(sorted(counts.items()))) + "\n")


def sum_part_counts(counts_dir: Path, n_parts: int) -> Counter[str]:
    """The sum of the `*.json` counts in `counts_dir`; exactly `n_parts` files, so a part that
    wrote nothing fails the gate instead of passing it."""
    files = sorted(counts_dir.glob("*.json"))
    if len(files) != n_parts:
        raise SystemExit(f"mutation: {len(files)} part counts in {counts_dir}, expected {n_parts}")
    total: Counter[str] = Counter()
    for file in files:
        total.update({str(k): int(v) for k, v in json.loads(file.read_text()).items()})
    return total


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
    gate_parser.add_argument("--counts", type=Path, help="a directory of `counts` outputs")
    gate_parser.add_argument("--parts", type=_positive, help="how many parts --counts holds")
    names_parser = sub.add_parser("names")
    names_parser.add_argument("--base")
    names_parser.add_argument("--part", type=_positive, help="which part (1 .. --parts)")
    names_parser.add_argument("--parts", type=_positive, help="how many parts in all")
    counts_parser = sub.add_parser("counts")
    counts_parser.add_argument("--meta-dir", type=Path, default=Path("mutants"))
    counts_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "names":
        if args.base is not None and args.part is None and args.parts is None:
            return _names_changed(args.base)
        if args.base is None and args.part is not None and args.parts is not None:
            if args.part > args.parts:
                parser.error(f"--part {args.part} is over --parts {args.parts}")
            return _names_of_part(args.part, args.parts)
        parser.error("names takes --base, or --part with --parts")
    if args.command == "counts":
        save_counts(count_statuses(load_exit_codes(args.meta_dir)), args.out)
        return 0
    if (args.counts is None) != (args.parts is None):
        parser.error("--counts and --parts go together")
    if args.counts is not None:
        counts = sum_part_counts(args.counts, args.parts)
    else:
        counts = count_statuses(load_exit_codes(args.meta_dir))
    return gate(counts, args.min_score, args.min_covered)


def _positive(text: str) -> int:
    if not (text.isascii() and text.isdigit() and int(text) >= 1):
        raise argparse.ArgumentTypeError(f"a whole number from 1, not {text!r}")
    return int(text)


def _names_changed(base: str) -> int:
    say("\n".join(mutant_globs(changed_paths(base), excluded_patterns())))
    return 0


def _names_of_part(part: int, n_parts: int) -> int:
    excluded = excluded_patterns()
    paths = [p for p in src_python_paths() if is_mutated(p, excluded)]
    chosen = split_into_parts(paths, mutant_counts(paths), n_parts)[part - 1]
    if not chosen:
        raise SystemExit(
            f"mutation: part {part} of {n_parts} holds no file (more parts than files)"
        )
    say("\n".join(mutant_globs(chosen, excluded)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
