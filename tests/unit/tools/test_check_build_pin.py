"""tools/ci/check_build_pin.py: the [build-system] hatchling pin must equal the one in uv.lock."""

import pytest
from ci import check_build_pin


def project(*requires: str) -> dict[str, dict[str, list[str]]]:
    return {"build-system": {"requires": list(requires)}}


def lock(*versions: str) -> dict[str, list[dict[str, str]]]:
    return {
        "package": [{"name": "hatchling", "version": v} for v in versions]
        + [{"name": "x", "version": "1"}]
    }


def test_the_exact_pin_is_read_whatever_the_spacing() -> None:
    assert check_build_pin.pinned_backend(project("hatchling == 1.33.0")) == "1.33.0"


@pytest.mark.parametrize("requirement", ["hatchling>=1.33", "hatchling", "hatchling~=1.33.0"])
def test_a_range_instead_of_an_exact_pin_is_refused(requirement: str) -> None:
    with pytest.raises(SystemExit, match="pin hatchling exactly"):
        check_build_pin.pinned_backend(project(requirement))


def test_the_locked_version_is_read() -> None:
    assert check_build_pin.locked_backend(lock("1.33.0")) == "1.33.0"


@pytest.mark.parametrize("versions", [(), ("1.33.0", "1.32.0")])
def test_zero_or_two_locked_versions_are_refused(versions: tuple[str, ...]) -> None:
    with pytest.raises(SystemExit, match="exactly one hatchling"):
        check_build_pin.locked_backend(lock(*versions))
