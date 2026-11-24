"""Check QML startup and the image worker without a GPU unless requested."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from entropy.core.config import UpscaleRequest
from entropy.core.events import Complete, Saved, decode

logger = logging.getLogger(__name__)


def check_worker(directory: Path, *, gpu: bool) -> None:
    source = directory / 'smoke.png'
    size = (16, 12)
    scale = 2.0 if gpu else 0.5
    Image.new('RGB', size, (128, 128, 128)).save(source)
    request = UpscaleRequest(images=(source,), output_dir=directory / 'output', output_scale=scale)
    result = subprocess.run(
        [sys.executable, '-m', 'entropy', '--worker', '--job'],
        input=request.model_dump_json(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    events = [event for line in result.stdout.splitlines() if (event := decode(line)) is not None]
    saved = [event for event in events if isinstance(event, Saved)]
    if result.returncode or len(saved) != 1 or events[-1] != Complete(succeeded=1, failed=0):
        msg = f'Worker smoke test failed:\n{result.stdout}\n{result.stderr}'
        raise RuntimeError(msg)
    with Image.open(saved[0].output) as output:
        if output.format != 'PNG' or output.size != tuple(round(edge * scale) for edge in size):
            msg = f'Unexpected image format or size: {output.format}, {output.size}'
            raise RuntimeError(msg)
        output.load()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpu', action='store_true', help='also run a real GPU inference tile')
    args = parser.parse_args()
    subprocess.run(
        [sys.executable, '-m', 'entropy'],
        check=True,
        timeout=30,
        env={
            **os.environ,
            'ENTROPY_STARTUP_CHECK': '1',
            'QT_QPA_PLATFORM': 'offscreen',
            'QT_QUICK_BACKEND': 'software',
        },
    )
    with TemporaryDirectory(prefix='entropy-smoke-') as directory:
        check_worker(Path(directory), gpu=False)
        if args.gpu:
            check_worker(Path(directory), gpu=True)
    logger.info('Smoke tests passed%s', ' (including GPU inference)' if args.gpu else '')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
