from importlib.metadata import version

import whitemarket


def test_version_is_the_installed_distribution_version() -> None:
    assert whitemarket.__version__ == version("whitemarket-sdk")
