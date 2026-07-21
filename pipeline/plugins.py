"""Pipeline plugins — the AI ingestion stages as swappable units.

Each enrichment stage (thumbnails, faces, people, CLIP, OCR) is a **plugin**
implementing a tiny contract, so new capabilities (object detection, video,
duplicates, new embedding models) can be added by writing one plugin and
registering it — without touching the core pipeline or the UI.

A plugin wraps an existing processor; it does not re-implement it. Heavy
dependencies are imported lazily inside ``run``/availability checks so importing
this module stays cheap and test-friendly.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from utils.logging_setup import get_logger

logger = get_logger("pipeline.plugins")

ProgressCallback = Callable[[int, int], None]
_UNSET = object()


@runtime_checkable
class Plugin(Protocol):
    """One ingestion stage. Runs over the photos that still need it."""

    name: str        # stable id, e.g. "faces"
    title: str       # UI step label, e.g. "Detecting faces"
    ai: bool         # True if it needs an AI model (gated by run_ai)

    def is_available(self) -> bool:
        """True if the stage can run (its dependencies/model are present)."""
        ...

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        """Process pending photos; return a short one-line summary fragment."""
        ...


# --- default backend factories (the pipeline layer owns these) -------------
def default_detector():
    """Build the InsightFace detector, or None if not installed."""
    try:
        import insightface  # noqa: F401
        from faces.detector import InsightFaceDetector

        return InsightFaceDetector()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Face model unavailable (%s)", exc)
        return None


def default_clip_backend():
    from search.clip_backend import default_backend

    return default_backend()


def default_ocr_backend():
    from ocr.backend import default_backend

    return default_backend()


# --- concrete plugins ------------------------------------------------------
class ThumbnailPlugin:
    name = "thumbnails"
    title = "Building thumbnails"
    ai = False

    def is_available(self) -> bool:
        return True

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from thumbnails.generator import generate_thumbnails

        summary = generate_thumbnails(on_progress=on_progress)
        return f"+{summary.generated} thumbnails"


class _BackendPlugin:
    """Base for plugins that need a lazily-built backend from a factory."""

    def __init__(self, factory: Optional[Callable[[], object]], default_factory) -> None:
        self._factory = factory or default_factory
        self._backend = _UNSET

    def _get(self):
        if self._backend is _UNSET:
            self._backend = self._factory()
        return self._backend

    def is_available(self) -> bool:
        return self._get() is not None


class FacePlugin(_BackendPlugin):
    name = "faces"
    title = "Detecting faces"
    ai = True

    def __init__(self, factory=None) -> None:
        super().__init__(factory, default_detector)

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from faces.processor import process_faces

        summary = process_faces(self._get(), on_progress=on_progress)
        return f"+{summary.faces} faces"


class PeoplePlugin:
    name = "people"
    title = "Recognizing people"
    ai = True

    def is_available(self) -> bool:
        return True

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from clustering.incremental import update_people

        summary = update_people()
        return f"{summary.recognized} recognized, {summary.new_people} new"


class ClipPlugin(_BackendPlugin):
    name = "clip"
    title = "Indexing search"
    ai = True

    def __init__(self, factory=None) -> None:
        super().__init__(factory, default_clip_backend)

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from search.embedding_engine import embed_images

        summary = embed_images(self._get(), on_progress=on_progress)
        return f"+{summary.embedded} search"


class PhashPlugin:
    name = "phash"
    title = "Fingerprinting for duplicates"
    ai = False  # pure Pillow; no model required

    def is_available(self) -> bool:
        return True

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from duplicates.processor import process_phashes

        summary = process_phashes(on_progress=on_progress)
        return f"+{summary.hashed} fingerprints"


class OcrPlugin(_BackendPlugin):
    name = "ocr"
    title = "Reading text (OCR)"
    ai = True

    def __init__(self, factory=None) -> None:
        super().__init__(factory, default_ocr_backend)

    def run(self, on_progress: Optional[ProgressCallback]) -> str:
        from ocr.processor import run_ocr

        summary = run_ocr(self._get(), on_progress=on_progress)
        return f"+{summary.with_text} OCR"
