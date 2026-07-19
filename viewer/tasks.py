"""Background pipeline worker for the desktop app.

Runs the whole indexing pipeline off the UI thread so the window never freezes:

    scan  ->  [plugins: thumbnails, faces, people, CLIP, OCR, ...]

The enrichment stages are **plugins** (see :mod:`pipeline`); this worker just
scans and asks the :class:`~pipeline.manager.PluginManager` to run them, so new
capabilities plug in without touching the worker. Each stage reports progress
via Qt signals delivered to the main thread. Import and "Re-index" both drive
this worker, so the user never touches the command line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore

from clustering.incremental import update_people
from faces.detector import FaceDetector
from faces.processor import process_faces
from pipeline.manager import default_manager
from pipeline.plugins import default_detector
from scanner.scanner import scan_directory
from utils.logging_setup import get_logger

logger = get_logger("viewer.tasks")

DetectorFactory = Callable[[], Optional[FaceDetector]]


class PipelineCancelled(Exception):
    """Raised cooperatively to unwind the pipeline when the user hits Stop.

    Because every stage is idempotent and commits in batches, stopping loses at
    most the current uncommitted batch; a later run continues from where this
    one left off.
    """


class PipelineWorker(QtCore.QThread):
    """Scans, then runs the ingestion plugins, emitting progress."""

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
        ocr_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        super().__init__()
        self._root = root
        self._run_ai = run_ai
        self._photo_ids = photo_ids
        # Raw factories (may be None -> the plugins use their own defaults).
        self._detector_factory = detector_factory
        self._clip_factory = clip_factory
        self._ocr_factory = ocr_factory
        self._cancelled = False

    def cancel(self) -> None:
        """Request a cooperative stop; takes effect at the next progress tick."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 - QThread entry point
        parts: list[str] = []
        try:
            # Manual selection: detect faces on exactly the chosen photos, then
            # regroup people. No scan / other stages.
            if self._photo_ids is not None:
                detector = (self._detector_factory or default_detector)()
                if detector is None:
                    self.failed.emit("Face model not installed (insightface).")
                    return
                self.step_changed.emit("Detecting faces")
                faces = process_faces(
                    detector, photo_ids=self._photo_ids, on_progress=self._on_progress
                )
                self.step_changed.emit("Recognizing people")
                update = update_people()
                self.step_changed.emit("Done")
                self.finished_ok.emit(
                    f"+{faces.faces} faces on {len(self._photo_ids)} photos  ·  "
                    f"{update.recognized} recognized, {update.new_people} new"
                )
                return

            if self._root is not None:
                self.step_changed.emit("Scanning")
                scan = scan_directory(self._root, on_progress=self._on_progress)
                parts.append(f"+{scan.processed} photos")

            manager = default_manager(
                self._detector_factory, self._clip_factory, self._ocr_factory
            )
            parts.extend(manager.run(
                run_ai=self._run_ai,
                on_step=self.step_changed.emit,
                on_progress=self._on_progress,
            ))

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
