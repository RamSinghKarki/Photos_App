"""OCR backend interface + RapidOCR implementation.

Like the face and CLIP subsystems, OCR sits behind a small interface so the
engine (RapidOCR — offline, ONNX) can be swapped for PaddleOCR or another local
model without touching the pipeline or search. Heavy imports are lazy.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

import numpy as np
from PIL import Image

from config.settings import get_settings
from utils.logging_setup import get_logger

logger = get_logger("ocr.backend")


@runtime_checkable
class OcrBackend(Protocol):
    """Extracts text from an image, entirely locally."""

    @property
    def name(self) -> str:
        ...

    def extract_text(self, image: Image.Image) -> str:
        """Return the text found in an image (empty string if none)."""
        ...


def ocr_available() -> bool:
    """True if the RapidOCR runtime is importable."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class RapidOcrBackend:
    """OcrBackend backed by RapidOCR (ONNX, offline, CPU/GPU)."""

    def __init__(self) -> None:
        self._languages = get_settings().ocr_languages
        self._engine = None

    @property
    def name(self) -> str:
        return f"rapidocr/{self._languages}"

    def _ensure_loaded(self) -> None:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            logger.info("Loaded RapidOCR (%s)", self._languages)

    def extract_text(self, image: Image.Image) -> str:
        self._ensure_loaded()
        array = np.asarray(image.convert("RGB"))
        result, _elapse = self._engine(array)  # type: ignore
        if not result:
            return ""
        # result is a list of [box, text, score]; join the text lines.
        lines: List[str] = [item[1] for item in result if len(item) >= 2 and item[1]]
        return "\n".join(lines).strip()


def default_backend() -> Optional[OcrBackend]:
    """Return a RapidOcrBackend if installed, else None."""
    if not ocr_available():
        logger.warning("RapidOCR not installed; OCR disabled")
        return None
    return RapidOcrBackend()
