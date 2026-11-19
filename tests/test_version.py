"""Check the release tag format derived from the PEP 440 project version."""

import pytest

from entropy.version import release_version


@pytest.mark.parametrize(
    'package_version, tag_version',
    [
        ('0.3.1', '0.3.1'),
        ('0.4.0a1', '0.4.0-alpha.1'),
        ('0.4.0b2', '0.4.0-beta.2'),
        ('1.0.0rc3', '1.0.0-rc.3'),
    ],
)
def test_release_version_matches_tags(package_version: str, tag_version: str) -> None:
    assert release_version(package_version) == tag_version
