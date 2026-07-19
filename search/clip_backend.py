"""CLIP embedding backend (open_clip), the first search backend.

Runs entirely locally on the GPU (CPU fallback). The heavy imports (torch,
open_clip) are lazy so the rest of the app — and the test suite — never require
them. Model weights download once on first use, then it is fully offline.

The model and pretrained tag come from settings (default ViT-B-32/openai, a
light 512-d model). Image encoding is batched, which is much faster on RTX GPUs.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from PIL import Image

from config.settings import get_settings
from search.embedding_backend import EmbeddingBackend, l2_normalize
from utils.logging_setup import get_logger

logger = get_logger("search.clip")


def clip_available() -> bool:
    """True if the CLIP runtime (torch + open_clip) is importable."""
    try:
        import torch  # noqa: F401
        import open_clip  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class ClipBackend:
    """EmbeddingBackend backed by open_clip. Lazy-loaded; GPU with CPU fallback."""

    def __init__(self) -> None:
        settings = get_settings()
        self._name = settings.clip_model
        self._pretrained = settings.clip_pretrained
        self._version = settings.clip_model_version
        self._dim = settings.clip_embedding_dim
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._device = "cpu"

    @property
    def model_id(self) -> str:
        return f"{self._name}/{self._pretrained}"

    @property
    def version(self) -> int:
        return self._version

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import open_clip  # type: ignore
        import torch  # type: ignore

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        model, _, preprocess = open_clip.create_model_and_transforms(
            self._name, pretrained=self._pretrained
        )
        model.eval().to(self._device)
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(self._name)
        logger.info("Loaded CLIP %s on %s", self.model_id, self._device)

    def encode_images(self, images: List[Image.Image]) -> np.ndarray:
        """Encode a batch of images to (N, dim) L2-normalized vectors."""
        if not images:
            return np.empty((0, self._dim), dtype=np.float32)
        self._ensure_loaded()
        import torch  # type: ignore

        tensors = [self._preprocess(img.convert("RGB")) for img in images]  # type: ignore
        batch = torch.stack(tensors).to(self._device)
        with torch.no_grad():
            feats = self._model.encode_image(batch)  # type: ignore
        return l2_normalize(feats.float().cpu().numpy())

    def encode_text(self, text: str) -> np.ndarray:
        """Encode a text query to a (dim,) L2-normalized vector."""
        self._ensure_loaded()
        import torch  # type: ignore

        tokens = self._tokenizer([text]).to(self._device)  # type: ignore
        with torch.no_grad():
            feats = self._model.encode_text(tokens)  # type: ignore
        return l2_normalize(feats.float().cpu().numpy())[0]


def default_backend() -> Optional[EmbeddingBackend]:
    """Return a ClipBackend if the runtime is installed, else None."""
    if not clip_available():
        logger.warning("CLIP runtime (torch + open_clip) not installed; search disabled")
        return None
    return ClipBackend()
