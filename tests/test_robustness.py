"""Robustness / stress tests — the app should degrade gracefully, never crash.

Covers: missing thumbnails, AI model/GPU unavailable, and an unreachable
database at launch. (Corrupt/deleted images are covered in the scanner/faces/
thumbnail/clip suites; interrupted work is covered by the pipeline cancel tests.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6")

from PySide6 import QtCore  # noqa: E402

from scanner.scanner import scan_directory  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from viewer.app import create_application

    yield create_application([])


def test_missing_thumbnail_shows_placeholder(qapp) -> None:
    """A row whose thumbnail file is gone must render a placeholder, not crash.

    The model reports "no decoration yet" (None) and the delegate paints a
    coloured gradient tile in its place — so rendering must succeed with no
    pixmap ever produced for the row.
    """
    from viewer.gallery import PhotoGrid, PhotoGridModel

    model = PhotoGridModel()
    rows = [(1, "/lib/a.jpg", "/does/not/exist/thumb.jpg", None)]
    model.set_fetcher(lambda offset, limit: rows[offset:offset + limit])

    assert model.data(model.index(0), QtCore.Qt.ItemDataRole.DecorationRole) is None
    grid = PhotoGrid(model)
    grid.resize(400, 300)
    assert not grid.grab().isNull()   # delegate painted the gradient placeholder


def test_pipeline_without_ai_models_still_completes(qapp, clean_db, photo_tree: Path) -> None:
    """No face/CLIP model installed -> scan + thumbnails still succeed."""
    from viewer.tasks import PipelineWorker

    results: list[str] = []
    worker = PipelineWorker(
        root=photo_tree,
        detector_factory=lambda: None,   # simulate no InsightFace / GPU
        clip_factory=lambda: None,       # simulate no CLIP
    )
    worker.finished_ok.connect(results.append)
    worker.run()

    assert results, "pipeline did not finish"
    assert "faces skipped" in results[0]


def test_app_builds_when_database_unreachable(qapp) -> None:
    """Launching against a down/misconfigured database must not crash the window."""
    from config.settings import get_settings
    from viewer.main_window import MainWindow

    saved = os.environ.get("PHOTOSPHERE_DB_NAME")
    os.environ["PHOTOSPHERE_DB_NAME"] = "photosphere_does_not_exist_db"
    get_settings.cache_clear()
    try:
        window = MainWindow()          # refreshes are defensive; must not raise
        window.show_page("photos")     # queries fail -> caught, no crash
        window.show_page("people")
        window.close()
    finally:
        if saved is None:
            os.environ.pop("PHOTOSPHERE_DB_NAME", None)
        else:
            os.environ["PHOTOSPHERE_DB_NAME"] = saved
        get_settings.cache_clear()
