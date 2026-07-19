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
