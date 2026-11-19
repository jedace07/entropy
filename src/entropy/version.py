"""Application version shared by the interface and release packaging."""

from __future__ import annotations

import argparse
import re
from importlib.metadata import version

# PEP 440 pre-release letters and the words used in release tags
PRERELEASES = {'a': 'alpha', 'b': 'beta', 'rc': 'rc'}


def release_version(package_version: str) -> str:
    """Convert a PEP 440 package version to release tag format.

    ``0.2.1a2`` becomes ``0.2.1-alpha.2``, matching the GitHub release tags.
    """
    return re.sub(
        r'(a|b|rc)(\d+)$',
        lambda match: f'-{PRERELEASES[match[1]]}.{match[2]}',
        package_version,
    )


def application_version() -> str:
    """Return the installed package version in release tag format."""
    return release_version(version('entropy'))


def main() -> int:
    """Print the release tag version for a version from `uv version --short`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    print(release_version(parser.parse_args().version))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
