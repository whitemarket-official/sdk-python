"""tools/ci/mutation_gate.py: the score formula, the exit code and the changed-files globs."""

import json
from pathlib import Path

import pytest
from ci import mutation_gate as gate_module
from ci.mutation_gate import (
    count_statuses,
    gate,
    mutant_globs,
    score,
    split_into_parts,
    status_of,
)

KILLED, SURVIVED, NO_TESTS, TIMEOUT = 1, 0, 33, 36


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (1, "killed"),
        (3, "killed"),
        (0, "survived"),
        (5, "no_tests"),
        (33, "no_tests"),
        (36, "timeout"),
        (152, "timeout"),
        (None, "not_checked"),
        (34, "skipped"),
        (35, "suspicious"),
        (-11, "segfault"),
        (4242, "suspicious"),
    ],
    ids=str,
)
def test_status_of_follows_mutmuts_exit_code_table(code: int | None, status: str) -> None:
    assert status_of(code) == status


def test_score_counts_killed_and_timeout_over_the_mutants_that_have_tests() -> None:
    counts = count_statuses([KILLED] * 6 + [TIMEOUT] * 2 + [SURVIVED] * 2 + [NO_TESTS] * 3)
    assert score(counts) == (80.0, 10)


def test_score_ignores_mutants_that_did_not_run() -> None:
    counts = count_statuses([KILLED, SURVIVED, None, None, None, 34, 2])
    assert score(counts) == (50.0, 2)


def test_score_of_an_empty_run_is_100_with_nothing_judged() -> None:
    assert score(count_statuses([None, NO_TESTS])) == (100.0, 0)


@pytest.mark.parametrize(
    ("survivors", "expected"),
    [(20, 0), (21, 1)],
    ids=["exactly 80 %", "just below 80 %"],
)
def test_gate_fails_below_the_minimum_score_only(survivors: int, expected: int) -> None:
    counts = count_statuses([KILLED] * 80 + [SURVIVED] * survivors)
    assert gate(counts, 80.0, 90.0) == expected


def test_a_covered_score_below_the_target_warns_but_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    counts = count_statuses([KILLED] * 85 + [SURVIVED] * 15)
    assert gate(counts, 80.0, 90.0) == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "85.00 %" in out


def test_the_gate_reads_every_meta_file(tmp_path: Path) -> None:
    files = {"a.py.meta": [KILLED, SURVIVED], "b/c.py.meta": [KILLED, KILLED]}
    for name, codes in files.items():
        meta = tmp_path / "src" / name
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps({"exit_code_by_key": {f"k{i}": c for i, c in enumerate(codes)}}))
    assert gate_module.main(["gate", "--meta-dir", str(tmp_path), "--min-score", "75"]) == 0
    assert gate_module.main(["gate", "--meta-dir", str(tmp_path), "--min-score", "76"]) == 1


def test_globs_name_the_changed_hand_written_modules_only() -> None:
    changed = [
        "src/whitemarket/retry.py",
        "src/whitemarket/live/_ws.py",
        "src/whitemarket/live/__init__.py",
        "src/whitemarket/_generated/client.py",
        "src/whitemarket/_sync/client.py",
        "src/whitemarket/py.typed",
        "tests/unit/test_x.py",
        "tools/ci/mutation_gate.py",
    ]
    excluded = ["src/whitemarket/_generated/*", "src/whitemarket/_sync/*"]
    assert mutant_globs(changed, excluded) == [
        "whitemarket.live.__init__.*",
        "whitemarket.live._ws.*",
        "whitemarket.retry.*",
    ]


SIZES = {"a.py": 5, "b.py": 4, "c.py": 3, "d.py": 3, "e.py": 1}


def test_parts_take_the_largest_file_first_into_the_lightest_part() -> None:
    # a(5)->1, b(4)->2, c(3)->2 (4 < 5), d(3)->1 (5 < 7), e(1)->2 (7 < 8)
    assert split_into_parts(SIZES, SIZES, 2) == [["a.py", "d.py"], ["b.py", "c.py", "e.py"]]


@pytest.mark.parametrize("n_parts", [1, 2, 3, 5, 6], ids=lambda n: f"{n} parts")
def test_every_file_lands_in_exactly_one_part_whatever_the_input_order(n_parts: int) -> None:
    parts = split_into_parts(SIZES, SIZES, n_parts)

    flat = [path for part in parts for path in part]
    assert sorted(flat) == sorted(SIZES)
    assert len(flat) == len(set(flat))
    assert parts == split_into_parts(list(reversed(SIZES)), SIZES, n_parts)


def test_more_parts_than_files_leaves_the_extra_parts_empty() -> None:
    assert split_into_parts(SIZES, SIZES, 7)[5:] == [[], []]


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--part", "1"], id="part without parts"),
        pytest.param(["--parts", "4"], id="parts without part"),
        pytest.param(["--part", "5", "--parts", "4"], id="part over parts"),
        pytest.param(["--part", "0", "--parts", "4"], id="part zero"),
        pytest.param(["--part", "1", "--parts", "0"], id="zero parts"),
        pytest.param(["--part", "-1", "--parts", "4"], id="sign"),
        pytest.param(["--part", "x", "--parts", "4"], id="not a number"),
        pytest.param(["--part", chr(0x0661), "--parts", "4"], id="non-ascii digit"),
        pytest.param(["--base", "origin/main", "--part", "1", "--parts", "4"], id="base and part"),
        pytest.param([], id="nothing"),
    ],
)
def test_names_takes_a_base_or_a_part_of_parts_and_refuses_anything_else(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        gate_module.main(["names", *argv])

    assert caught.value.code == 2


def run_names(capsys: pytest.CaptureFixture[str], part: int, n_parts: int) -> list[str]:
    assert gate_module.main(["names", "--part", str(part), "--parts", str(n_parts)]) == 0
    return capsys.readouterr().out.split()


@pytest.mark.parametrize("n_parts", [1, 6, 20], ids=lambda n: f"{n} parts")
def test_the_parts_of_this_repository_cover_every_hand_written_module_once(
    capsys: pytest.CaptureFixture[str], n_parts: int
) -> None:
    parts = [run_names(capsys, part, n_parts) for part in range(1, n_parts + 1)]

    flat = [glob for part in parts for glob in part]
    every = mutant_globs(gate_module.src_python_paths(), gate_module.excluded_patterns())
    assert sorted(flat) == every
    assert len(flat) == len(set(flat))
    assert all(parts), "no part is empty"


def test_a_part_with_no_file_is_an_error_not_an_empty_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    n_files = len(run_names(capsys, 1, 1))

    with pytest.raises(SystemExit, match="holds no file"):
        gate_module.main(["names", "--part", str(n_files + 1), "--parts", str(n_files + 1)])


def write_meta(meta_dir: Path, codes: list[int | None]) -> None:
    meta = meta_dir / "src" / "m.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"exit_code_by_key": {f"k{i}": c for i, c in enumerate(codes)}}))


def test_the_gate_of_the_parts_scores_their_summed_counts(tmp_path: Path) -> None:
    # Part 1 alone is 100 %, part 2 alone 50 %: only the sum (3 of 4, 75 %) decides.
    counts_dir = tmp_path / "counts"
    for part, codes in enumerate([[KILLED, KILLED, None], [KILLED, SURVIVED, NO_TESTS]], 1):
        meta_dir = tmp_path / f"mutants{part}"
        write_meta(meta_dir, codes)
        out = counts_dir / f"part-{part}.json"
        assert gate_module.main(["counts", "--meta-dir", str(meta_dir), "--out", str(out)]) == 0

    common = ["gate", "--counts", str(counts_dir), "--parts", "2", "--min-score"]
    assert gate_module.main([*common, "75"]) == 0
    assert gate_module.main([*common, "76"]) == 1


@pytest.mark.parametrize("n_parts", [1, 3], ids=["fewer parts expected", "a part missing"])
def test_the_gate_of_the_parts_fails_when_their_number_is_not_the_expected_one(
    tmp_path: Path, n_parts: int
) -> None:
    for part in range(2):
        (tmp_path / f"part-{part}.json").write_text(json.dumps({"killed": 1}))

    with pytest.raises(SystemExit, match="2 part counts"):
        gate_module.main(["gate", "--counts", str(tmp_path), "--parts", str(n_parts)])


@pytest.mark.parametrize(
    "argv", [["--counts", "x"], ["--parts", "2"]], ids=["counts alone", "parts alone"]
)
def test_gate_over_counts_needs_both_counts_and_parts(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        gate_module.main(["gate", *argv])

    assert caught.value.code == 2
