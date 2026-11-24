"""Assets and notices shared by the standalone desktop packages."""

from __future__ import annotations

import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path

COMPONENT = 'io.github.jedace07.Entropy'

ENTRY_POINT = '''\
"""Compiled Entropy entry point."""

from entropy.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
'''


def _is_license_file(parts: tuple[str, ...], name: str) -> bool:
    return (
        any(part.lower() in {'license', 'licenses'} for part in parts)
        or name.lower().startswith(('license', 'copying', 'notice'))
        or name == 'METADATA'
    )


def copy_dependency_licenses(destination: Path) -> None:
    """Preserve installed dependencies' license and notice files in the payload."""
    for distribution in distributions():
        for entry in distribution.files or ():
            if '..' in entry.parts or not _is_license_file(entry.parts, entry.name):
                continue
            source = Path(str(distribution.locate_file(entry)))
            if source.is_file():
                target = destination / distribution.metadata['Name'] / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    for license_file in Path(sys.base_prefix).glob('LICENSE*'):
        if license_file.is_file():
            target = destination / 'Python' / license_file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_file, target)
