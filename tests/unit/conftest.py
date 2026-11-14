"""Run every test that takes a `flavor` through the async stack and its generated sync twin."""

import pytest

from support.flavors import FLAVORS


def _parametrized_explicitly(metafunc: pytest.Metafunc) -> bool:
    for mark in metafunc.definition.iter_markers("parametrize"):
        names = mark.args[0] if mark.args else mark.kwargs.get("argnames", "")
        listed = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
        if "flavor" in listed:
            return True
    return False


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames and not _parametrized_explicitly(metafunc):
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)
