"""Build a sandboxed Apple silicon app and optionally notarize it for distribution."""

from __future__ import annotations

import argparse
import json
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
logger = logging.getLogger(__name__)


def render_icon(destination: Path) -> None:
    renderer = QSvgRenderer(str(PROJECT / 'flatpak' / f'{COMPONENT}.svg'))
    pixels = QImage(512, 512, QImage.Format.Format_RGBA8888)
    pixels.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixels)
    renderer.render(painter)
    painter.end()
    if not renderer.isValid() or not pixels.save(str(destination)):
        msg = 'Could not render the macOS application icon.'
        raise RuntimeError(msg)


def compile_bundle(staging: Path, native: Path, identity: str) -> Path:
    source = staging / 'entropy'
    shutil.copytree(
        PROJECT / 'src' / 'entropy', source, ignore=shutil.ignore_patterns('__pycache__')
    )
    (staging / 'Entropy.py').write_text(ENTRY_POINT, encoding='utf-8')
    icon = staging / 'Entropy.png'
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
            '--macos-app-name=Entropy',
            f'--macos-app-icon={icon}',
            f'--macos-app-version={version}',
            f'--macos-sign-identity={identity}',
            *(['--macos-sign-notarization'] if identity != '-' else []),
            f'--output-dir={output}',
            'Entropy.py',
        ],
        cwd=staging,
        env={**os.environ, 'PYTHONPATH': str(native)},
        check=True,
    )
    return output / 'Entropy.app'


def sign_bundle(bundle: Path, identity: str) -> Path:
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
    command = ['/usr/bin/codesign', '--force', '--sign', identity]
    if identity != '-':
        command.extend(('--timestamp', '--options', 'runtime'))
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


def notarize(bundle: Path, archive: Path, profile: str) -> None:
    result = subprocess.run(
        [
            'xcrun',
            'notarytool',
            'submit',
            str(archive),
            '--keychain-profile',
            profile,
            '--wait',
            '--output-format',
            'json',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    submission = json.loads(result.stdout)
    if submission.get('status') != 'Accepted':
        msg = f'Apple did not accept the notarization submission: {submission}'
        raise RuntimeError(msg)
    subprocess.run(['xcrun', 'stapler', 'staple', str(bundle)], check=True)
    subprocess.run(['xcrun', 'stapler', 'validate', str(bundle)], check=True)
    archive.unlink()
    write_archive(bundle, archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sign-identity', default='-', help='Developer ID Application identity')
    parser.add_argument('--notary-profile', help='notarytool keychain profile for a public build')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        parser.error('Use a native arm64 Python on an Apple silicon Mac.')
    identity = str(args.sign_identity)
    profile = str(args.notary_profile) if args.notary_profile else None
    if identity != '-' and (not identity.startswith('Developer ID Application: ') or not profile):
        parser.error(
            'For distribution, provide a Developer ID Application identity and --notary-profile.'
        )
    if identity == '-' and profile:
        parser.error('Notarization requires a Developer ID Application identity.')

    metadata = activate_local_runtime()
    if metadata is None or metadata.get('compiled_backends') != ['Metal']:
        parser.error('Build the Metal runtime first with scripts/build_mnn.py.')
    native = (runtime_root() / str(metadata['directory'])).resolve()
    dist = PROJECT / 'dist'
    dist.mkdir(exist_ok=True)
    filename = 'entropy-macos-arm64.zip' if profile else 'entropy-macos-arm64-testing.zip'
    with TemporaryDirectory(prefix='entropy-macos-', dir=dist) as directory:
        staging = Path(directory)
        bundle = compile_bundle(staging, native, identity)
        check_bundle(sign_bundle(bundle, identity))
        archive = staging / filename
        write_archive(bundle, archive)
        if profile:
            notarize(bundle, archive, profile)
        archive.replace(dist / filename)
    logger.info('Created %s', dist / filename)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
