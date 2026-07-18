"""Face detection + embedding for Module 2.

Detection runs **entirely locally** via InsightFace on the GPU (with automatic
CPU fallback). No image or embedding ever leaves the machine.

The concrete model is hidden behind the :class:`FaceDetector` protocol so the
rest of the pipeline (crop saving, database writes, batching) depends only on
the small :class:`DetectedFace` value type. That keeps the processor testable
without the heavy InsightFace/ONNX runtime present, and lets the model be
swapped later without touching storage code.

Embeddings are returned **exactly as produced by the model** (raw, not
normalized). Normalization for similarity is applied at query time — see the
cosine (`<=>`) index in ``database/schema.sql``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable

import numpy as np

from config.settings import get_settings
from utils.logging_setup import get_logger

logger = get_logger("faces.detector")


@dataclass(frozen=True)
class DetectedFace:
    """One detected face in an image.

    Attributes:
        bbox: (x, y, w, h) in pixels, clamped to the image bounds.
        det_score: Detector confidence in [0, 1].
        embedding: Raw recognition embedding, length == Settings.embedding_dim.
    """

    bbox: tuple[int, int, int, int]
    det_score: float
    embedding: List[float]


@runtime_checkable
class FaceDetector(Protocol):
    """Anything that can turn an RGB image into a list of detected faces."""

    def detect(self, image_rgb: np.ndarray) -> List[DetectedFace]:
        """Detect faces in an HxWx3 RGB uint8 array."""
        ...


def _clamp_bbox(
    x1: float, y1: float, x2: float, y2: float, width: int, height: int
) -> tuple[int, int, int, int]:
    """Clamp a float (x1,y1,x2,y2) box to the image and return (x, y, w, h)."""
    ix1 = max(0, min(int(round(x1)), width - 1))
    iy1 = max(0, min(int(round(y1)), height - 1))
    ix2 = max(0, min(int(round(x2)), width))
    iy2 = max(0, min(int(round(y2)), height))
    w = max(1, ix2 - ix1)
    h = max(1, iy2 - iy1)
    return ix1, iy1, w, h


class InsightFaceDetector:
    """FaceDetector backed by InsightFace's ``FaceAnalysis`` pipeline.

    The model is loaded lazily on first use so that merely importing this
    module (e.g. during tests) does not require the runtime or download models.
    GPU is preferred; if the CUDA provider is unavailable the detector falls
    back to CPU automatically.
    """

    def __init__(self) -> None:
        self._app = None  # populated on first detect() call

    def _ensure_loaded(self) -> None:
        if self._app is not None:
            return

        # Imported lazily: heavy dependency, only needed when actually detecting.
        from insightface.app import FaceAnalysis  # type: ignore

        settings = get_settings()
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        app = FaceAnalysis(name=settings.face_model_name, providers=providers)

        ctx_id = settings.face_ctx_id
        det = settings.face_det_size
        try:
            app.prepare(ctx_id=ctx_id, det_size=(det, det))
            logger.info(
                "Loaded InsightFace model '%s' (ctx_id=%d, det_size=%d)",
                settings.face_model_name, ctx_id, det,
            )
        except Exception as exc:  # noqa: BLE001 - retry on CPU before giving up
            logger.warning("GPU init failed (%s); falling back to CPU", exc)
            app.prepare(ctx_id=-1, det_size=(det, det))
            logger.info("Loaded InsightFace model '%s' on CPU", settings.face_model_name)

        self._app = app

    def detect(self, image_rgb: np.ndarray) -> List[DetectedFace]:
        """Detect faces in an RGB image and return them above the min score."""
        self._ensure_loaded()
        assert self._app is not None  # for type-checkers; set by _ensure_loaded

        # InsightFace expects BGR (OpenCV convention).
        image_bgr = image_rgb[:, :, ::-1]
        height, width = image_rgb.shape[:2]
        min_score = get_settings().face_min_score

        results: List[DetectedFace] = []
        for face in self._app.get(image_bgr):
            score = float(getattr(face, "det_score", 0.0))
            if score < min_score:
                continue
            x1, y1, x2, y2 = (float(v) for v in face.bbox)
            bbox = _clamp_bbox(x1, y1, x2, y2, width, height)
            # `.embedding` is the raw vector; store it verbatim.
            embedding = np.asarray(face.embedding, dtype=np.float32).tolist()
            results.append(DetectedFace(bbox=bbox, det_score=score, embedding=embedding))
        return results
