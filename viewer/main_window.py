"""The main application window: top bar + sidebar + pages + status bar.

Wires navigation, the always-available search box, keyboard shortcuts, and a
background import worker so the UI stays responsive while a folder is scanned
and thumbnailed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from scanner.scanner import scan_directory
from thumbnails.generator import generate_thumbnails
from utils.logging_setup import get_logger
from viewer import data, theme
from viewer.components import ComingSoonPage, Sidebar, StatusBar, TopBar
from viewer.pages import DashboardPage, GalleryPage, PeoplePage, PersonDetailPage
from viewer.photo_viewer import PhotoViewer

logger = get_logger("viewer.main")

# Honest notes for sections whose backend module is not built yet.
_PLANNED_NOTES = {
    "timeline": "Timeline — planned. Will group photos by year and month.",
    "videos": "Videos — planned. Video indexing is a future module.",
    "search": "Semantic Search — planned. Use the top search bar for basic search today.",
    "objects": "Object Detection — planned AI module.",
    "similar": "Similar Photos — planned AI module.",
    "albums": "Albums — planned organization module.",
    "favorites": "Favorites — planned organization module.",
    "archive": "Archive — planned organization module.",
    "trash": "Trash — planned. Deletions will be database-only; originals are never touched.",
    "settings": "Settings — planned configuration module.",
    "about": "PhotoSphere AI — a fully offline, local AI photo manager.",
}


class ScanWorker(QtCore.QThread):
    """Runs a scan + thumbnail pass off the UI thread.

    Both steps open their own database connections internally, so nothing on the
    main thread's connections is shared across threads.
    """

    done = QtCore.Signal(int)  # number of newly processed photos

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            summary = scan_directory(self._root)
            generate_thumbnails()
            self.done.emit(summary.processed)
        except Exception as exc:  # noqa: BLE001 - surface as zero, log details
            logger.error("Import failed for %s: %s", self._root, exc)
            self.done.emit(-1)


class MainWindow(QtWidgets.QMainWindow):
    """Assembles the whole application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PhotoSphere AI")
        self.resize(1280, 820)

        self._worker: Optional[ScanWorker] = None

        # --- Top bar ---
        self._topbar = TopBar()
        self._topbar.search_changed.connect(self._on_search)
        self._topbar.import_requested.connect(self._on_import)

        # --- Sidebar ---
        self._sidebar = Sidebar()
        self._sidebar.navigate.connect(self.show_page)

        # --- Pages ---
        self._stack = QtWidgets.QStackedWidget()
        self._dashboard = DashboardPage()
        self._gallery = GalleryPage()
        self._people = PeoplePage()
        self._person_detail = PersonDetailPage()

        self._gallery.photo_activated.connect(
            lambda pid: self._open_viewer(self._gallery.current_photo_ids(), pid)
        )
        self._person_detail.photo_activated.connect(
            lambda pid: self._open_viewer(self._person_detail.current_photo_ids(), pid)
        )
        self._people.person_selected.connect(self._open_person)
        self._person_detail.back_requested.connect(lambda: self.show_page("people"))

        self._page_keys: dict[str, int] = {}
        for key, widget in (
            ("dashboard", self._dashboard),
            ("photos", self._gallery),
            ("people", self._people),
        ):
            self._page_keys[key] = self._stack.addWidget(widget)
        self._detail_index = self._stack.addWidget(self._person_detail)

        # Planned-feature pages.
        self._coming: dict[str, int] = {}
        for key, note in _PLANNED_NOTES.items():
            title = key.capitalize()
            self._coming[key] = self._stack.addWidget(ComingSoonPage(title, note))

        # --- Layout: sidebar | content ---
        content = QtWidgets.QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._sidebar)
        content.addWidget(self._stack, 1)

        self._status = StatusBar()

        root = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._topbar)
        root_layout.addLayout(content, 1)
        root_layout.addWidget(self._status)
        self.setCentralWidget(root)

        self._install_shortcuts()
        self.show_page("dashboard")
        self.refresh_all()

    # -- navigation ----------------------------------------------------------
    def show_page(self, key: str) -> None:
        """Switch the content area to the page for ``key`` and refresh it."""
        self._sidebar.select(key)
        if key in self._page_keys:
            self._stack.setCurrentIndex(self._page_keys[key])
            self._refresh_page(key)
        elif key in self._coming:
            self._stack.setCurrentIndex(self._coming[key])

    def _refresh_page(self, key: str) -> None:
        if key == "dashboard":
            self._dashboard.refresh()
        elif key == "photos":
            self._gallery.refresh()
        elif key == "people":
            self._people.refresh()

    def refresh_all(self) -> None:
        """Refresh the status bar and the current page."""
        try:
            self._status.update_stats(data.library_stats())
        except Exception as exc:  # noqa: BLE001 - DB may be unavailable at launch
            logger.warning("Could not load library stats: %s", exc)

    def _open_person(self, person_id: int) -> None:
        people = {p["id"]: p for p in data.persons()}
        name = people.get(person_id, {}).get("display_name")
        self._person_detail.show_person(person_id, name)
        self._sidebar.select("people")
        self._stack.setCurrentIndex(self._detail_index)

    def _open_viewer(self, photo_ids: list[int], photo_id: int) -> None:
        if not photo_ids:
            return
        start = photo_ids.index(photo_id) if photo_id in photo_ids else 0
        viewer = PhotoViewer(photo_ids, start, self)
        viewer.exec()

    # -- actions -------------------------------------------------------------
    def _on_search(self, term: str) -> None:
        self._gallery.set_search(term)
        self.show_page("photos")

    def _on_import(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Import Folder")
        if not directory:
            return
        self._status.update_stats(data.library_stats())
        self._topbar.search.setPlaceholderText("Indexing…")
        self._worker = ScanWorker(Path(directory))
        self._worker.done.connect(self._on_import_done)
        self._worker.start()

    def _on_import_done(self, processed: int) -> None:
        self._topbar.search.setPlaceholderText("Search photos…  (Ctrl+F)")
        if processed >= 0:
            logger.info("Import finished: %d new photos", processed)
        self.refresh_all()
        self.show_page("photos")

    # -- shortcuts -----------------------------------------------------------
    def _install_shortcuts(self) -> None:
        def add(seq: str, handler) -> None:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            shortcut.activated.connect(handler)

        add("Ctrl+O", self._on_import)
        add("Ctrl+F", self._topbar.focus_search)
        add("Ctrl+Q", self.close)
        add("F11", self._toggle_fullscreen)
        add("+", lambda: self._gallery.zoom(24))
        add("=", lambda: self._gallery.zoom(24))
        add("-", lambda: self._gallery.zoom(-24))

    def _toggle_fullscreen(self) -> None:
        self.setWindowState(self.windowState() ^ QtCore.Qt.WindowState.WindowFullScreen)
