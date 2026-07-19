"""Test the in-app background pipeline worker end to end (headless).

Drives PipelineWorker.run() synchronously with a stub face detector, so the
whole scan -> thumbnails -> faces -> cluster chain that Import triggers is
exercised without a GPU or a running event loop.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import numpy as np
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
pytest.importorskip("PySide6")

from database import db  # noqa: E402
from faces.detector import DetectedFace  # noqa: E402


class _StubDetector:
    def detect(self, image_rgb: np.ndarray) -> List[DetectedFace]:
        h, w = image_rgb.shape[:2]
        emb = (np.arange(512, dtype="float32") / 512).tolist()
        return [DetectedFace((0, 0, max(1, w // 2), max(1, h // 2)), 0.95, emb)]


@pytest.fixture(scope="module")
def qapp():
    from viewer.app import create_application

    yield create_application([])


def test_pipeline_worker_runs_full_chain(qapp, clean_db, photo_tree: Path) -> None:
    from viewer.tasks import PipelineWorker

    steps: list[str] = []
    results: list[str] = []
    worker = PipelineWorker(
        root=photo_tree, run_ai=True, detector_factory=lambda: _StubDetector()
    )
    worker.step_changed.connect(steps.append)
    worker.finished_ok.connect(results.append)

    worker.run()  # synchronous; same-thread signal connections fire inline

    assert results, "pipeline did not finish"
    # All stages ran, in order.
    assert steps[:4] == ["Scanning", "Building thumbnails", "Detecting faces", "Grouping people"]

    with db.connection() as conn, conn.cursor() as cur:
        stats = db.library_stats(cur)
        assert stats["photos"] == 5
        assert stats["faces"] == 4          # 4 readable images, one face each
        assert stats["persons"] >= 1
        cur.execute("SELECT count(*) FROM photos WHERE thumbnail_path IS NOT NULL")
        assert cur.fetchone()[0] == 4       # thumbnails for the readable images


def test_reindex_without_scan(qapp, clean_db, photo_tree: Path) -> None:
    from scanner.scanner import scan_directory
    from viewer.tasks import PipelineWorker

    scan_directory(photo_tree)  # photos already imported

    steps: list[str] = []
    worker = PipelineWorker(root=None, run_ai=True, detector_factory=lambda: _StubDetector())
    worker.step_changed.connect(steps.append)
    worker.run()

    # No scan stage when root is None; it starts at thumbnails.
    assert "Scanning" not in steps
    assert steps[0] == "Building thumbnails"
    with db.connection() as conn, conn.cursor() as cur:
        assert db.library_stats(cur)["faces"] == 4


def test_cancel_raises_at_progress(qapp) -> None:
    from viewer.tasks import PipelineCancelled, PipelineWorker

    worker = PipelineWorker(root=None, detector_factory=lambda: _StubDetector())
    worker.cancel()
    with pytest.raises(PipelineCancelled):
        worker._on_progress(1, 10)  # a cancelled worker stops at the next tick


def test_cancelled_run_emits_cancelled(qapp, clean_db, photo_tree: Path) -> None:
    from viewer.tasks import PipelineWorker

    worker = PipelineWorker(
        root=photo_tree, run_ai=True, detector_factory=lambda: _StubDetector()
    )
    finished: list[str] = []
    stopped: list[str] = []
    worker.finished_ok.connect(finished.append)
    worker.cancelled.connect(stopped.append)

    worker.cancel()   # stop as soon as the first progress tick fires
    worker.run()

    assert stopped and not finished   # ended via the cancelled path, not finished_ok
