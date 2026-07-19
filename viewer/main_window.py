"""The main application window: top bar + sidebar + pages + status bar.

Wires navigation, the always-available (debounced) search, keyboard shortcuts,
and the background pipeline worker. Import and Re-index run the whole
scan → thumbnail → face → cluster pipeline off the UI thread with live progress
in the status bar, so the user never touches the command line and the window
stays responsive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from utils.logging_setup import get_logger
from utils.perf import timer
from viewer import data
from viewer.components import ComingSoonPage, Sidebar, StatusBar, TopBar
from viewer.gpuinfo import detect_gpu
from viewer.pages import DashboardPage, GalleryPage, PeoplePage, PersonDetailPage
from viewer.photo_viewer import PhotoViewer
from viewer.search_page import SearchPage
from viewer.state import AppState
from viewer.tasks import PipelineWorker
from viewer.timeline_page import TimelinePage

logger = get_logger("viewer.main")

# Honest notes for sections whose backend module is not built yet.
_PLANNED_NOTES = {
    "videos": "Videos — planned. Video indexing is a future module.",
    "objects": "Object Detection — planned AI module.",
    "similar": "Similar Photos — planned AI module.",
    "albums": "Albums — planned organization module.",
    "favorites": "Favorites — planned organization module.",
    "archive": "Archive — planned organization module.",
    "trash": "Trash — planned. Deletions will be database-only; originals are never touched.",
    "settings": "Settings — planned configuration module.",
    "about": "PhotoSphere AI — a fully offline, local AI photo manager.",
}


class MainWindow(QtWidgets.QMainWindow):
    """Assembles the whole application shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PhotoSphere AI")
        self.resize(1320, 860)

        self._state = AppState()
        self._current_page = "dashboard"
        self._worker: Optional[PipelineWorker] = None
        self._last_job: tuple[Optional[Path], Optional[list[int]]] = (None, None)

        # --- Top bar ---
        self._topbar = TopBar()
        self._topbar.search_changed.connect(self._on_search)
        self._topbar.import_requested.connect(self._on_import)
        self._topbar.reindex_requested.connect(self._on_reindex)
        self._topbar.stop_requested.connect(self._on_stop)
        self._topbar.continue_requested.connect(self._on_continue)

        # --- Sidebar ---
        self._sidebar = Sidebar()
        self._sidebar.navigate.connect(self.show_page)

        # --- Pages ---
        self._stack = QtWidgets.QStackedWidget()
        self._dashboard = DashboardPage()
        self._gallery = GalleryPage()
        self._people = PeoplePage()
        self._person_detail = PersonDetailPage()
        self._search = SearchPage()
        self._timeline = TimelinePage()

        self._search.photo_activated.connect(
            lambda pid: self._open_viewer(self._search.current_photo_ids(), pid)
        )
        self._timeline.photo_activated.connect(
            lambda pid: self._open_viewer(self._timeline.current_photo_ids(), pid)
        )
        self._gallery.photo_activated.connect(
            lambda pid: self._open_viewer(self._gallery.current_photo_ids(), pid)
        )
        self._gallery.detect_faces_requested.connect(self._on_detect_selected)
        self._gallery.find_similar_requested.connect(self._on_find_similar)
        self._person_detail.photo_activated.connect(
            lambda pid: self._open_viewer(self._person_detail.current_photo_ids(), pid)
        )
        self._person_detail.detect_faces_requested.connect(self._on_detect_selected)
        self._person_detail.find_similar_requested.connect(self._on_find_similar)
        self._person_detail.person_changed.connect(self.refresh_all)
        self._person_detail.open_person_requested.connect(self._open_person)
        self._people.person_selected.connect(self._open_person)
        self._person_detail.back_requested.connect(lambda: self.show_page("people"))

        self._page_keys: dict[str, int] = {}
        for key, widget in (
            ("dashboard", self._dashboard),
            ("photos", self._gallery),
            ("people", self._people),
            ("search", self._search),
            ("timeline", self._timeline),
        ):
            self._page_keys[key] = self._stack.addWidget(widget)
        self._detail_index = self._stack.addWidget(self._person_detail)

        self._coming: dict[str, int] = {}
        for key, note in _PLANNED_NOTES.items():
            self._coming[key] = self._stack.addWidget(ComingSoonPage(key.capitalize(), note))

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
        self._status.set_gpu(detect_gpu().badge())
        self.setAcceptDrops(True)  # drop a folder anywhere to import it
        self._restore_state()
        self.refresh_all()

    # -- session state (resume where you left off) ---------------------------
    def _restore_state(self) -> None:
        """Restore window geometry, gallery zoom, and the last page on launch."""
        geometry = self._state.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)

        self._gallery.set_tile_size(self._state.tile(self._gallery.tile_size()))

        # Only restore to a page that still exists; fall back to dashboard.
        last = self._state.page("dashboard")
        if last not in self._page_keys and last not in self._coming:
            last = "dashboard"
        self.show_page(last)

    def _save_state(self) -> None:
        self._state.save_geometry(self.saveGeometry())
        self._state.save_page(self._current_page)
        self._state.save_tile(self._gallery.tile_size())
        self._state.sync()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 (Qt name)
        self._save_state()
        super().closeEvent(event)

    # -- navigation ----------------------------------------------------------
    def show_page(self, key: str) -> None:
        """Switch the content area to the page for ``key`` and refresh it."""
        self._sidebar.select(key)
        self._current_page = key
        if key in self._page_keys:
            self._stack.setCurrentIndex(self._page_keys[key])
            self._refresh_page(key)
            if key == "search":
                self._search.focus_input()
        elif key in self._coming:
            self._stack.setCurrentIndex(self._coming[key])

    def _refresh_page(self, key: str) -> None:
        # Defensive: a transient DB issue at launch must not crash the window.
        try:
            with timer(f"tab.{key}.refresh"):
                if key == "dashboard":
                    self._dashboard.refresh()
                elif key == "photos":
                    self._gallery.refresh()
                elif key == "people":
                    self._people.refresh()
                elif key == "timeline":
                    self._timeline.refresh()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refresh page '%s': %s", key, exc)

    def refresh_all(self) -> None:
        """Refresh the status bar and the current page."""
        try:
            self._status.update_stats(data.library_stats())
        except Exception as exc:  # noqa: BLE001 - DB may be unavailable at launch
            logger.warning("Could not load library stats: %s", exc)

    def _open_person(self, person_id: int) -> None:
        with timer("tab.person_detail.open"):
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

    # -- search --------------------------------------------------------------
    def _on_search(self, term: str) -> None:
        # Switch to the gallery once; the page debounces the actual reload so we
        # do not re-query on every keystroke.
        self._sidebar.select("photos")
        self._stack.setCurrentIndex(self._page_keys["photos"])
        self._gallery.set_search(term)

    # -- drag & drop ---------------------------------------------------------
    @staticmethod
    def _dropped_dirs(event: QtGui.QDropEvent) -> list[Path]:
        """Local directories among a drop's URLs (files are ignored)."""
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        dirs = []
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    dirs.append(path)
        return dirs

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802 (Qt name)
        if self._dropped_dirs(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802 (Qt name)
        dirs = self._dropped_dirs(event)
        if not dirs:
            event.ignore()
            return
        event.acceptProposedAction()
        # Import the first dropped folder; remember it for the next dialog.
        folder = dirs[0]
        self._state.save_import_dir(str(folder))
        self._start_pipeline(folder)

    # -- pipeline ------------------------------------------------------------
    def _on_import(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Import Folder", self._state.import_dir()
        )
        if directory:
            self._state.save_import_dir(directory)
            self._start_pipeline(Path(directory))

    def _on_reindex(self) -> None:
        # Re-run thumbnails + AI over already-imported photos (no new scan).
        self._start_pipeline(root=None)

    def _on_stop(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def _on_continue(self) -> None:
        # Resume: re-run the same target. Every stage is idempotent, so it
        # picks up exactly where Stop left off.
        root, photo_ids = self._last_job
        self._start_pipeline(root=root, photo_ids=photo_ids)

    def _on_detect_selected(self, photo_ids: list[int]) -> None:
        """Run face detection + people grouping on user-selected photos only."""
        if photo_ids:
            self._start_pipeline(photo_ids=list(photo_ids))

    def _on_find_similar(self, photo_id: int) -> None:
        """Show photos visually similar to the given one on the Search tab."""
        rows = data.similar_photos(photo_id, limit=200)
        self._search.show_rows(
            rows, f"{len(rows)} similar photo(s)" if rows
            else "No similar photos — build the search index (Re-index) first."
        )
        self.show_page("search")

    def _start_pipeline(
        self, root: Optional[Path] = None, photo_ids: Optional[list[int]] = None
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # a pipeline is already running
        self._last_job = (root, photo_ids)
        self._topbar.set_running()
        self._worker = PipelineWorker(root=root, run_ai=True, photo_ids=photo_ids)
        self._worker.step_changed.connect(self._status.set_step)
        self._worker.progress.connect(self._status.set_progress)
        self._worker.finished_ok.connect(self._on_pipeline_done)
        self._worker.cancelled.connect(self._on_pipeline_stopped)
        self._worker.failed.connect(self._on_pipeline_failed)
        self._worker.start()

    def _on_pipeline_done(self, summary: str) -> None:
        logger.info("Pipeline finished: %s", summary)
        self._status.set_step(None)
        self._topbar.set_idle()
        self.refresh_all()
        self.show_page("photos")

    def _on_pipeline_stopped(self, summary: str) -> None:
        logger.info("Pipeline stopped: %s", summary)
        self._status.set_step(None)
        self._topbar.set_stopped()   # offer Continue
        self.refresh_all()

    def _on_pipeline_failed(self, message: str) -> None:
        self._status.set_step(None)
        self._topbar.set_idle()
        self.refresh_all()
        QtWidgets.QMessageBox.warning(self, "Pipeline error", message)

    # -- shortcuts -----------------------------------------------------------
    def _install_shortcuts(self) -> None:
        def add(seq: str, handler) -> None:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            shortcut.activated.connect(handler)

        add("Ctrl+O", self._on_import)
        add("Ctrl+R", self._on_reindex)
        add("Ctrl+F", self._topbar.focus_search)
        add("Ctrl+Q", self.close)
        add("F11", self._toggle_fullscreen)
        add("+", lambda: self._gallery.zoom(24))
        add("=", lambda: self._gallery.zoom(24))
        add("-", lambda: self._gallery.zoom(-24))

    def _toggle_fullscreen(self) -> None:
        self.setWindowState(self.windowState() ^ QtCore.Qt.WindowState.WindowFullScreen)
