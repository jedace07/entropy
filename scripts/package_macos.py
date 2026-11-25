"""Build a sandboxed, ad hoc signed Apple silicon app."""

from __future__ import annotations

import argparse
import logging
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from package_assets import COMPONENT, ENTRY_POINT, copy_dependency_licenses
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from entropy.core.models import ensure_default_model
from entropy.paths import MACOS_WORKER, runtime_root
from entropy.version import application_version
from entropy.worker.runtime import activate_local_runtime

PROJECT = Path(__file__).resolve().parents[1]
ICON_SIZES = (16, 32, 128, 256, 512)
logger = logging.getLogger(__name__)


def render_icon(destination: Path) -> None:
    renderer = QSvgRenderer(str(PROJECT / 'flatpak' / f'{COMPONENT}.svg'))
    if not renderer.isValid():
        msg = 'Could not render the macOS application icon.'
        raise RuntimeError(msg)

    # Nuitka only takes an icns icon as is, so build one from every standard size
    iconset = destination.with_suffix('.iconset')
    iconset.mkdir()
    for size in ICON_SIZES:
        for scale, suffix in ((1, ''), (2, '@2x')):
            pixels = QImage(size * scale, size * scale, QImage.Format.Format_RGBA8888)
            pixels.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixels)
            renderer.render(painter)
            painter.end()
            if not pixels.save(str(iconset / f'icon_{size}x{size}{suffix}.png')):
                msg = 'Could not render the macOS application icon.'
                raise RuntimeError(msg)
    subprocess.run(
        ['/usr/bin/iconutil', '--convert', 'icns', '--output', str(destination), str(iconset)],
        check=True,
    )


def compile_bundle(staging: Path, native: Path) -> Path:
    source = staging / 'entropy'
    shutil.copytree(
        PROJECT / 'src' / 'entropy', source, ignore=shutil.ignore_patterns('__pycache__')
    )
    (staging / 'Entropy.py').write_text(ENTRY_POINT, encoding='utf-8')
    icon = staging / 'Entropy.icns'
    render_icon(icon)
    ensure_default_model(directory=staging / 'models')
    notices = staging / 'notices'
    copy_dependency_licenses(notices)
    for library in ('MNN', 'Qt'):
        source_license = PROJECT / 'packaging' / 'windows' / 'licenses' / library
        shutil.copytree(source_license, notices / library, dirs_exist_ok=True)
    shutil.copy2(PROJECT / 'LICENSE', notices / 'Entropy.txt')

    output = staging / 'frozen'
    version = application_version().split('-', 1)[0]
    subprocess.run(
        [
            sys.executable,
            '-m',
            'nuitka',
            '--mode=app',
            '--assume-yes-for-downloads',
            '--enable-plugin=pyside6',
            '--include-qt-plugins=sensible,qml',
            '--noinclude-dlls=*/qml/QtQuickEffectMaker/*',
            '--include-package=MNN',
            '--include-module=_mnncengine',
            '--include-distribution-metadata=entropy',
            '--include-data-dir=entropy/ui/qml=entropy/ui/qml',
            '--include-data-dir=models=models',
            '--include-data-dir=notices=notices',
            # The default executable name, Entropy, clashes with the entropy package folder
            # beside it on case-insensitive file systems
            '--output-filename=EntropyApp',
            '--macos-app-name=Entropy',
            f'--macos-app-icon={icon}',
            f'--macos-app-version={version}',
            '--macos-sign-identity=-',
            f'--output-dir={output}',
            'Entropy.py',
        ],
        cwd=staging,
        env={**os.environ, 'PYTHONPATH': str(native)},
        check=True,
    )
    return output / 'Entropy.app'


def sign_bundle(bundle: Path) -> Path:
    contents = bundle / 'Contents'
    info_path = contents / 'Info.plist'
    with info_path.open('rb') as stream:
        info = plistlib.load(stream)
    executable = contents / 'MacOS' / str(info['CFBundleExecutable'])
    info['CFBundleIdentifier'] = COMPONENT
    info['CFBundleVersion'] = info['CFBundleShortVersionString']
    with info_path.open('wb') as stream:
        plistlib.dump(info, stream)

    worker = executable.with_name(MACOS_WORKER)
    shutil.copy2(executable, worker)
    entitlements = PROJECT / 'packaging' / 'macos'
    command = ['/usr/bin/codesign', '--force', '--sign', '-']
    subprocess.run(
        [
            *command,
            '--identifier',
            f'{COMPONENT}.worker',
            '--entitlements',
            str(entitlements / 'worker.entitlements'),
            str(worker),
        ],
        check=True,
    )
    subprocess.run(
        [*command, '--entitlements', str(entitlements / 'app.entitlements'), str(bundle)],
        check=True,
    )
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    return executable


def write_archive(bundle: Path, archive: Path) -> None:
    subprocess.run(
        ['/usr/bin/ditto', '-c', '-k', '--keepParent', str(bundle), str(archive)], check=True
    )


def check_bundle(executable: Path) -> None:
    with TemporaryDirectory(prefix='entropy-sandbox-', dir=Path.home()) as directory:
        fixture = Path(directory) / 'private.txt'
        fixture.touch()
        subprocess.run(
            [str(executable)],
            check=True,
            timeout=60,
            env={
                **os.environ,
                'ENTROPY_STARTUP_CHECK': '1',
                'QT_QPA_PLATFORM': 'offscreen',
                'QT_QUICK_BACKEND': 'software',
                'ENTROPY_SANDBOX_CHECK_FILE': str(fixture),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('Use a native arm64 Python on an Apple silicon Mac.')

    metadata = activate_local_runtime()
    if metadata is None or metadata.get('compiled_backends') != ['Metal']:
        parser.error('Build the Metal runtime first with scripts/build_mnn.py.')
    native = (runtime_root() / str(metadata['directory'])).resolve()
    dist = PROJECT / 'dist'
    dist.mkdir(exist_ok=True)
    filename = 'entropy-macos-arm64.zip'
    with TemporaryDirectory(prefix='entropy-macos-', dir=dist) as directory:
        staging = Path(directory)
        bundle = compile_bundle(staging, native)
        check_bundle(sign_bundle(bundle))
        archive = staging / filename
        write_archive(bundle, archive)
        archive.replace(dist / filename)
    logger.info('Created %s', dist / filename)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
