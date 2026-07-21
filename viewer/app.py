"""Application bootstrap for the PhotoSphere AI desktop UI.

Creates the QApplication, applies the dark theme, ensures the database schema
exists, and shows the main window.
"""

from __future__ import annotations

import sys

from PySide6 import QtCore, QtGui, QtWidgets

from config.settings import get_settings
from database import db
from utils.logging_setup import get_logger, setup_logging
from viewer import theme
from viewer.main_window import MainWindow
from viewer.onboarding import welcome_qss

logger = get_logger("viewer.app")


def _apply_ui_scale() -> None:
    """Apply the user's interface-size preference before the QApplication.

    ``QT_SCALE_FACTOR`` multiplies the OS display scaling, so a value below 1.0
    makes the whole app denser than the global scale — the fix for a high-DPI
    laptop (e.g. 2880x1800 at 200%) where everything feels oversized. An
    existing environment value always wins so power users keep control.
    """
    import os

    if os.environ.get("QT_SCALE_FACTOR"):
        return
    try:
        from config.user_config import get_config
        scale = float(get_config().get("appearance", "ui_scale"))
    except Exception:  # noqa: BLE001 - a bad preference must never block launch
        return
    if abs(scale - 1.0) > 1e-3:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"


def create_application(argv: list[str]) -> QtWidgets.QApplication:
    """Create and style the QApplication, or reuse the existing singleton.

    QApplication is a process-wide singleton; reusing an existing instance lets
    multiple entry points (and multiple test modules) call this safely.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        _apply_ui_scale()
        # Respect fractional display scaling (125/150/175%) precisely instead of
        # rounding it to whole steps — must be set before the QApplication.
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QtWidgets.QApplication(argv)
    app.setApplicationName("PhotoSphere AI")
    app.setStyleSheet(theme.build_stylesheet() + welcome_qss())
    return app


def run(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return its exit code."""
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    from utils.imaging import configure_pillow
    configure_pillow()  # let the user's large panoramas/scans decode
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
