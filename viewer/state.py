"""Persistent UI state so the app reopens where you left off.

Backed by :class:`QSettings`, which stores per-user settings in the native
location (the registry on Windows, an ini/plist elsewhere) — no database
involved. Remembers the window geometry, the last page, the gallery zoom, and
the last folder you imported from.
"""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore

_ORG = "PhotoSphere"
_APP = "PhotoSphere AI"


class AppState:
    """Thin, typed wrapper over QSettings for the values we persist."""

    def __init__(self, settings: Optional[QtCore.QSettings] = None) -> None:
        self._s = settings or QtCore.QSettings(_ORG, _APP)

    # -- window geometry (size, position, maximized) -------------------------
    def save_geometry(self, data: QtCore.QByteArray) -> None:
        self._s.setValue("window/geometry", data)

    def geometry(self) -> Optional[QtCore.QByteArray]:
        value = self._s.value("window/geometry")
        return value if isinstance(value, QtCore.QByteArray) else None

    # -- last active page ----------------------------------------------------
    def save_page(self, key: str) -> None:
        self._s.setValue("nav/page", key)

    def page(self, default: str = "dashboard") -> str:
        return str(self._s.value("nav/page", default))

    # -- gallery zoom (thumbnail tile size) ----------------------------------
    def save_tile(self, tile: int) -> None:
        self._s.setValue("grid/tile", int(tile))

    def tile(self, default: int) -> int:
        try:
            return int(self._s.value("grid/tile", default))
        except (TypeError, ValueError):
            return default

    # -- last import directory (used as the file dialog's start folder) ------
    def save_import_dir(self, path: str) -> None:
        self._s.setValue("io/import_dir", path)

    def import_dir(self) -> str:
        return str(self._s.value("io/import_dir", "") or "")

    # -- first-run onboarding (shown once) -----------------------------------
    def onboarded(self) -> bool:
        return str(self._s.value("app/onboarded", "false")).lower() in ("1", "true")

    def mark_onboarded(self) -> None:
        self._s.setValue("app/onboarded", True)

    def sync(self) -> None:
        """Flush pending writes to disk (called on close)."""
        self._s.sync()
