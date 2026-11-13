"""Run every market test through the async client and its generated sync twin."""

import pytest

from support.flavors import FLAVORS


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "flavor" in metafunc.fixturenames:
        metafunc.parametrize("flavor", FLAVORS, ids=lambda f: f.name)
