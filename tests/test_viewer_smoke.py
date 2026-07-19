"""Headless smoke tests for the Qt Viewer.

These build the real widgets under Qt's offscreen platform (no display needed)
and drive basic navigation, verifying the UI constructs and binds to live data
without raising. They skip cleanly if PySide6 is not installed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Qt must run headless in CI/containers; set before any QApplication is made.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

pytest.importorskip("PySide6")

from scanner.scanner import scan_directory  # noqa: E402
from thumbnails.generator import generate_thumbnails  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from viewer.app import create_application

    app = create_application([])
    yield app


def test_main_window_builds_and_navigates(qapp, clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    generate_thumbnails()

    from viewer.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("photos")
        assert window._gallery._model.rowCount() == 5  # all photos in the grid

        # Navigating to other pages (including search and a planned one) must not raise.
        window.show_page("people")
        window.show_page("search")
        window.show_page("dashboard")
        window.show_page("timeline")
    finally:
        window.close()


def test_drop_filters_folders_from_files(qapp, photo_tree: Path) -> None:
    """A folder drop is accepted (dirs only); loose files/URLs are ignored."""
    from PySide6 import QtCore
    from viewer.main_window import MainWindow

    class _Evt:
        def __init__(self, mime):
            self._mime = mime

        def mimeData(self):
            return self._mime

    a_file = photo_tree / "with_exif.jpg"

    mixed = QtCore.QMimeData()
    mixed.setUrls([
        QtCore.QUrl.fromLocalFile(str(photo_tree)),  # a directory -> kept
        QtCore.QUrl.fromLocalFile(str(a_file)),       # a file -> dropped
    ])
    dirs = MainWindow._dropped_dirs(_Evt(mixed))
    assert dirs == [photo_tree]

    files_only = QtCore.QMimeData()
    files_only.setUrls([QtCore.QUrl.fromLocalFile(str(a_file))])
    assert MainWindow._dropped_dirs(_Evt(files_only)) == []

    no_urls = QtCore.QMimeData()
    assert MainWindow._dropped_dirs(_Evt(no_urls)) == []


def test_appearance_strip_builds_and_signals(qapp) -> None:
    """The appearance strip renders one thumb per representative and relays removal."""
    from viewer.appearance_strip import AppearanceStrip, _RepThumb

    strip = AppearanceStrip()
    got: list[int] = []
    strip.representative_rejected.connect(got.append)

    reps = [
        {"face_id": 10, "crop_path": None, "quality": 0.95, "photo_id": 1, "taken_at": None},
        {"face_id": 11, "crop_path": None, "quality": 0.70, "photo_id": 2, "taken_at": None},
    ]
    strip.set_representatives(reps)
    thumbs = strip.findChildren(_RepThumb)
    assert len(thumbs) == 2

    # A thumb's removal request propagates out of the strip with its face id.
    thumbs[0].rejected.emit(thumbs[0]._face_id)
    assert got == [10]

    # Empty set clears the thumbs from the layout (only the trailing stretch left).
    strip.set_representatives([])
    assert strip._row_layout.count() == 1


def test_photo_viewer_navigation(qapp, clean_db, photo_tree: Path) -> None:
    scan_directory(photo_tree)
    generate_thumbnails()

    from viewer import data
    from viewer.photo_viewer import PhotoViewer

    ids = [row[0] for row in data.photo_grid(limit=100)]
    viewer = PhotoViewer(ids, start_index=0)
    try:
        assert len(ids) == 5
        viewer.show_next()
        assert viewer._index == 1
        viewer.show_prev()
        viewer.show_prev()  # clamped at the first item
        assert viewer._index == 0
    finally:
        viewer.close()
