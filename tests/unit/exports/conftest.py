"""Fixtures of the export tests."""

from collections.abc import Iterator
from typing import Any

import pytest

from support.export_rig import Rig
from support.flavors import Flavor


@pytest.fixture
def rigs() -> Iterator[Any]:
    """`rigs(flavor, *outcomes, **options)` makes an export rig that is closed after the test."""
    made: list[Rig] = []

    def make(flavor: Flavor, *outcomes: Any, **kwargs: Any) -> Rig:
        rig = Rig(flavor, *outcomes, **kwargs)
        made.append(rig)
        return rig

    yield make
    for rig in made:
        rig.close()
