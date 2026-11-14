"""tools/ci/audit_fix.py: the pins the dependency-audit workflow raises, and the rest."""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from ci import audit_fix

PYPROJECT = """\
[project]
name = "whitemarket-sdk"
dependencies = ["httpx>=0.28", "pydantic>=2.8"]

[project.optional-dependencies]
test = ["pytest==9.2.0", "respx==0.23.1"]
dev = ["whitemarket-sdk[test]", "Twine==7.0.0", "keyring[extra]==25.0.0"]
codegen = ["ariadne-codegen==0.19.0"]
"""


def audit(*vulns: tuple[str, str, list[list[str]]]) -> dict[str, Any]:
    """pip-audit JSON: (name, version, fix_versions per advisory)."""
    return {
        "dependencies": [
            {
                "name": name,
                "version": version,
                "vulns": [
                    {"id": f"PYSEC-{i}", "fix_versions": fixes}
                    for i, fixes in enumerate(advisories)
                ],
            }
            for name, version, advisories in vulns
        ]
    }


def test_requirements_exclude_the_project_itself_and_the_codegen_extra() -> None:
    found = audit_fix.requirements(tomllib.loads(PYPROJECT))

    assert found == [
        "Twine==7.0.0",
        "httpx>=0.28",
        "keyring[extra]==25.0.0",
        "pydantic>=2.8",
        "pytest==9.2.0",
        "respx==0.23.1",
    ]


def test_the_codegen_extra_is_resolved_on_its_own() -> None:
    assert audit_fix.requirements(tomllib.loads(PYPROJECT), codegen=True) == [
        "ariadne-codegen==0.19.0"
    ]


@pytest.mark.parametrize(
    ("current", "fixes", "expected"),
    [
        pytest.param("1.0.0", [["1.0.1"]], "1.0.1", id="one fix"),
        pytest.param("1.0.0", [["0.9.9", "1.2.0", "1.1.0"]], "1.1.0", id="lowest newer fix"),
        pytest.param("1.0.0", [["1.0.1"], ["1.3.0"]], "1.3.0", id="highest of the advisories"),
        pytest.param("1.0.0", [["1.0.1"], ["0.8.0"]], None, id="one advisory has no newer fix"),
        pytest.param("1.0.0", [[]], None, id="no fixed version"),
        pytest.param("1.0.0", [], None, id="no advisories listed"),
        pytest.param("1.0.0", [["1.0.0"]], None, id="fix equals current"),
        pytest.param("1.0.0", [["2.0.0rc1"]], None, id="pre-release fix is not guessed"),
        pytest.param("9.2", [["10.0"]], "10.0", id="numeric, not lexical, order"),
    ],
)
def test_target_version(current: str, fixes: list[list[str]], expected: str | None) -> None:
    assert audit_fix.target_version(current, fixes) == expected


def test_an_exact_pin_is_raised_and_nothing_else_changes() -> None:
    text, changes, remaining = audit_fix.plan_fixes(
        audit(("pytest", "9.2.0", [["9.2.1"]])), PYPROJECT
    )

    assert text == PYPROJECT.replace("pytest==9.2.0", "pytest==9.2.1")
    assert changes == [audit_fix.Change("pytest", ("PYSEC-0",), "9.2.0", "9.2.1")]
    assert remaining == []


def test_the_name_match_ignores_case_and_extras() -> None:
    text, _, _ = audit_fix.plan_fixes(
        audit(("twine", "7.0.0", [["7.0.1"]]), ("keyring", "25.0.0", [["25.1.0"]])), PYPROJECT
    )

    assert '"Twine==7.0.1"' in text
    assert '"keyring[extra]==25.1.0"' in text


@pytest.mark.parametrize(
    ("package", "version", "fixes"),
    [
        pytest.param("httpx", "0.28.1", [["0.28.2"]], id="lower-bound range is a decision"),
        pytest.param("idna", "3.7", [["3.8"]], id="transitive package is not declared"),
        pytest.param("pytest", "9.2.0", [[]], id="no fixed version"),
        pytest.param("pytest", "9.1.0", [["9.1.1"]], id="pin differs from the audited version"),
    ],
)
def test_what_cannot_be_fixed_by_a_pin_goes_to_a_human(
    package: str, version: str, fixes: list[list[str]]
) -> None:
    text, changes, remaining = audit_fix.plan_fixes(audit((package, version, fixes)), PYPROJECT)

    assert (text, changes, remaining) == (PYPROJECT, [], [package])


def test_main_fix_writes_the_pin_and_the_report_and_reports_leftovers(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT)
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(
        json.dumps(audit(("pytest", "9.2.0", [["9.2.1"]]), ("idna", "3.7", [["3.8"]])))
    )
    report = tmp_path / "report.md"

    code = audit_fix.main(["audit_fix.py", "fix", str(audit_file), str(pyproject), str(report)])

    assert code == 1
    assert "pytest==9.2.1" in pyproject.read_text()
    assert "| `pytest` | PYSEC-0 | `9.2.0` | `9.2.1` |" in report.read_text()
    assert "`idna`" in report.read_text()


def test_main_without_vulnerabilities_changes_nothing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT)
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(
        json.dumps({"dependencies": [{"name": "pytest", "version": "9.2.0", "vulns": []}]})
    )

    code = audit_fix.main(
        ["audit_fix.py", "fix", str(audit_file), str(pyproject), str(tmp_path / "r.md")]
    )

    assert code == 0
    assert pyproject.read_text() == PYPROJECT


def test_main_rejects_unknown_usage() -> None:
    assert audit_fix.main(["audit_fix.py", "bogus"]) == 2
