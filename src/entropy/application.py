"""The desktop application: owns the session and the interface and wires them together."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QWindow
from PySide6.QtQuickControls2 import QQuickStyle

from entropy.core.events import Error, ModelReady, WorkerEvent
from entropy.core.macos_sandbox import check_sandbox_write_denied
from entropy.logic.session import Session
from entropy.logic.settings import Settings
from entropy.logic.worker_host import WorkerHost
from entropy.paths import is_compiled, uses_macos_sandbox
from entropy.ui.dialogs import configure_file_portal
from entropy.ui.view import Ui
from entropy.version import application_version

# Some desktops default to fonts too small for the dense queue layout
MIN_FONT_SIZE = 12
logger = logging.getLogger(__name__)


class Entropy:
    """Hold every long-lived part of the desktop process.

    Parts receive this object so they can reach each other. The session never
    touches ``ui``: it reports changes through signals the interface connects to.
    Constructors may only use parts built before them.
    """

    def __init__(self, *, settings: QSettings | None = None, start_setup: bool = True) -> None:
        # Order matters, each part may use the ones above it
        self.settings = Settings(settings)
        self.worker = WorkerHost()
        self.session = Session(self)
        self.ui = Ui(self)

        # Start setup once the event loop runs, so the window appears first
        if start_setup:
            QTimer.singleShot(0, self.session.prepare)

    def shutdown(self) -> None:
        """Reap the worker and persist preferences; safe to call more than once."""
        self.worker.shutdown()
        self.session.save_settings()
        self.ui.save_settings()


def _check_packaged_worker(qt: QGuiApplication, worker: WorkerHost) -> int:
    """Start the signed helper and load its bundled runtime without probing a GPU."""
    check_sandbox_write_denied()
    ready = False

    def receive(event: WorkerEvent) -> None:
        nonlocal ready
        if isinstance(event, ModelReady):
            ready = True
        elif isinstance(event, Error):
            logger.error('%s', event.message)

    def finish(code: int, cancelled: bool) -> None:
        qt.exit(0 if ready and not cancelled and code == 0 else 1)

    worker.received.connect(receive)
    worker.diagnostic.connect(logger.error)
    worker.finished.connect(finish)
    QTimer.singleShot(0, lambda: worker.start('check-bundle'))
    QTimer.singleShot(30_000, lambda: qt.exit(1))
    result = qt.exec()
    worker.shutdown()
    return result


def run() -> int:
    """Launch Material Qt Quick with native portal file dialogs on Linux."""
    sandboxed = uses_macos_sandbox()
    if sandboxed:
        os.environ['QV4_FORCE_INTERPRETER'] = '1'

    # Both must be configured before the QGuiApplication exists
    configure_file_portal()
    QQuickStyle.setStyle('Material')

    qt = QGuiApplication(sys.argv)
    qt.setOrganizationName('Entropy')
    qt.setApplicationName('Entropy')
    qt.setApplicationDisplayName('Entropy')
    qt.setApplicationVersion(application_version())

    # Windows ships its icon next to the executable
    if is_compiled() and not sandboxed:
        qt.setWindowIcon(QIcon(str(Path(sys.executable).with_name('Entropy.ico'))))

    font = qt.font()
    font.setPointSizeF(max(MIN_FONT_SIZE, font.pointSizeF()))
    qt.setFont(font)

    # Packaging checks that QML loads without starting model setup
    startup_check = os.environ.get('ENTROPY_STARTUP_CHECK') == '1'
    app = Entropy(start_setup=not startup_check)
    engine = app.ui.load()

    # No root object means the QML failed to load, the errors are already logged
    if not engine.rootObjects():
        app.shutdown()
        return 1

    if startup_check:
        qt.setQuitOnLastWindowClosed(False)
        for window in engine.rootObjects():
            if isinstance(window, QWindow):
                window.close()
        return _check_packaged_worker(qt, app.worker) if sandboxed else 0

    qt.aboutToQuit.connect(app.shutdown)
    return qt.exec()
