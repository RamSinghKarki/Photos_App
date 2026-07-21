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


def test_optimize_after_import_retrains_vector_index(clean_db) -> None:
    """The post-import maintenance step must run cleanly and keep ANN search
    correct: the ivfflat indexes are created on empty tables at schema time, so
    the pipeline retrains them (REINDEX) + refreshes stats after a bulk load."""
    import datetime as _dt

    import numpy as np

    from database import db

    rng = np.random.default_rng(5)
    with db.connection() as conn, conn.cursor() as cur:
        pids = []
        for i in range(40):
            meta = db.PhotoMetadata(
                file_path=f"/v/opt{i}.jpg", file_hash=f"opt{i}", file_size=1,
                file_mtime=_dt.datetime(2024, 1, 1),
            )
            pids.append(db.insert_photo(cur, meta))
        vecs = rng.standard_normal((40, 512)).astype("float32")
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        for pid, v in zip(pids, vecs):
            db.upsert_clip_embedding(cur, pid, v.tolist(), "clip", 1)

        db.optimize_after_import(cur)  # must not raise

        cur.execute(
            "SELECT photo_id FROM clip_embeddings ORDER BY embedding <=> %s::vector LIMIT 5",
            (vecs[7].tolist(),),
        )
        top = [r[0] for r in cur.fetchall()]
    assert pids[7] in top  # self-match survives the rebuild


def test_interrupted_import_resumes(qapp, clean_db, photo_tree: Path) -> None:
    """Stopping mid-import must lose no committed work; a re-run completes the
    library to exactly the same state as an uninterrupted import."""
    from database import db
    from viewer.tasks import PipelineWorker

    def make_worker():
        return PipelineWorker(
            root=photo_tree,
            detector_factory=lambda: None,
            clip_factory=lambda: None,
        )

    # First run: request a stop as thumbnailing starts; the stage's first
    # progress tick observes it (cooperative cancel), after the scan committed.
    w1 = make_worker()
    outcomes: list[str] = []
    w1.cancelled.connect(lambda msg: outcomes.append(f"cancelled:{msg}"))
    w1.failed.connect(lambda msg: outcomes.append(f"failed:{msg}"))
    w1.step_changed.connect(lambda step: step == "Building thumbnails" and w1.cancel())
    w1.run()
    assert outcomes and outcomes[0].startswith("cancelled")

    # Second run finishes the job; the library matches a clean full import.
    w2 = make_worker()
    done: list[str] = []
    w2.finished_ok.connect(done.append)
    w2.run()
    assert done, "resumed pipeline did not finish"

    with db.connection() as conn, conn.cursor() as cur:
        # a.jpg, b.png, a_copy.jpg, with_exif.jpg + broken.jpg (identity-only)
        assert db.count_photos(cur) == 5
