"""Handle App Sandbox file access for the packaged macOS app and worker."""

from __future__ import annotations

import ctypes as ct
import os
from contextlib import ExitStack, contextmanager
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

BOOKMARK_NO_UI_OR_MOUNT = (1 << 8) | (1 << 9)


@cache
def _framework() -> ct.CDLL:
    core = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    pointer = ct.c_void_p
    index = ct.c_long
    flags = ct.c_ulong
    signatures = (
        (
            core.CFURLCreateFromFileSystemRepresentation,
            pointer,
            (pointer, ct.c_char_p, index, ct.c_bool),
        ),
        (
            core.CFURLCreateBookmarkData,
            pointer,
            (pointer, pointer, flags, pointer, pointer, pointer),
        ),
        (
            core.CFURLCreateByResolvingBookmarkData,
            pointer,
            (pointer, pointer, flags, pointer, pointer, pointer, pointer),
        ),
        (core.CFDataCreate, pointer, (pointer, ct.c_char_p, index)),
        (core.CFDataGetLength, index, (pointer,)),
        (core.CFDataGetBytePtr, pointer, (pointer,)),
        (core.CFURLStopAccessingSecurityScopedResource, None, (pointer,)),
        (core.CFRelease, None, (pointer,)),
    )
    for function, result, arguments in signatures:
        function.restype = result
        function.argtypes = arguments
    return core


def bookmark_for(path: Path, *, directory: bool = False) -> str:
    """Serialize a bookmark with implicit scope from a path accessible to the app."""
    core = _framework()
    encoded = os.fsencode(path)
    url = core.CFURLCreateFromFileSystemRepresentation(None, encoded, len(encoded), directory)
    if not url:
        msg = f'Could not create a file URL for {path}'
        raise OSError(msg)
    try:
        data = core.CFURLCreateBookmarkData(None, url, 0, None, None, None)
        if not data:
            msg = f'Could not share access to {path}. Choose it again in the file picker.'
            raise OSError(msg)
        try:
            return ct.string_at(core.CFDataGetBytePtr(data), core.CFDataGetLength(data)).hex()
        finally:
            core.CFRelease(data)
    finally:
        core.CFRelease(url)


def share_job_paths(images: tuple[Path, ...], output: Path) -> tuple[str, ...]:
    """Capture the input files and the output folder for this job only."""
    output.mkdir(parents=True, exist_ok=True)
    return (*(bookmark_for(path) for path in images), bookmark_for(output, directory=True))


@contextmanager
def resolve_bookmarks(bookmarks: tuple[str, ...]) -> Generator[None]:
    """Extend the worker's sandbox until the batch finishes."""
    with ExitStack() as access:
        for bookmark in bookmarks:
            core = _framework()
            encoded = bytes.fromhex(bookmark)
            data = core.CFDataCreate(None, encoded, len(encoded))
            if not data:
                msg = 'Could not read a file access bookmark.'
                raise OSError(msg)
            try:
                stale = ct.c_bool()
                url = core.CFURLCreateByResolvingBookmarkData(
                    None, data, BOOKMARK_NO_UI_OR_MOUNT, None, None, ct.byref(stale), None
                )
            finally:
                core.CFRelease(data)
            if url:
                access.callback(core.CFRelease, url)
                access.callback(core.CFURLStopAccessingSecurityScopedResource, url)
            if not url or stale.value:
                msg = 'File access expired. Reselect the images and output folder.'
                raise OSError(msg)
        yield


def check_sandbox_write_denied() -> None:
    """Fail the packaging smoke check if a private fixture is writable."""
    if fixture := os.environ.get('ENTROPY_SANDBOX_CHECK_FILE'):
        try:
            with Path(fixture).open('r+b'):
                pass
        except PermissionError:
            return
        msg = 'App Sandbox allowed opening an unselected file for writing.'
        raise RuntimeError(msg)
