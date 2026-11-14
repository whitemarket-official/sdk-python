"""tools/ci/mutation_gate.py: the score formula, the exit code and the changed-files globs."""

import json
from pathlib import Path

import pytest
from ci import mutation_gate as gate_module
from ci.mutation_gate import count_statuses, gate, mutant_globs, score, status_of

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
