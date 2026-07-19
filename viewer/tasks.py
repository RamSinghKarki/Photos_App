"""Background pipeline worker for the desktop app.

Runs the whole indexing pipeline off the UI thread so the window never freezes:

    scan  ->  thumbnails  ->  face detection (GPU)  ->  clustering

Each stage reports progress via Qt signals, which are delivered to the main
thread automatically. Import and "Re-index" both drive this worker, so the user
never has to touch the command line. If the InsightFace model is not installed,
the face/cluster stages are skipped gracefully rather than failing the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore

from clustering.processor import recluster
from faces.detector import FaceDetector
from faces.processor import process_faces
from scanner.scanner import scan_directory
from thumbnails.generator import generate_thumbnails
from utils.logging_setup import get_logger

logger = get_logger("viewer.tasks")

DetectorFactory = Callable[[], Optional[FaceDetector]]


class PipelineCancelled(Exception):
    """Raised cooperatively to unwind the pipeline when the user hits Stop.

    Because every stage is idempotent and commits in batches, stopping loses at
    most the current uncommitted batch; a later run continues from where this
    one left off.
    """


def _default_detector() -> Optional[FaceDetector]:
    """Build the real InsightFace detector, or None if it isn't installed."""
    try:
        import insightface  # noqa: F401  (probe availability before constructing)

        from faces.detector import InsightFaceDetector

        return InsightFaceDetector()
    except Exception as exc:  # noqa: BLE001 - missing model/runtime is non-fatal
        logger.warning("Face model unavailable (%s); skipping face stages", exc)
        return None


def _default_clip_backend():
    """Build the real CLIP backend, or None if the runtime isn't installed."""
    from search.clip_backend import default_backend

    return default_backend()


class PipelineWorker(QtCore.QThread):
    """Runs scan/thumbnail/face/cluster stages and emits progress."""

    step_changed = QtCore.Signal(str)      # human-readable current stage
    progress = QtCore.Signal(int, int)     # (done, total); total == 0 == indeterminate
    finished_ok = QtCore.Signal(str)       # one-line result summary
    cancelled = QtCore.Signal(str)         # user pressed Stop; partial summary
    failed = QtCore.Signal(str)            # error message

    def __init__(
        self,
        root: Optional[Path] = None,
        run_ai: bool = True,
        photo_ids: Optional[list[int]] = None,
        detector_factory: Optional[DetectorFactory] = None,
        clip_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        super().__init__()
        self._root = root
        self._run_ai = run_ai
        self._photo_ids = photo_ids
        self._detector_factory = detector_factory or _default_detector
        self._clip_factory = clip_factory or _default_clip_backend
        self._cancelled = False

    def cancel(self) -> None:
        """Request a cooperative stop; takes effect at the next progress tick."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            parts: list[str] = []

            # Manual selection: detect faces on exactly the chosen photos, then
            # regroup people. No scan / thumbnail stages.
            if self._photo_ids is not None:
                detector = self._detector_factory()
                if detector is None:
                    self.failed.emit("Face model not installed (insightface).")
                    return
                self.step_changed.emit("Detecting faces")
                faces = process_faces(
                    detector, photo_ids=self._photo_ids, on_progress=self._on_progress
                )
                self.step_changed.emit("Grouping people")
                clusters = recluster()
                self.step_changed.emit("Done")
                self.finished_ok.emit(
                    f"+{faces.faces} faces on {len(self._photo_ids)} photos  ·  "
                    f"{clusters.persons} people"
                )
                return

            if self._root is not None:
                self.step_changed.emit("Scanning")
                scan = scan_directory(self._root, on_progress=self._on_progress)
                parts.append(f"+{scan.processed} photos")

            self.step_changed.emit("Building thumbnails")
            thumbs = generate_thumbnails(on_progress=self._on_progress)
            parts.append(f"+{thumbs.generated} thumbnails")

            if self._run_ai:
                detector = self._detector_factory()
                if detector is not None:
                    self.step_changed.emit("Detecting faces")
                    faces = process_faces(detector, on_progress=self._on_progress)
                    parts.append(f"+{faces.faces} faces")

                    self.step_changed.emit("Grouping people")
                    clusters = recluster()
                    parts.append(f"{clusters.persons} people")
                else:
                    parts.append("faces skipped (no model)")

                # Semantic-search index (optional; skipped if CLIP not installed).
                clip_backend = self._clip_factory()
                if clip_backend is not None:
                    from search.embedding_engine import embed_images

                    self.step_changed.emit("Indexing search")
                    emb = embed_images(clip_backend, on_progress=self._on_progress)
                    parts.append(f"+{emb.embedded} search")

            self.step_changed.emit("Done")
            self.finished_ok.emit("  ·  ".join(parts) if parts else "Nothing to do")
        except PipelineCancelled:
            logger.info("Pipeline stopped by user")
            self.cancelled.emit("  ·  ".join(parts) if parts else "Stopped")
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            logger.exception("Pipeline failed")
            self.failed.emit(str(exc))

    def _on_progress(self, done: int, total: int) -> None:
        # Runs on the worker thread. Raising here unwinds the current stage;
        # committed batches persist, so a later run resumes from here.
        if self._cancelled:
            raise PipelineCancelled()
        self.progress.emit(done, total)  # emit() marshals to the GUI thread safely
