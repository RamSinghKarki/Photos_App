"""Application bootstrap for the PhotoSphere AI desktop UI.

Creates the QApplication, applies the dark theme, ensures the database schema
exists, and shows the main window.
"""

from __future__ import annotations

import sys

from PySide6 import QtWidgets

from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger, setup_logging
from viewer import theme
from viewer.main_window import MainWindow
from viewer.onboarding import welcome_qss

logger = get_logger("viewer.app")


def create_application(argv: list[str]) -> QtWidgets.QApplication:
    """Create and style the QApplication, or reuse the existing singleton.

    QApplication is a process-wide singleton; reusing an existing instance lets
    multiple entry points (and multiple test modules) call this safely.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(argv)
    app.setApplicationName("PhotoSphere AI")
    app.setStyleSheet(theme.build_stylesheet() + welcome_qss())
    return app


def run(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return its exit code."""
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    get_settings().ensure_directories()

    # Make sure tables exist so a first launch on a fresh database works.
    try:
        db.apply_schema()
    except Exception as exc:  # noqa: BLE001 - show the window anyway; UI degrades gracefully
        logger.error("Could not initialise database: %s", exc)

    app = create_application(argv)
    window = MainWindow()
    window.show()
    window.maybe_onboard()   # first-run welcome (shown once)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
